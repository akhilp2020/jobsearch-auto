from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .models import JobPosting, SearchFilters

logger = logging.getLogger(__name__)


class JobAdapter(ABC):
    """Base class for job board adapters."""

    @abstractmethod
    async def search(self, filters: SearchFilters) -> list[JobPosting]:
        """Search for jobs matching the filters."""
        pass


class GreenhouseAdapter(JobAdapter):
    """Adapter for Greenhouse public job boards."""

    # Popular companies using Greenhouse
    GREENHOUSE_COMPANIES = [
        {"name": "Airbnb", "board_token": "airbnb"},
        {"name": "Slack", "board_token": "slack"},
        {"name": "Stripe", "board_token": "stripe"},
        {"name": "DoorDash", "board_token": "doordash"},
        {"name": "Coinbase", "board_token": "coinbase"},
    ]

    async def search(self, filters: SearchFilters) -> list[JobPosting]:
        """Search Greenhouse job boards."""
        all_jobs: list[JobPosting] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for company in self.GREENHOUSE_COMPANIES:
                try:
                    jobs = await self._fetch_company_jobs(client, company, filters)
                    all_jobs.extend(jobs)
                except Exception as exc:
                    logger.warning(f"Failed to fetch jobs from {company['name']}: {exc}")

        return all_jobs

    async def _fetch_company_jobs(
        self, client: httpx.AsyncClient, company: dict[str, str], filters: SearchFilters
    ) -> list[JobPosting]:
        """Fetch jobs from a single Greenhouse company board."""
        board_token = company["board_token"]
        url = f"https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs"

        response = await client.get(url)
        if response.status_code != 200:
            logger.warning(f"Greenhouse API returned {response.status_code} for {company['name']}")
            return []

        data = response.json()
        jobs = data.get("jobs", [])

        postings: list[JobPosting] = []
        for job in jobs:
            if not self._matches_filters(job, filters):
                continue

            posting = self._normalize_job(job, company["name"])
            if posting:
                postings.append(posting)

        return postings

    def _matches_filters(self, job: dict[str, Any], filters: SearchFilters) -> bool:
        """Check if job matches search filters."""
        title = job.get("title", "").lower()
        location = job.get("location", {}).get("name", "").lower()

        # Check title match
        if filters.titles:
            if not any(filter_title.lower() in title for filter_title in filters.titles):
                return False

        # Check location match
        if filters.locations:
            if not any(filter_loc.lower() in location for filter_loc in filters.locations):
                return False

        return True

    def _normalize_job(self, job: dict[str, Any], company_name: str) -> JobPosting | None:
        """Convert Greenhouse job to normalized JobPosting."""
        try:
            job_id = str(job.get("id", ""))
            title = job.get("title", "")
            location_obj = job.get("location", {})
            location = location_obj.get("name", "Unknown")

            # Extract job description
            content = job.get("content", "")
            if not content:
                content = job.get("description", "")

            apply_url = job.get("absolute_url", "")
            if not apply_url:
                return None

            return JobPosting(
                id=f"gh_{company_name.lower()}_{job_id}",
                title=title,
                company=company_name,
                location=location,
                jd_text=self._clean_html(content),
                requirements="",
                source="greenhouse",
                apply_url=apply_url,
                raw_data=job,
            )
        except Exception as exc:
            logger.warning(f"Failed to normalize Greenhouse job: {exc}")
            return None

    @staticmethod
    def _clean_html(html: str) -> str:
        """Remove HTML tags and clean up text."""
        if not html:
            return ""
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(separator="\n", strip=True)
        return text.strip()


