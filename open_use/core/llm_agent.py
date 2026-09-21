"""Universal System 2 Cognitive Controller (LLM Proxy Agent).

Designed to be completely environment-agnostic:
- Works standalone in CLI, terminal, Docker, Jupyter, scripts, or any AI agent framework (LangChain, AutoGen, CrewAI).
- Zero vendor lock-in: NOT tied to Antigravity or any specific proprietary IDE.
- Full multi-provider support:
  1. Google Gemini (via google-genai SDK or zero-dependency pure REST)
  2. OpenAI & OpenAI-Compatible (DeepSeek, Ollama, vLLM, LM Studio, Groq, OpenRouter)
  3. Anthropic Claude (Messages API with base64 vision)
  4. Pluggable Custom Delegate (any user-provided callable or external agent)
  5. Deterministic Cognitive Heuristic (zero-network / offline recovery)
"""

from __future__ import annotations

import abc
import base64
import json
import logging
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union

from .config import (
    get_llm_api_key,
    get_llm_base_url,
    get_llm_model,
    get_llm_provider,
    load_env,
)

logger = logging.getLogger("open_use.core.llm_agent")


class LLMProviderType(str, Enum):
    AUTO = "auto"
    GEMINI = "gemini"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    CUSTOM = "custom"
    HEURISTIC = "heuristic"


@dataclass
class AgentContext:
    """Universal state representation passed to the System 2 Agent."""
    goal: str
    escalation_reason: str
    screen_summary: str
    image_path: Optional[str] = None
    elements: List[Any] = field(default_factory=list)
    history: List[Dict[str, Any]] = field(default_factory=list)
    platform: str = sys.platform
    active_app: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMStepDecision:
    """Universal action decision produced by System 2 LLM Agent."""
    action_type: str           # "click", "double_click", "right_click", "press_key", "hotkey", "type_text", "paste_and_send", "scroll", "focus_chat_input", "wait", "done", "custom"
    target_label: str
    target_point: Optional[List[int]] = None
    key_name: Optional[str] = None
    hotkeys: Optional[List[str]] = None
    text_content: Optional[str] = None
    scroll_delta: Optional[int] = None
    rationale: str = ""
    provider_used: str = ""
    raw_response: Dict[str, Any] = field(default_factory=dict)


def _encode_image_base64(image_path: Optional[str]) -> Optional[str]:
    """Safely read and base64-encode an image file."""
    if not image_path or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.warning(f"Failed to read image for LLM perception: {e}")
        return None


