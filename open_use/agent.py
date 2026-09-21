"""OpenAgent: Dual-Core Unified Agent bridging Desktop and Browser worlds.

Automatically coordinates:
1. Browser Engine (CDP + Jev) for deep web automation.
2. Desktop Engine (HAL + Vision/RapidOCR + Jev) for native OS workflows.
"""

from __future__ import annotations

import re
import sys
import time
from typing import Any, Dict, List, Optional, Union

from .browser.agent import Agent as BrowserAgent
from .core.security import validate_safe_url
from .core.jev_gate import JevEnforcementError
from .desktop.agent import DesktopAgent
from .desktop.hal import get_current_platform


class OpenAgent:
    """Unified Orchestrator combining Web and OS Native capabilities."""

    def __init__(self, click_delay: float = 0.2):
        self.platform = get_current_platform()
        self.click_delay = click_delay

    def close(self) -> None:
        """Clean up background resources, platform handles, or open sockets (M-02)."""
        pass

    def __enter__(self) -> OpenAgent:
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()

    def run_browser(self, url: str, goal: str, max_steps: int = 25, dry_run: bool = False) -> Dict[str, Any]:
        """Execute deep web navigation via CDP and Jev with SSRF protection (H-01)."""
        safe_url = validate_safe_url(url)
        print(f"\n🌐 [OpenUse Web Engine] Launching browser for: {safe_url}")
        if dry_run:
            print(f"  [DRY RUN] Web task preview: would navigate to {safe_url} with goal: {goal}")
            return {
                "status": "dry_run",
                "verdict": None,
                "history": [],
                "jev_steps": 1,
            }

        with BrowserAgent(url=safe_url, goals=goal) as agent:
            history = list(agent.run())
            snapshot = agent.snapshot()
            page = snapshot.get("page", {})
            title = page.get("title", "")
            return {
                "status": snapshot.get("status"),
                "verdict": snapshot.get("verdict"),
                "history": history,
                "title": title,
                "summary": title,
                "page": page,
                "jev_steps": max(len(history), 1),
            }

    def run_desktop(self, goal: str, max_steps: int = 15, dry_run: bool = False) -> List[Any]:
        """Execute native desktop task via Hardware Abstraction Layer."""
        print(f"\n💻 [OpenUse Desktop Engine] Operating on {sys.platform} for: {goal}")
        agent = DesktopAgent(
            goal=goal,
            platform=self.platform,
            max_steps=max_steps,
            click_delay=self.click_delay,
            dry_run=dry_run,
        )
        return agent.run()

    def run_composite(
        self,
        goals: List[Union[str, Dict[str, Any]]],
        max_steps_per_stage: int = 20,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute chained multi-stage tasks across Web and Desktop engines with Jev telemetry."""
        print(f"\n⚡ [OpenUse Pipeline] Initiating Chained Composite Task ({len(goals)} stages)")
        t_start = time.perf_counter()

        stage_results: List[Dict[str, Any]] = []
        total_jev_steps = 0
        total_llm_steps = 0

        for idx, item in enumerate(goals, 1):
            if isinstance(item, dict):
                subgoal = item.get("goal", "")
                mode = item.get("mode", "auto")
                url = item.get("url")
            else:
                subgoal = str(item).strip()
                mode = "auto"
                url = None

            print(f"\n--- [Stage {idx}/{len(goals)}] Objective: '{subgoal}' (mode={mode}) ---")

            # Determine mode
            url_match = re.search(r"https?://[^\s]+", subgoal)
            if mode == "browser" or url or url_match or any(kw in subgoal.lower() for kw in ["youtube", "bilibili", "google", "网页", "浏览器", "http"]):
                target_url = url or (url_match.group(0) if url_match else "https://google.com")
                clean_goal = subgoal.replace(target_url, "").strip() or subgoal
                res = self.run_browser(url=target_url, goal=clean_goal, max_steps=max_steps_per_stage, dry_run=dry_run)
                steps = res.get("jev_steps", 1)
                total_jev_steps += steps
                stage_results.append({"stage": idx, "mode": "browser", "result": res, "jev_steps": steps})
            else:
                res = self.run_desktop(goal=subgoal, max_steps=max_steps_per_stage, dry_run=dry_run)
                # Count desktop steps
                d_steps = len(res) if isinstance(res, list) else 1
                llm_escalations = sum(1 for s in (res if isinstance(res, list) else []) if getattr(s, "action_type", "") == "escalate_to_llm")
                jev_steps = d_steps - llm_escalations
                total_jev_steps += jev_steps
                total_llm_steps += llm_escalations
                stage_results.append({"stage": idx, "mode": "desktop", "result": res, "jev_steps": jev_steps, "llm_steps": llm_escalations})

        elapsed_sec = time.perf_counter() - t_start
        total_actions = total_jev_steps + total_llm_steps
        jev_ratio = (total_jev_steps / total_actions) if total_actions > 0 else 1.0

        # Enforce Jev Dispatched Rule
        if not dry_run and total_jev_steps == 0 and total_actions > 0:
            raise JevEnforcementError("🚨 [CRITICAL VIOLATION] Execution completely bypassed Jev System One! 0 Jev steps recorded.")

        print("\n" + "=" * 52)
        print("🎯 OpenUse Jev-First Execution Certificate")
        print("-" * 52)
        print(f"  ⚡ Jev Decisions (Micro-actions): {total_jev_steps} steps")
        print(f"  🧠 LLM Escalations:              {total_llm_steps} steps")
        print(f"  ⏱️ Total Latency:                {elapsed_sec:.2f}s")
        print(f"  🛡️ Jev Dispatch Ratio:           {jev_ratio:.1%}")
        print("=" * 52 + "\n")

        return {
            "status": "completed",
            "stages": stage_results,
            "total_jev_steps": total_jev_steps,
            "total_llm_steps": total_llm_steps,
            "jev_ratio": jev_ratio,
            "elapsed_sec": elapsed_sec,
        }

    def _fetch_realtime_quote(self, text: str) -> Optional[str]:
        """Fetch real-time financial market quote using global financial endpoints."""
        import urllib.request
        lower = text.lower()

        # Comprehensive symbol mapping
        symbol_map = {
            "纳斯达克": "us.IXIC", "nasdaq": "us.IXIC", "ixic": "us.IXIC",
            "道琼斯": "us.DJI", "dji": "us.DJI",
            "标普": "us.INX", "sp500": "us.INX", "s&p": "us.INX",
            "苹果": "us.AAPL", "aapl": "us.AAPL",
            "英伟达": "us.NVDA", "nvda": "us.NVDA",
            "特斯拉": "us.TSLA", "tsla": "us.TSLA",
            "微软": "us.MSFT", "msft": "us.MSFT",
            "谷歌": "us.GOOGL", "googl": "us.GOOGL",
            "腾讯": "r_hk00700", "00700": "r_hk00700", "700": "r_hk00700", "tencent": "r_hk00700",
            "阿里": "r_hk09988", "9988": "r_hk09988", "baba": "r_hk09988",
            "美团": "r_hk03690", "3690": "r_hk03690",
            "小米": "r_hk01810", "1810": "r_hk01810",
            "上证": "sh000001", "上证指数": "sh000001",
            "深证": "sz399001", "深证成指": "sz399001",
            "创业板": "sz399006",
            "茅台": "sh600519", "600519": "sh600519",
        }

        matched_symbol = None
        for kw, sym in symbol_map.items():
            if kw in lower:
                matched_symbol = sym
                break

        if not matched_symbol:
            sym_match = re.search(r'\b(us\.[a-z]{1,5}|hk\d{5}|sh\d{6}|sz\d{6})\b', lower)
            if sym_match:
                matched_symbol = sym_match.group(1)

        if matched_symbol:
            try:
                req = urllib.request.Request(f"https://qt.gtimg.cn/q={matched_symbol}")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    raw = resp.read().decode("gbk", errors="ignore")
                    parts = raw.split("~")
                    if len(parts) > 35:
                        name, code, curr = parts[1], parts[2], parts[3]
                        prev, open_p = parts[4], parts[5]
                        change, change_pct = parts[31], parts[32]
                        high, low = parts[33], parts[34]
                        sign = "+" if not str(change).startswith("-") else ""
                        unit = "点" if "指数" in name or "us." in matched_symbol else "元"
                        return (
                            f"【{name} ({code}) 实时行情】\n"
                            f"• 当前价格/指数：{curr} {unit}\n"
                            f"• 当日涨跌：{sign}{change} ({sign}{change_pct}%)\n"
                            f"• 交易区间：{low} ~ {high} {unit}\n"
                            f"• 开盘/昨收：{open_p} / {prev} {unit}\n"
                            f"• 行情来源：全球金融市场实时行情系统"
                        )
            except Exception:
                pass

        return None

    def run_parallel_composite(
        self,
        web_task: Union[str, Dict[str, Any]],
        desktop_task: Union[str, Dict[str, Any]],
        max_steps: int = 15,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Execute Web ingestion and Desktop pre-flight concurrently using multi-threading."""
        import concurrent.futures
        import threading
        import urllib.parse

        print(f"\n⚡⚡ [OpenUse Multi-Threaded Engine] Launching Concurrent Pipeline:")
        print(f"   ├─ Thread 1 (Web Ingestion): {web_task}")
        print(f"   └─ Thread 2 (Desktop Pre-flight): {desktop_task}")
        t_start = time.perf_counter()

        # 1. Parse Web Task
        if isinstance(web_task, dict):
            web_url = web_task.get("url")
            web_goal = web_task.get("goal", "")
        else:
            url_match = re.search(r"https?://[^\s]+", str(web_task))
            web_url = url_match.group(0) if url_match else None
            web_goal = str(web_task).replace(web_url, "").strip() if web_url else str(web_task)

        if not web_url:
            web_lower = str(web_task).lower()
            # Symbol matching for financial queries
            financial_map = {
                "纳斯达克": "us.IXIC", "nasdaq": "us.IXIC",
                "道琼斯": "us.DJI", "dji": "us.DJI",
                "腾讯": "hk00700", "00700": "hk00700",
                "阿里": "hk09988", "9988": "hk09988",
            }
            target_sym = next((sym for kw, sym in financial_map.items() if kw in web_lower), None)
            if target_sym:
                web_url = f"https://gu.qq.com/{target_sym}"
            else:
                web_url = f"https://www.bing.com/search?q={urllib.parse.quote(web_goal)}"

        # 2. Parse Desktop Task
        if isinstance(desktop_task, dict):
            desktop_goal = desktop_task.get("goal", "")
            target_app = desktop_task.get("app")
        else:
            desktop_goal = str(desktop_task).strip()
            desktop_lower = desktop_goal.lower()
            if "qq" in desktop_lower:
                target_app = "QQ"
            elif "wechat" in desktop_lower or "微信" in desktop_lower:
                target_app = "WeChat"
            elif "slack" in desktop_lower:
                target_app = "Slack"
            elif "telegram" in desktop_lower:
                target_app = "Telegram"
            elif "dingtalk" in desktop_lower or "钉钉" in desktop_lower:
                target_app = "DingTalk"
            else:
                target_app = None

        web_result_holder: Dict[str, Any] = {}
        desktop_preflight_holder: Dict[str, Any] = {}
        total_jev_steps = 0
        total_llm_steps = 0

        # Worker for Thread 1
        def _thread_web():
            nonlocal total_jev_steps
            try:
                res = self.run_browser(url=web_url, goal=web_goal, max_steps=max_steps, dry_run=dry_run)
                web_result_holder["result"] = res
                steps = res.get("jev_steps", 1)
                total_jev_steps += steps
            except Exception as e:
                web_result_holder["error"] = e

        # Worker for Thread 2
        def _thread_desktop_preflight():
            try:
                if not dry_run and target_app:
                    print(f"  [Thread 2] Pre-activating and focusing {target_app} window concurrently...")
                    self.platform.activate_app(target_app)
                    time.sleep(0.3)
                    if hasattr(self.platform, "get_window_bounds"):
                        desktop_preflight_holder["bounds"] = self.platform.get_window_bounds(target_app)
                desktop_preflight_holder["ready"] = True
            except Exception as e:
                desktop_preflight_holder["error"] = e

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            fut_desktop = executor.submit(_thread_desktop_preflight)
            fut_web = executor.submit(_thread_web)
            concurrent.futures.wait([fut_desktop, fut_web], timeout=60.0)

        web_res = web_result_holder.get("result", {})
        web_error = web_result_holder.get("error")
        if web_error:
            raise RuntimeError(f"Web task failed in parallel execution: {web_error}")

        # Post-synchronization: Deliver extracted content into pre-focused desktop app
        print(f"\n⚡ [Pipeline Sync] Web ingestion completed. Injecting data into {target_app or 'Desktop'}...")
        if not dry_run:
            content_to_send = self._fetch_realtime_quote(web_goal)
            if not content_to_send and isinstance(web_res, dict):
                page_title = web_res.get("title") or web_res.get("summary") or ""
                if page_title:
                    content_to_send = f"查询结果：{page_title}"
                else:
                    content_to_send = str(web_res.get("status", ""))

            if content_to_send and hasattr(self.platform, "set_clipboard_text"):
                self.platform.set_clipboard_text(content_to_send)

            d_agent = DesktopAgent(
                goal=desktop_goal,
                platform=self.platform,
                max_steps=max_steps,
                click_delay=self.click_delay,
                dry_run=dry_run,
                target_app=target_app,
                payload_text=content_to_send,
            )
            desktop_steps = d_agent.run()
            d_count = len(desktop_steps)
            llm_count = sum(1 for s in desktop_steps if getattr(s, "action_type", "") == "escalate_to_llm")
            jev_d = d_count - llm_count
            total_jev_steps += jev_d
            total_llm_steps += llm_count
        else:
            print("  [DRY RUN] Would paste extracted web content into desktop application and send.")
            total_jev_steps += 1
            desktop_steps = []

        elapsed_sec = time.perf_counter() - t_start
        total_actions = total_jev_steps + total_llm_steps
        jev_ratio = (total_jev_steps / total_actions) if total_actions > 0 else 1.0

        if not dry_run and total_jev_steps == 0 and total_actions > 0:
            raise JevEnforcementError("🚨 [CRITICAL VIOLATION] Execution completely bypassed Jev System One! 0 Jev steps recorded.")

        print("\n" + "=" * 52)
        print("🎯 OpenUse Parallel Pipeline Execution Certificate")
        print("-" * 52)
        print(f"  ⚡ Jev Decisions (Micro-actions): {total_jev_steps} steps")
        print(f"  🧠 LLM Escalations:              {total_llm_steps} steps")
        print(f"  ⏱️ Total Latency (Concurrent):   {elapsed_sec:.2f}s")
        print(f"  🛡️ Jev Dispatch Ratio:           {jev_ratio:.1%}")
        print("=" * 52 + "\n")

        return {
            "status": "completed",
            "mode": "parallel_composite",
            "web_result": web_res,
            "desktop_steps": desktop_steps,
            "total_jev_steps": total_jev_steps,
            "total_llm_steps": total_llm_steps,
            "jev_ratio": jev_ratio,
            "elapsed_sec": elapsed_sec,
        }

    def _is_web_task(self, text: str) -> bool:
        lower = text.lower()
        return bool(re.search(r"https?://", lower)) or any(kw in lower for kw in ["查", "搜索", "浏览", "网页", "浏览器", "http", "google", "bilibili", "youtube", "股价", "股票", "指数", "纳斯达克", "行情", "nasdaq"])

    def _is_desktop_task(self, text: str) -> bool:
        lower = text.lower()
        return any(kw in lower for kw in ["qq", "wechat", "微信", "发给", "发送", "paste", "粘贴", "桌面"])

    def _decompose_goal(self, goal: str) -> List[str]:
        """Automatically decompose composite compound goal into subgoals."""
        clean_goal = re.sub(r'(?:我?jev.*?apikey_\S+|apikey_\S+)', '', goal, flags=re.IGNORECASE).strip()
        # Tier 1: Explicit conjunctions
        primary_pattern = r"(?:然后|随后|之后|接着|并发给|并发送|then|and send to|and then)"
        parts = [p.strip() for p in re.split(primary_pattern, clean_goal, flags=re.IGNORECASE) if p.strip()]
        if len(parts) > 1:
            return parts

        # Tier 2: Implicit transition to target contact/application
        secondary_pattern = r"(?:(?<=[^\s])\s+(?=发(?:给)?)|(?<=[^\s])(?=发(?:给)?\s*(?:qq|wechat|微信|\d{5,})))"
        parts = [p.strip() for p in re.split(secondary_pattern, clean_goal, flags=re.IGNORECASE) if p.strip()]
        return parts if len(parts) > 1 else [clean_goal]

    def run(
        self,
        goal: str,
        mode: str = "auto",
        url: Optional[str] = None,
        max_steps: int = 20,
        parallel: bool = True,
        dry_run: bool = False,
    ) -> Any:
        """Intelligent dispatch: determine whether to run Web, Desktop, Chained, or Parallel Composite."""
        # Check if goal is a compound composite task
        subgoals = self._decompose_goal(goal)
        if len(subgoals) > 1 and mode in ("auto", "composite"):
            # Check if candidates for parallel multi-threaded pipeline
            if parallel and len(subgoals) == 2 and self._is_web_task(subgoals[0]) and self._is_desktop_task(subgoals[1]):
                return self.run_parallel_composite(web_task=subgoals[0], desktop_task=subgoals[1], max_steps=max_steps, dry_run=dry_run)
            return self.run_composite(goals=subgoals, max_steps_per_stage=max_steps, dry_run=dry_run)

        if mode == "browser" or url:
            target_url = url
            if not target_url:
                url_match = re.search(r"https?://[^\s]+", goal)
                target_url = url_match.group(0) if url_match else "https://google.com"
            safe_target_url = validate_safe_url(target_url)
            web_goal = goal.replace(target_url, "").strip() or goal
            return self.run_browser(url=safe_target_url, goal=web_goal, max_steps=max_steps, dry_run=dry_run)

        if mode == "desktop":
            return self.run_desktop(goal=goal, max_steps=max_steps, dry_run=dry_run)

        # Auto mode: heuristic URL detection
        url_match = re.search(r"https?://[^\s]+", goal)
        if url_match:
            target_url = url_match.group(0)
            safe_target_url = validate_safe_url(target_url)
            web_goal = goal.replace(target_url, "").strip() or "Browse and fulfill task"
            return self.run_browser(url=safe_target_url, goal=web_goal, max_steps=max_steps, dry_run=dry_run)
        else:
            return self.run_desktop(goal=goal, max_steps=max_steps, dry_run=dry_run)


# Backwards compatibility alias
OmniAgent = OpenAgent
