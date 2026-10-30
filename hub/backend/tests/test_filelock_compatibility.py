"""Exercise downstream lock consumers before overriding LiteLLM's filelock cap."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from filelock import FileLock
from huggingface_hub.utils import WeakFileLock

LOCK_PROBE = """
import sys
from filelock import FileLock, Timeout

try:
    with FileLock(sys.argv[1], timeout=0.1):
        print("acquired")
except Timeout:
    print("blocked")
"""


@pytest.mark.parametrize("consumer", ["litellm", "huggingface"])
def test_downstream_lock_excludes_other_processes_and_releases(
    consumer: str, tmp_path: Path
) -> None:
    lock_path = tmp_path / "locks" / "cache.lock"
    lock_path.parent.mkdir()
    if consumer == "litellm":
        # The FileLock API used by LiteLLM; its proxy CLI needs unrelated extras.
        lock = FileLock(str(lock_path), timeout=10, mode=0o600)
    else:
        lock = WeakFileLock(lock_path, timeout=1)

    def probe() -> str:
        result = subprocess.run(
            [sys.executable, "-c", LOCK_PROBE, str(lock_path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.stdout.strip()

    with lock:
        assert probe() == "blocked"

    assert probe() == "acquired"