def _clean_and_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """Robustly extract and parse a JSON object from raw LLM output text."""
    if not text or not text.strip():
        return None
    # 1. Match code blocks ```json ... ``` or ``` ... ```
    code_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if code_block:
        try:
            return json.loads(code_block.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Greedy search for outermost curly braces
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        snippet = text[first_brace:last_brace + 1]
        try:
            return json.loads(snippet)
        except json.JSONDecodeError:
            # Try cleaning trailing commas
            cleaned = re.sub(r",\s*([\]}])", r"\1", snippet)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError:
                pass
    return None


class BaseLLMBackend(abc.ABC):
    """Abstract interface for LLM backends."""

    @abc.abstractmethod
    def is_available(self) -> bool:
        """Check if required credentials or packages are present."""
        pass

    @abc.abstractmethod
    def generate_decision(self, ctx: AgentContext) -> Optional[LLMStepDecision]:
        """Generate a structured action decision from context."""
        pass


class GeminiBackend(BaseLLMBackend):
    """Google Gemini backend supporting both official google.genai SDK and zero-dependency REST API."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or get_llm_api_key("gemini")
        self.model = model or get_llm_model("gemini") or "gemini-2.0-flash"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate_decision(self, ctx: AgentContext) -> Optional[LLMStepDecision]:
        prompt = self._build_prompt(ctx)
        
        # 1. Try official google.genai SDK if installed
        try:
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=self.api_key)
            contents = [prompt]
            if ctx.image_path and os.path.exists(ctx.image_path):
                with open(ctx.image_path, "rb") as f:
                    contents.append(types.Part.from_bytes(data=f.read(), mime_type="image/png"))

            resp = client.models.generate_content(
                model=self.model,
                contents=contents,
            )
            parsed = _clean_and_parse_json(resp.text)
            if parsed:
                return self._to_decision(parsed, provider="gemini_sdk")
        except ImportError:
            logger.debug("google.genai SDK not installed, using universal pure-REST Gemini backend.")
        except Exception as e:
            logger.warning(f"google.genai SDK invocation failed: {e}. Falling back to REST...")

        # 2. Universal pure-REST fallback (Zero third-party dependencies required)
        return self._generate_rest(ctx, prompt)

    def _generate_rest(self, ctx: AgentContext, prompt: str) -> Optional[LLMStepDecision]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}"
        parts: List[Dict[str, Any]] = [{"text": prompt}]

        b64 = _encode_image_base64(ctx.image_path)
        if b64:
            parts.append({
                "inlineData": {
                    "mimeType": "image/png",
                    "data": b64,
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                candidates = data.get("candidates", [])
                if candidates:
                    parts_out = candidates[0].get("content", {}).get("parts", [])
                    if parts_out:
                        text = parts_out[0].get("text", "")
                        parsed = _clean_and_parse_json(text)
                        if parsed:
                            return self._to_decision(parsed, provider="gemini_rest")
        except Exception as e:
            logger.warning(f"Gemini REST call failed: {e}")
        return None

    def _build_prompt(self, ctx: AgentContext) -> str:
        el_lines = [
            f"[{getattr(e, 'id', i)}] {getattr(e, 'category', '').upper()}: '{getattr(e, 'label', '')}' @ center={getattr(e, 'center', [])}"
            for i, e in enumerate(ctx.elements[:45], 1)
        ]
        return (
            "You are the System 2 Cognitive Controller in an autonomous desktop automation engine.\n"
            "System 1 (fast micro-action runner) reached an impasse or error.\n"
            f"Goal: {ctx.goal}\n"
            f"Escalation Cause: {ctx.escalation_reason}\n"
            f"Platform: {ctx.platform}\n"
            f"Recent Action History: {json.dumps(ctx.history[-4:] if ctx.history else [])}\n"
            f"Detected UI Elements:\n" + "\n".join(el_lines) + "\n\n"
            "Analyze the interface, reason through the obstacle (e.g. dismiss modal, focus input, submit search, or complete goal), "
            "and output your decision as a single valid JSON object:\n"
            "{\n"
            '  "action_type": "click" | "press_key" | "hotkey" | "type_text" | "paste_and_send" | "focus_chat_input" | "wait" | "done",\n'
            '  "target_label": "description of target",\n'
            '  "target_point": [x, y] or null,\n'
            '  "key_name": "escape" | "return" | null,\n'
            '  "hotkeys": ["cmd", "v"] or null,\n'
            '  "text_content": "text to type" or null,\n'
            '  "rationale": "Clear reasoning why this breaks the impasse"\n'
            "}"
        )

    def _to_decision(self, data: Dict[str, Any], provider: str) -> LLMStepDecision:
        return LLMStepDecision(
            action_type=data.get("action_type", "wait"),
            target_label=data.get("target_label", "gemini_action"),
            target_point=data.get("target_point"),
            key_name=data.get("key_name"),
            hotkeys=data.get("hotkeys"),
            text_content=data.get("text_content"),
            rationale=data.get("rationale", ""),
            provider_used=provider,
            raw_response=data,
        )


class OpenAICompatibleBackend(BaseLLMBackend):
    """Universal OpenAI-compatible backend (supports OpenAI, DeepSeek, Ollama, vLLM, LM Studio, Groq, OpenRouter)."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
    ):
        self.api_key = api_key or get_llm_api_key("openai") or "none"
        self.base_url = (base_url or get_llm_base_url("openai") or "https://api.openai.com/v1").rstrip("/")
        self.model = model or get_llm_model("openai") or "gpt-4o"

    def is_available(self) -> bool:
        # Local models (Ollama/vLLM) might not require an API key
        return bool(self.api_key and self.api_key != "none") or "localhost" in self.base_url or "127.0.0.1" in self.base_url

    def generate_decision(self, ctx: AgentContext) -> Optional[LLMStepDecision]:
        url = f"{self.base_url}/chat/completions"
        prompt = self._build_prompt(ctx)

        content_items: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        b64 = _encode_image_base64(ctx.image_path)
        if b64:
            content_items.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"}
            })

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content_items}],
            "temperature": 0.1,
            "max_tokens": 1024,
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key and self.api_key != "none":
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=35.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text = data["choices"][0]["message"]["content"]
                parsed = _clean_and_parse_json(text)
                if parsed:
                    return LLMStepDecision(
                        action_type=parsed.get("action_type", "wait"),
                        target_label=parsed.get("target_label", "openai_action"),
                        target_point=parsed.get("target_point"),
                        key_name=parsed.get("key_name"),
                        hotkeys=parsed.get("hotkeys"),
                        text_content=parsed.get("text_content"),
                        rationale=parsed.get("rationale", ""),
                        provider_used=f"openai_compatible({self.model})",
                        raw_response=parsed,
                    )
        except Exception as e:
            logger.warning(f"OpenAI-compatible call to {self.base_url} failed: {e}")
        return None

    def _build_prompt(self, ctx: AgentContext) -> str:
        el_lines = [
            f"[{getattr(e, 'id', i)}] {getattr(e, 'category', '').upper()}: '{getattr(e, 'label', '')}' @ center={getattr(e, 'center', [])}"
            for i, e in enumerate(ctx.elements[:45], 1)
        ]
        return (
            "You are the System 2 Cognitive Controller in a universal desktop automation agent.\n"
            "System 1 micro-actions stalled or encountered an exception.\n"
            f"Task Objective: {ctx.goal}\n"
            f"Escalation Trigger: {ctx.escalation_reason}\n"
            f"OS Platform: {ctx.platform}\n"
            f"Recent Steps: {json.dumps(ctx.history[-4:] if ctx.history else [])}\n"
            f"UI Components:\n" + "\n".join(el_lines) + "\n\n"
            "Determine the next strategic action to resolve the situation and return pure JSON:\n"
            "{\n"
            '  "action_type": "click" | "press_key" | "hotkey" | "type_text" | "paste_and_send" | "focus_chat_input" | "wait" | "done",\n'
            '  "target_label": "description",\n'
            '  "target_point": [x, y] or null,\n'
            '  "key_name": "escape" | "return" | null,\n'
            '  "hotkeys": ["cmd", "v"] or null,\n'
            '  "text_content": "text" or null,\n'
            '  "rationale": "reason"\n'
            "}"
        )


