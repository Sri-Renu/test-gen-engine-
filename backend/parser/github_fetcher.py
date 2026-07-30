"""
GitHub Fetcher — fetch raw Python source from a GitHub URL.

Supports:
  - https://github.com/user/repo/blob/main/path/to/file.py
  - https://raw.githubusercontent.com/user/repo/main/path/to/file.py
  - Direct raw URLs

Converts blob URLs to raw.githubusercontent.com automatically.
This was in the original spec (POST /analyze with GitHub URL) and is
what separates this from a toy paste-box tool.
"""

from __future__ import annotations
import re
import httpx
from dataclasses import dataclass


@dataclass
class FetchResult:
    success: bool
    source_code: str
    url: str
    error: str = ""
    file_path: str = ""     # the path within the repo


class GitHubFetcher:
    """
    Fetch Python source from GitHub.

    Usage:
        fetcher = GitHubFetcher()
        result = fetcher.fetch("https://github.com/user/repo/blob/main/foo.py")
        if result.success:
            print(result.source_code)
    """

    TIMEOUT = 10  # seconds

    def fetch(self, url: str) -> FetchResult:
        raw_url, file_path = self._to_raw_url(url)
        if not raw_url:
            return FetchResult(
                success=False,
                source_code="",
                url=url,
                error=f"Could not parse GitHub URL: {url}. "
                      f"Expected format: github.com/user/repo/blob/branch/path/to/file.py",
            )

        try:
            resp = httpx.get(raw_url, timeout=self.TIMEOUT, follow_redirects=True)
            if resp.status_code == 404:
                return FetchResult(success=False, source_code="", url=raw_url,
                                   error=f"File not found (404): {raw_url}")
            if resp.status_code != 200:
                return FetchResult(success=False, source_code="", url=raw_url,
                                   error=f"HTTP {resp.status_code} fetching {raw_url}")
            if not raw_url.endswith(".py") and not self._looks_like_python(resp.text):
                return FetchResult(success=False, source_code="", url=raw_url,
                                   error="URL does not point to a Python file.")

            return FetchResult(
                success=True,
                source_code=resp.text,
                url=raw_url,
                file_path=file_path,
            )

        except httpx.TimeoutException:
            return FetchResult(success=False, source_code="", url=raw_url,
                               error=f"Request timed out after {self.TIMEOUT}s.")
        except Exception as e:
            return FetchResult(success=False, source_code="", url=raw_url,
                               error=str(e))

    def _to_raw_url(self, url: str) -> tuple[str, str]:
        """Convert any GitHub URL form to raw.githubusercontent.com."""
        url = url.strip()

        # Already raw
        if "raw.githubusercontent.com" in url:
            path = re.sub(r"https://raw\.githubusercontent\.com/[^/]+/[^/]+/[^/]+/", "", url)
            return url, path

        # github.com/user/repo/blob/branch/path
        match = re.match(
            r"https?://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url
        )
        if match:
            user, repo, branch, path = match.groups()
            raw = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}"
            return raw, path

        # github.com/user/repo/raw/branch/path  (legacy)
        match = re.match(
            r"https?://github\.com/([^/]+)/([^/]+)/raw/([^/]+)/(.+)", url
        )
        if match:
            user, repo, branch, path = match.groups()
            raw = f"https://raw.githubusercontent.com/{user}/{repo}/{branch}/{path}"
            return raw, path

        return "", ""

    def _looks_like_python(self, text: str) -> bool:
        python_signals = ["def ", "import ", "class ", "if __name__"]
        return any(s in text for s in python_signals)

    @staticmethod
    def is_github_url(text: str) -> bool:
        """Quick check — is this string a GitHub URL?"""
        return "github.com" in text or "raw.githubusercontent.com" in text