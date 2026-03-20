"""DuckDuckGo web search via the HTML endpoint.

No API key required. Returns a formatted list of results with title,
URL, and snippet. Respects a hard result cap to keep token cost low.
"""
from __future__ import annotations

import re
from typing import List, Tuple

import httpx

from src.utils.logger import logger

_DDG_URL = "https://html.duckduckgo.com/html/"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
_RE_RESULT = re.compile(
    r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_RE_SNIPPET = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL,
)
_RE_TAGS = re.compile(r"<[^>]+>")
_RE_ENTITIES = [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")]


def _strip(html: str) -> str:
    text = _RE_TAGS.sub(" ", html)
    for esc, ch in _RE_ENTITIES:
        text = text.replace(esc, ch)
    return " ".join(text.split())


def _extract_results(html: str, limit: int) -> List[Tuple[str, str, str]]:
    """Return list of (title, url, snippet) tuples."""
    titles_urls = _RE_RESULT.findall(html)
    snippets = [_strip(s) for s in _RE_SNIPPET.findall(html)]
    results = []
    for i, (url, raw_title) in enumerate(titles_urls):
        if i >= limit:
            break
        title = _strip(raw_title)
        snippet = snippets[i] if i < len(snippets) else ""
        if url.startswith("//"):
            url = "https:" + url
        results.append((title, url, snippet))
    return results


async def web_search(query: str, max_results: int = 5) -> str:
    """Search DuckDuckGo and return formatted results as plain text."""
    if not query or not query.strip():
        return "Error: empty query."

    try:
        async with httpx.AsyncClient(
            timeout=15.0,
            headers=_HEADERS,
            follow_redirects=True,
        ) as client:
            r = await client.post(_DDG_URL, data={"q": query})
            r.raise_for_status()
            html = r.text
    except httpx.HTTPStatusError as exc:
        logger.error("ddg_http_error", status=exc.response.status_code, query=query)
        return f"Web search error: HTTP {exc.response.status_code}"
    except Exception as exc:
        logger.error("ddg_request_failed", query=query, error=str(exc))
        return f"Web search error: {exc}"

    results = _extract_results(html, max_results)
    if not results:
        return f"No results found for: {query}"

    lines = [f"Web search results for: {query}\n"]
    for i, (title, url, snippet) in enumerate(results, 1):
        lines.append(f"{i}. {title}")
        lines.append(f"   URL: {url}")
        if snippet:
            lines.append(f"   {snippet}")
        lines.append("")
    return "\n".join(lines).strip()
