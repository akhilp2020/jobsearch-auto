#!/usr/bin/env python3
"""Test OpenAI API connectivity."""

import os
import sys

from llm_driver.driver import OpenAICompletionDriver


def main() -> None:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("Set OPENAI_API_KEY before running this script.")
        sys.exit(1)

    model = os.environ.get("OPENAI_MODEL", "gpt-3.5-turbo")

    print(f"Testing OpenAI API with model: {model}")
    print("API key loaded from environment.")

    driver = OpenAICompletionDriver(model=model, api_key=api_key)

    try:
        result = driver.complete("Say 'Hello, World!' and nothing else.")
        print(f"\nSuccess! Response: {result}")
    except Exception as exc:
        print(f"\nError: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
