#!/usr/bin/env python3
from __future__ import annotations

import runpy
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    backend_root = repo_root / "hub" / "backend"
    sys.path.insert(0, str(backend_root))
    runpy.run_module("app.cli.review_pending_submissions", run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
