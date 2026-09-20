# OmniUse 🌐💻

> **The Dual-Core Autonomous Agent Bridging Browser & Desktop Worlds.**  
> Powered by **CDP**, **Set-of-Marks (SoM)**, and **TypeSafe Jev System One** sub-50ms probabilistic decision engine.

---

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey.svg)]()

---

## 🌟 Why OmniUse?

Traditional autonomous agents suffer from two major flaws:
1. **The Sandbox Trap**: Web agents cannot touch local native apps (like WeChat, QQ, Office, Finder). Desktop agents struggle with deep dynamic web forms and nested iframes.
2. **The "Token Burner" Problem**: Uploading full 4K screenshots to cloud Vision LLMs on every single step creates 5-15 second latencies and burns thousands of tokens per minute.

**OmniUse solves both**:
- **Dual-Core Architecture**: Seamlessly coordinates between a **Browser Engine** (direct CDP DOM interaction) and a **Desktop Engine** (Hardware Abstraction Layer for OS interactions).
- **Sub-50ms Decisions**: Uses local high-speed perception (Apple Vision on macOS / RapidOCR on Windows) to extract structured buttons `[1]`, `[2]`, `[3]`. **TypeSafe Jev System One** selects the action in **sub-50ms**, dropping cloud token costs by **98%**.

---

## 🏗 Architecture & Cross-Platform Support

```
                         OmniAgent (Unified Orchestrator)
                                      │
              ┌───────────────────────┴───────────────────────┐
              ▼                                               ▼
       Browser Engine                                  Desktop Engine
    (CDP + DOM Numbering)                     (Hardware Abstraction Layer - HAL)
              │                                               │
              ▼                                   ┌───────────┴───────────┐
     Google Chrome / Edge                         ▼                       ▼
   (Forms, Scraping, Downloads)             macOS Platform         Windows Platform
                                          (Apple Vision Accurate)   (RapidOCR ONNX)
                                          (Swift CGEvent Events)   (Win32 SendInput)
```

| Feature | macOS Engine | Windows Engine |
| :--- | :--- | :--- |
| **Text Perception (OCR)** | Apple Vision Accurate (Apple Neural Engine) | RapidOCR (ONNXRuntime / DirectML) |
| **UI Container Detection**| Apple Vision Rectangles | Numpy Vectorized Heuristics |
| **Native Input** | Swift CGEvent Hardware Driver | Win32 `user32.SendInput` ctypes |
| **Clipboard File Mount**  | NSPasteboard | Win32 `CF_HDROP` Structure |
| **Web Automation** | Google Chrome via CDP | Chrome / Microsoft Edge via CDP |

---

## 🚀 Quick Start

### 1. Installation

```bash
git clone https://github.com/your-username/omni-use.git
cd omni-use

# Install core dependencies
pip install -r requirements.txt

# On Windows: ensure rapidocr is installed
# pip install rapidocr-onnxruntime
```

### 2. Configuration

Create a `.env` file or export your TypeSafe Jev API key:

```bash
export JEV_API_KEY="your-typesafe-jev-key"
```

---

## 🕹 Usage

### CLI Execution

```bash
# 1. Desktop mode (automatic platform detection: macOS or Windows)
python run.py --mode desktop --goal "在 QQ 中把文件发送给客户"

# 2. Browser mode
python run.py --mode browser --url "https://example.com" --goal "Export yearly financial report"

# 3. Autonomous Smart Dispatch
python run.py --goal "https://en.wikipedia.org/wiki/Main_Page Find Gödel's incompleteness theorem"
```

### Python API Integration

```python
from omni_use import OmniAgent

agent = OmniAgent()

# Cross-application chained task:
# 1. Scrape data from web
web_res = agent.run_browser(
    url="https://portal.example.com",
    goal="Download latest monthly audit spreadsheet to /tmp/audit.xlsx"
)

# 2. Distribute to native desktop chat application
agent.run_desktop(
    goal="Open QQ, search contact 'Finance Team', paste /tmp/audit.xlsx and send"
)
```

---

## 🔌 Model Context Protocol (MCP) Server

OmniUse can be launched directly as a standard **MCP Server** over stdio. This equips any MCP-compatible AI (Claude Desktop, Cursor, Windsurf, Zed, Antigravity) with native desktop and deep browser capabilities!

### 1. Launch via CLI
```bash
python run.py --mcp
```

### 2. Claude Desktop Integration
Add the following to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "omni-use": {
      "command": "python3",
      "args": ["/absolute/path/to/omni-use/run.py", "--mcp"],
      "env": {
        "JEV_API_KEY": "your-typesafe-jev-key"
      }
    }
  }
}
```

### 3. Cursor Integration
Add to your project's `.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "omni-use": {
      "command": "python3",
      "args": ["run.py", "--mcp"]
    }
  }
}
```

### Exposed MCP Tools:
- `omni_run(goal)`: Dual-core autonomous execution across web and desktop.
- `desktop_run_goal(goal, max_steps)`: Native desktop automation (QQ, WeChat, Office, Finder).
- `browser_run_goal(url, goal)`: Fast CDP web automation without token waste.
- `desktop_get_buttons()`: Inspect screen and return numbered UI buttons `[1], [2], [3]`.
- `desktop_click_button(button_id)`: Hardware-level click by button ID.
- `desktop_type_text(text)`: Native Unicode text typing.
- `desktop_copy_file_to_clipboard(file_path)`: Mount file to OS clipboard for instant pasting.


---

## ⚖️ License & Open Source Compliance

This project is licensed under the **Apache License 2.0** - see the [LICENSE](LICENSE) file for details.

### 🙏 Credits & Acknowledgments
We express deep appreciation to the following pioneering open-source projects and services that inspired and empowered this architecture:
- [browser-use](https://github.com/browser-use/browser-use) - Groundbreaking browser automation concepts and CDP design patterns.
- [RapidOCR](https://github.com/RapidAI/RapidOCR) - High-performance, offline ONNX OCR engine powering our Windows perception layer.
- [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) - Robust deep learning text recognition models.
- [TypeSafe AI](https://typesafe.ai) - The `jev-latest` System One decision and audit engine.
