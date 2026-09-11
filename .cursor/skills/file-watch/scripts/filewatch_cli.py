#!/usr/bin/env python3
"""filewatch CLI 入口。与 scripts/filewatch 包同目录，随 skill 分发。"""

from __future__ import annotations

from filewatch.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
