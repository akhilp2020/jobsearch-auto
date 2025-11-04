from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import DefaultDict
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple rate limiter with per-domain tracking."""

    def __init__(self, requests_per_second: float = 1.0) -> None:
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.last_request: DefaultDict[str, float] = defaultdict(float)

    async def acquire(self, domain: str) -> None:
        """Wait if necessary to respect rate limit for domain."""
        now = time.time()
        last = self.last_request[domain]
        elapsed = now - last

        if elapsed < self.min_interval:
            wait_time = self.min_interval - elapsed
            await asyncio.sleep(wait_time)

        self.last_request[domain] = time.time()


class RobotsChecker:
    """Check robots.txt compliance."""

    def __init__(self) -> None:
        self.parsers: dict[str, RobotFileParser] = {}
        self.user_agent = "JobSearchBot/1.0"

    async def can_fetch(self, url: str) -> bool:
        """Check if URL can be fetched according to robots.txt."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        if base_url not in self.parsers:
            await self._load_robots(base_url)

        parser = self.parsers.get(base_url)
        if parser is None:
            # No robots.txt or failed to load - allow
            return True

        return parser.can_fetch(self.user_agent, url)

    async def _load_robots(self, base_url: str) -> None:
        """Load robots.txt for a domain."""
        robots_url = f"{base_url}/robots.txt"
        parser = RobotFileParser()
        parser.set_url(robots_url)

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(robots_url)
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                    logger.info(f"Loaded robots.txt from {robots_url}")
                else:
                    logger.info(f"No robots.txt at {robots_url} (status {response.status_code})")
        except Exception as exc:
            logger.warning(f"Failed to load robots.txt from {robots_url}: {exc}")

        self.parsers[base_url] = parser