class LeverAdapter(JobAdapter):
    """Adapter for Lever public job boards."""

    # Popular companies using Lever
    LEVER_COMPANIES = [
        {"name": "Netflix", "lever_id": "netflix"},
        {"name": "Shopify", "lever_id": "shopify"},
        {"name": "Figma", "lever_id": "figma"},
        {"name": "Notion", "lever_id": "notion"},
        {"name": "Canva", "lever_id": "canva"},
    ]

    async def search(self, filters: SearchFilters) -> list[JobPosting]:
        """Search Lever job boards."""
        all_jobs: list[JobPosting] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for company in self.LEVER_COMPANIES:
                try:
                    jobs = await self._fetch_company_jobs(client, company, filters)
                    all_jobs.extend(jobs)
                except Exception as exc:
                    logger.warning(f"Failed to fetch jobs from {company['name']}: {exc}")

        return all_jobs

    async def _fetch_company_jobs(
        self, client: httpx.AsyncClient, company: dict[str, str], filters: SearchFilters
    ) -> list[JobPosting]:
        """Fetch jobs from a single Lever company board."""
        lever_id = company["lever_id"]
        url = f"https://api.lever.co/v0/postings/{lever_id}"

        params = {"mode": "json", "skip": 0, "limit": 100}
        response = await client.get(url, params=params)

        if response.status_code != 200:
            logger.warning(f"Lever API returned {response.status_code} for {company['name']}")
            return []

        jobs = response.json()
        postings: list[JobPosting] = []

        for job in jobs:
            if not self._matches_filters(job, filters):
                continue

            posting = self._normalize_job(job, company["name"])
            if posting:
                postings.append(posting)

        return postings

    def _matches_filters(self, job: dict[str, Any], filters: SearchFilters) -> bool:
        """Check if job matches search filters."""
        title = job.get("text", "").lower()
        categories = job.get("categories", {})
        location = categories.get("location", "").lower()

        # Check title match
        if filters.titles:
            if not any(filter_title.lower() in title for filter_title in filters.titles):
                return False

        # Check location match
        if filters.locations:
            if not any(filter_loc.lower() in location for filter_loc in filters.locations):
                return False

        return True

    def _normalize_job(self, job: dict[str, Any], company_name: str) -> JobPosting | None:
        """Convert Lever job to normalized JobPosting."""
        try:
            job_id = job.get("id", "")
            title = job.get("text", "")
            categories = job.get("categories", {})
            location = categories.get("location", "Unknown")

            # Extract job description
            description_obj = job.get("description", "")
            lists = job.get("lists", [])

            # Combine description and lists
            jd_parts = [description_obj]
            for lst in lists:
                content = lst.get("content", "")
                jd_parts.append(content)

            jd_html = "\n".join(jd_parts)

            apply_url = job.get("hostedUrl", "")
            if not apply_url:
                apply_url = job.get("applyUrl", "")
            if not apply_url:
                return None

            return JobPosting(
                id=f"lever_{company_name.lower()}_{job_id}",
                title=title,
                company=company_name,
                location=location,
                jd_text=GreenhouseAdapter._clean_html(jd_html),
                requirements="",
                source="lever",
                apply_url=apply_url,
                raw_data=job,
            )
        except Exception as exc:
            logger.warning(f"Failed to normalize Lever job: {exc}")
            return None


class WorkdayAdapter(JobAdapter):
    """Adapter for Workday public job boards."""

    # Some companies with public Workday job boards
    WORKDAY_COMPANIES = [
        {"name": "Amazon", "tenant": "amazon"},
        {"name": "Target", "tenant": "target"},
    ]

    async def search(self, filters: SearchFilters) -> list[JobPosting]:
        """Search Workday job boards.

        Note: Workday's API is complex and varies by company.
        This is a basic implementation that may need customization.
        """
        # Workday doesn't have a standardized public API
        # Most companies require web scraping or have custom integrations
        # For now, return empty list
        logger.info("Workday adapter: Public API access is limited, returning no results")
        return []


class GenericHTMLAdapter(JobAdapter):
    """Generic HTML scraper using BeautifulSoup."""

    def __init__(self, target_urls: list[str] | None = None) -> None:
        self.target_urls = target_urls or []

    async def search(self, filters: SearchFilters) -> list[JobPosting]:
        """Scrape jobs from generic HTML pages.

        This is a basic implementation. Real-world usage would require
        site-specific selectors and potentially Playwright for JavaScript-heavy sites.
        """
        all_jobs: list[JobPosting] = []

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            for url in self.target_urls:
                try:
                    jobs = await self._scrape_url(client, url, filters)
                    all_jobs.extend(jobs)
                except Exception as exc:
                    logger.warning(f"Failed to scrape {url}: {exc}")

        return all_jobs

    async def _scrape_url(
        self, client: httpx.AsyncClient, url: str, filters: SearchFilters
    ) -> list[JobPosting]:
        """Scrape jobs from a single URL."""
        response = await client.get(url)
        if response.status_code != 200:
            logger.warning(f"Failed to fetch {url}: {response.status_code}")
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        # This is a generic implementation
        # In practice, you'd need site-specific selectors
        job_elements = soup.find_all("div", class_=["job", "job-posting", "position"])

        postings: list[JobPosting] = []
        for idx, elem in enumerate(job_elements[:20]):  # Limit to 20 per page
            posting = self._extract_job_from_element(elem, url, idx)
            if posting:
                postings.append(posting)

        return postings

    def _extract_job_from_element(
        self, element: Any, base_url: str, index: int
    ) -> JobPosting | None:
        """Extract job information from HTML element."""
        try:
            # Generic extraction - would need customization per site
            title_elem = element.find(["h2", "h3", "h4"])
            title = title_elem.get_text(strip=True) if title_elem else "Unknown Title"

            # Try to find link
            link_elem = element.find("a", href=True)
            apply_url = ""
            if link_elem:
                href = link_elem["href"]
                apply_url = urljoin(base_url, href)

            # Extract company from URL or element
            parsed = urlparse(base_url)
            company = parsed.netloc.replace("www.", "").split(".")[0].title()

            # Extract location
            location_elem = element.find(class_=re.compile(r"location", re.I))
            location = location_elem.get_text(strip=True) if location_elem else "Unknown"

            # Get description
            jd_text = element.get_text(separator="\n", strip=True)

            if not apply_url or not jd_text:
                return None

            return JobPosting(
                id=f"generic_{company.lower()}_{index}",
                title=title,
                company=company,
                location=location,
                jd_text=jd_text,
                requirements="",
                source="generic_html",
                apply_url=apply_url,
                raw_data={"html_snippet": str(element)[:500]},
            )
        except Exception as exc:
            logger.warning(f"Failed to extract job from element: {exc}")
            return None
