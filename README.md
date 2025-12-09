# SyncAgent

[![CI](https://github.com/dubrzr/syncagent/actions/workflows/ci.yml/badge.svg)](https://github.com/dubrzr/syncagent/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/dubrzr/syncagent/branch/main/graph/badge.svg)](https://codecov.io/gh/dubrzr/syncagent)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Zero-Knowledge End-to-End Encrypted (E2EE) file synchronization system.

## Installation

```bash
# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# Install with all dependencies
pip install -e ".[all]"
```

## Usage

```bash
syncagent init
syncagent unlock
```

## License

MIT
