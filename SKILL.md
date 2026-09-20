---
name: open-use
description: High-performance dual-core autonomous agent engine bridging browser (CDP) and native desktop automation (macOS/Windows) with sub-50ms TypeSafe Jev decisions and MCP stdio support.
---

# OpenUse Skill

OpenUse allows agents to autonomously interact with both web browsers and native operating system desktops with ultra-fast TypeSafe decisions and reliable visual grounding.

## Modes of Integration

### 1. Model Context Protocol (MCP) Server
Run OpenUse directly as an MCP stdio server for Claude Desktop, Cursor, Zed, Windsurf, or VS Code:

```bash
openuse --mcp
# or
python3 -m open_use --mcp
```

### 2. Autonomous Task Execution (CLI)
Delegate end-to-end tasks to OpenUse via the command line:

```bash
# Auto mode (routes to browser or desktop)
openuse --goal "Search for the latest Rust release notes and summarize them"

# Pure browser mode
openuse --mode browser --url "https://news.ycombinator.com" --goal "Extract the top 3 trending stories"

# Pure desktop mode
openuse --mode desktop --goal "Open Slack and send 'Build complete' to the #dev channel"
```

### 3. Python SDK Direct Invocation
Use OpenUse directly inside Python scripts or Agent tool definitions:

```python
from open_use import OpenAgent

agent = OpenAgent()
result = agent.run(
    goal="Open Finder, locate the downloads folder, and organize PDF files",
    mode="desktop",
)
print("Execution success:", result.success)
```

## Available MCP Tools

When launched with `--mcp`, OpenUse exposes the following 7 standard tools:

| Tool Name | Parameters | Purpose |
| :--- | :--- | :--- |
| `open_run` | `goal: str` | Smart dual-core dispatch across browser and desktop environments |
| `desktop_run_goal` | `goal: str, max_steps?: int` | Native desktop automation via local neural perception |
| `desktop_get_buttons` | None | Inspect display and return indexed interactive coordinates |
| `desktop_click_button`| `button_id: str` | Hardware-level input injection by indexed button target |
| `desktop_type_text` | `text: str` | Native Unicode keyboard stream injection |
| `desktop_hotkey` | `keys: list[str]` | Native hardware-level hotkey shortcut execution |
| `browser_run_goal` | `url: str, goal: str` | Zero-vision CDP browser execution with interactive DOM |

## Platform Support & Fallbacks

- **macOS**: Native Apple Vision OCR + AppleScript/CGEvent. Zero compilation required with precompiled bundled binaries. Fallback to `swiftc` or pure Python OCR automatically.
- **Windows**: 100% pure Python + Win32 `ctypes` (`SendInput`, `CF_HDROP`). Zero C++ / MSVC compiler required.