class AnthropicBackend(BaseLLMBackend):
    """Anthropic Claude backend using standard Messages API with multimodal vision."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or get_llm_api_key("anthropic")
        self.model = model or get_llm_model("anthropic") or "claude-3-5-sonnet-20241022"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate_decision(self, ctx: AgentContext) -> Optional[LLMStepDecision]:
        url = "https://api.anthropic.com/v1/messages"
        prompt = self._build_prompt(ctx)

        content_items: List[Dict[str, Any]] = []
        b64 = _encode_image_base64(ctx.image_path)
        if b64:
            content_items.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": b64,
                }
            })
        content_items.append({"type": "text", "text": prompt})

        payload = {
            "model": self.model,
            "max_tokens": 1024,
            "temperature": 0.1,
            "messages": [{"role": "user", "content": content_items}],
        }

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=35.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                text_blocks = [c.get("text", "") for c in data.get("content", []) if c.get("type") == "text"]
                full_text = "".join(text_blocks)
                parsed = _clean_and_parse_json(full_text)
                if parsed:
                    return LLMStepDecision(
                        action_type=parsed.get("action_type", "wait"),
                        target_label=parsed.get("target_label", "claude_action"),
                        target_point=parsed.get("target_point"),
                        key_name=parsed.get("key_name"),
                        hotkeys=parsed.get("hotkeys"),
                        text_content=parsed.get("text_content"),
                        rationale=parsed.get("rationale", ""),
                        provider_used=f"anthropic({self.model})",
                        raw_response=parsed,
                    )
        except Exception as e:
            logger.warning(f"Anthropic Claude API call failed: {e}")
        return None

    def _build_prompt(self, ctx: AgentContext) -> str:
        return (
            f"You are the System 2 Cognitive Controller in a desktop automation framework.\n"
            f"Objective: {ctx.goal}\n"
            f"Blocker: {ctx.escalation_reason}\n"
            f"UI Context: {ctx.screen_summary[:1500]}\n"
            "Return a JSON object specifying the single next action: action_type, target_label, target_point, key_name, hotkeys, text_content, rationale."
        )


class CustomDelegateBackend(BaseLLMBackend):
    """Allows wrapping any external agent function, class, or framework (LangChain/AutoGen/CrewAI/Bespoke)."""

    def __init__(self, delegate_fn: Callable[[AgentContext], Union[LLMStepDecision, Dict[str, Any], str]]):
        self.delegate_fn = delegate_fn

    def is_available(self) -> bool:
        return callable(self.delegate_fn)

    def generate_decision(self, ctx: AgentContext) -> Optional[LLMStepDecision]:
        try:
            res = self.delegate_fn(ctx)
            if isinstance(res, LLMStepDecision):
                res.provider_used = "custom_delegate"
                return res
            elif isinstance(res, dict):
                return LLMStepDecision(
                    action_type=res.get("action_type", "wait"),
                    target_label=res.get("target_label", "custom_delegate"),
                    target_point=res.get("target_point"),
                    key_name=res.get("key_name"),
                    hotkeys=res.get("hotkeys"),
                    text_content=res.get("text_content"),
                    rationale=res.get("rationale", "Custom agent decision"),
                    provider_used="custom_delegate",
                    raw_response=res,
                )
            elif isinstance(res, str):
                parsed = _clean_and_parse_json(res)
                if parsed:
                    return LLMStepDecision(
                        action_type=parsed.get("action_type", "wait"),
                        target_label=parsed.get("target_label", "custom_delegate_str"),
                        target_point=parsed.get("target_point"),
                        key_name=parsed.get("key_name"),
                        hotkeys=parsed.get("hotkeys"),
                        text_content=parsed.get("text_content"),
                        rationale=parsed.get("rationale", ""),
                        provider_used="custom_delegate",
                        raw_response=parsed,
                    )
        except Exception as e:
            logger.warning(f"Custom delegate agent failed: {e}")
        return None


class CognitiveHeuristicBackend(BaseLLMBackend):
    """Deterministic, zero-network emergency cognitive heuristic engine."""

    def is_available(self) -> bool:
        return True

    def generate_decision(self, ctx: AgentContext) -> LLMStepDecision:
        last_action = ctx.history[-1].get("action") if ctx.history else "none"
        reason = ctx.escalation_reason.lower()

        # 1. Error dialog or popup overlay -> Press Escape
        if any(kw in reason for kw in ("modal", "popup", "dialog", "wrong_modal", "drift")):
            return LLMStepDecision(
                action_type="press_key",
                target_label="dismiss_popup_esc",
                key_name="escape",
                rationale="Deterministic escape key to dismiss intrusive modal or dialog",
                provider_used="cognitive_heuristic",
            )

        # 2. Input was just typed -> Press Return
        if last_action == "type_text" or "type_text" in reason:
            return LLMStepDecision(
                action_type="press_key",
                target_label="submit_search_return",
                key_name="return",
                rationale="Deterministic submission of typed input using Return",
                provider_used="cognitive_heuristic",
            )

        # 3. Chat goal and impasse after input -> Focus input or paste
        if last_action in ("press_return", "click") and any(kw in ctx.goal.lower() for kw in ("qq", "wechat", "微信", "发给", "发送")):
            return LLMStepDecision(
                action_type="paste_and_send",
                target_label="chat_paste_and_send",
                rationale="Deterministic injection of payload into chat input",
                provider_used="cognitive_heuristic",
            )

        # 4. Search input visible in elements -> Focus it
        for el in ctx.elements:
            lbl = getattr(el, "label", "").lower()
            cat = getattr(el, "category", "")
            if "搜索" in lbl or "search" in lbl or cat == "input":
                return LLMStepDecision(
                    action_type="click",
                    target_label=f"focus_input_{lbl}",
                    target_point=getattr(el, "center", None),
                    rationale="Deterministic focus on candidate input field",
                    provider_used="cognitive_heuristic",
                )

        # Default fallback
        return LLMStepDecision(
            action_type="focus_chat_input",
            target_label="focus_chat_input_default",
            rationale="Deterministic focus on application interaction region",
            provider_used="cognitive_heuristic",
        )


class UniversalLLMProxyAgent:
    """Universal System 2 Cognitive Controller.
    
    Orchestrates fallback across:
    1. User Custom Delegate (if provided)
    2. Primary configured LLM (Gemini / OpenAI / Anthropic)
    3. Secondary discovered LLMs
    4. Deterministic Cognitive Heuristic
    """

    def __init__(
        self,
        provider: str = "auto",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        custom_delegate: Optional[Callable[[AgentContext], Any]] = None,
    ):
        load_env()
        self.provider = (provider or get_llm_provider()).lower()
        self.custom_delegate = custom_delegate

        # Initialize backends
        self.backends: List[BaseLLMBackend] = []

        # 1. Custom delegate gets top priority if provided
        if self.custom_delegate:
            self.backends.append(CustomDelegateBackend(self.custom_delegate))

        # 2. Configured or auto-detected providers
        if self.provider in ("gemini", "google"):
            self.backends.append(GeminiBackend(api_key=api_key, model=model))
        elif self.provider == "openai":
            self.backends.append(OpenAICompatibleBackend(api_key=api_key, base_url=base_url, model=model))
        elif self.provider == "anthropic":
            self.backends.append(AnthropicBackend(api_key=api_key, model=model))
        else:
            # AUTO mode: Register all backends in order of credential availability
            gemini = GeminiBackend(api_key=api_key, model=model)
            if gemini.is_available():
                self.backends.append(gemini)

            openai_backend = OpenAICompatibleBackend(api_key=api_key, base_url=base_url, model=model)
            if openai_backend.is_available():
                self.backends.append(openai_backend)

            anthropic = AnthropicBackend(api_key=api_key, model=model)
            if anthropic.is_available():
                self.backends.append(anthropic)

        # 3. Always register Cognitive Heuristic as unbreakable fallback
        self.heuristic_backend = CognitiveHeuristicBackend()
        self.backends.append(self.heuristic_backend)

    def act(
        self,
        goal: str,
        escalation_reason: str,
        screen_summary: str,
        image_path: Optional[str] = None,
        elements: Optional[List[Any]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        platform: Optional[str] = None,
        active_app: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> LLMStepDecision:
        """Execute high-order cognitive reasoning to break deadlocks and return a structured decision."""
        ctx = AgentContext(
            goal=goal,
            escalation_reason=escalation_reason,
            screen_summary=screen_summary,
            image_path=image_path,
            elements=elements or [],
            history=history or [],
            platform=platform or sys.platform,
            active_app=active_app,
            metadata=metadata or {},
        )

        print(f"\n🧠 [Universal System 2 LLM Agent] Takeover initiated! Cause: '{escalation_reason}'")

        for backend in self.backends:
            if backend.is_available():
                try:
                    dec = backend.generate_decision(ctx)
                    if dec and dec.action_type:
                        print(f"  ⚡ Decision rendered by [{dec.provider_used}]: {dec.action_type} -> '{dec.target_label}' ({dec.rationale})")
                        return dec
                except Exception as e:
                    logger.warning(f"Backend {backend.__class__.__name__} failed: {e}. Trying next backend...")

        # Absolute safety net
        return self.heuristic_backend.generate_decision(ctx)


# Backwards compatibility alias
LLMProxyAgent = UniversalLLMProxyAgent
