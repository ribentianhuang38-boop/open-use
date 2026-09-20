# Contributing to OmniUse

Thank you for your interest in contributing to OmniUse! We welcome pull requests, feature suggestions, bug reports, and optimizations for cross-platform automation.

## Development Setup

1. **Fork and clone the repository**:
   ```bash
   git clone https://github.com/ribentianhuang38-boop/omni-use.git
   cd omni-use
   ```

2. **Create a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install dependencies in editable mode**:
   ```bash
   pip install -e .
   # On Windows:
   pip install -e ".[windows]"
   ```

4. **Run syntax verification**:
   ```bash
   python -m py_compile run.py
   python -m py_compile omni_use/**/*.py
   ```

## Architecture Guidelines

- **Zero-Vision Verification on Web**: Always prefer pure DOM and CDP evaluation over capturing screenshots.
- **Cross-Platform HAL**: Keep hardware specifics isolated in `omni_use/desktop/platform_mac.py` and `omni_use/desktop/platform_win.py`. The core orchestrator `OmniAgent` should remain platform-agnostic.
- **MCP Protocol**: Any new general-purpose capability should be exposed as an MCP tool in `omni_use/mcp_server.py`.

## Submitting Pull Requests

1. Create a feature branch: `git checkout -b feat/your-feature-name`.
2. Commit your changes with concise, conventional commit messages.
3. Push to your fork and submit a PR with a clear description of the problem solved.
