from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx


@dataclass(frozen=True)
class PublicTrendEvidence:
    source: str
    item_id: str
    title: str
    url: str
    summary: str


class _ResultParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._capture = ""
        self._current: dict[str, str] | None = None

    def handle_starttag(self, tag: str, attrs):
        attributes = dict(attrs)
        classes = set(attributes.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            self._current = {"url": attributes.get("href", ""), "title": "", "summary": ""}
            self.results.append(self._current)
            self._capture = "title"
        elif self._current is not None and "result__snippet" in classes:
            self._capture = "summary"

    def handle_endtag(self, tag: str):
        if tag in {"a", "div", "span"}:
            self._capture = ""

    def handle_data(self, data: str):
        if self._current is not None and self._capture:
            self._current[self._capture] += data


class PublicTrendWebClient:
    """Metadata-only public search. It never downloads result media."""

    def __init__(
        self,
        *,
        enabled: bool,
        endpoint: str = "https://html.duckduckgo.com/html/",
        timeout_seconds: float = 20.0,
        transport: httpx.BaseTransport | None = None,
    ):
        self.enabled = enabled
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.transport = transport

    def status(self) -> dict[str, str]:
        return {
            "status": "configured" if self.enabled else "disabled",
            "provider": "public_web_metadata",
        }

    @staticmethod
    def _unwrap_url(raw: str) -> str:
        parsed = urlparse(unescape(raw))
        if "duckduckgo.com" in (parsed.hostname or ""):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            return unquote(target)
        return unescape(raw)

    @staticmethod
    def _source(url: str) -> str:
        host = (urlparse(url).hostname or "").lower()
        if host == "douyin.com" or host.endswith(".douyin.com"):
            return "douyin_public_web"
        if host == "xiaohongshu.com" or host.endswith(".xiaohongshu.com") or host.endswith(".xhslink.com"):
            return "xiaohongshu_public_web"
        return ""

    def search(self, keyword: str, *, count: int = 6) -> list[PublicTrendEvidence]:
        if not self.enabled:
            return []
        with httpx.Client(transport=self.transport, timeout=self.timeout_seconds, follow_redirects=True) as client:
            response = client.get(
                self.endpoint,
                params={"q": f'{keyword.strip()} (site:douyin.com/video OR site:xiaohongshu.com/explore)'},
                headers={"User-Agent": "Mozilla/5.0 VideoWorkbench/1.0"},
            )
            response.raise_for_status()
        parser = _ResultParser()
        parser.feed(response.text)
        results: list[PublicTrendEvidence] = []
        for item in parser.results:
            url = self._unwrap_url(item["url"])
            source = self._source(url)
            if not source:
                continue
            item_id = urlparse(url).path.strip("/").replace("/", "-") or str(abs(hash(url)))
            results.append(
                PublicTrendEvidence(
                    source=source,
                    item_id=item_id,
                    title=unescape(item["title"]).strip() or keyword,
                    url=url,
                    summary=unescape(item["summary"]).strip(),
                )
            )
            if len(results) >= max(1, count):
                break
        return results
