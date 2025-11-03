#!/usr/bin/env python3
"""Test script to upload CV to storage service."""

import sys
from pathlib import Path

import httpx

def main():
    pdf_path = Path("/Users/akhil/Library/CloudStorage/OneDrive-Personal/2025/Career/Resume General/Akhil K Pandey.pdf")

    if not pdf_path.exists():
        print(f"Error: PDF not found at {pdf_path}")
        sys.exit(1)

    print(f"Uploading {pdf_path.name} ({pdf_path.stat().st_size} bytes)...")

    url = "http://localhost:8000/ingest-cv"

    with open(pdf_path, "rb") as f:
        files = {"file": (pdf_path.name, f, "application/pdf")}

        try:
            response = httpx.post(url, files=files, timeout=90.0)
            response.raise_for_status()

            print(f"\nSuccess! Status: {response.status_code}")
            print(f"Response:\n{response.text}")

        except httpx.TimeoutException as e:
            print(f"\nError: Request timed out after 90 seconds")
            print(f"Details: {e}")
            sys.exit(1)
        except httpx.HTTPStatusError as e:
            print(f"\nError: HTTP {e.response.status_code}")
            print(f"Response: {e.response.text}")
            sys.exit(1)
        except Exception as e:
            print(f"\nError: {type(e).__name__}: {e}")
            sys.exit(1)

if __name__ == "__main__":
    main()
