"""Simple CLI smoke test for the configured LLM provider."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_repo_on_path() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    lib_path = repo_root / "libs" / "llm_driver" / "src"
    if str(lib_path) not in sys.path:
        sys.path.insert(0, str(lib_path))


_ensure_repo_on_path()

from llm_driver import load_driver_from_env  # noqa: E402


def main() -> None:
    provider = os.getenv("LLM_PROVIDER", "<unset>")
    model = os.getenv("LLM_MODEL", "<unset>")
    driver = load_driver_from_env()
    prompt = "Say hello from the Jobsearch Auto smoke test."
    result = driver.complete(prompt)
    print(f"provider={provider} model={model}")
    print(result[:200])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # pragma: no cover - CLI ergonomics
        print(f"Smoke test failed: {exc}", file=sys.stderr)
        sys.exit(1)
