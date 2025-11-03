#!/usr/bin/env python3
"""Test CV ingestion by directly calling the service endpoint with a small test file."""

import asyncio
import sys
from pathlib import Path

# Add necessary paths
sys.path.insert(0, "libs/llm_driver/src")
sys.path.insert(0, "libs/mcp_clients/src")
sys.path.insert(0, "services/storage_svc/src")

import httpx


async def main():
    # Create a minimal test PDF-like content
    test_content = b"""John Doe
Software Engineer
john.doe@example.com | 555-1234

EXPERIENCE
Senior Software Engineer - Tech Corp (2020-2023)
- Led team of 5 engineers
- Improved performance by 50%

Software Engineer - StartupCo (2018-2020)
- Built microservices architecture
- Deployed to AWS

SKILLS
Python, JavaScript, AWS, Docker, Kubernetes

EDUCATION
BS Computer Science - University of Tech (2014-2018)
"""

    print("Testing direct CV ingestion with test content...")

    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            files = {"file": ("test_resume.txt", test_content, "text/plain")}
            response = await client.post(
                "http://localhost:8000/ingest-cv",
                files=files
            )
            response.raise_for_status()
            result = response.json()

            print("\n✓ Success!")
            print(f"Profile saved to: {result['path']}")
            print(f"\nExtracted profile:")
            import json
            print(json.dumps(result['profile'], indent=2))

        except httpx.TimeoutException:
            print("✗ Request timed out")
            sys.exit(1)
        except Exception as e:
            print(f"✗ Error: {type(e).__name__}: {e}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
