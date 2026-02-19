"""Fetch and parse HTML lecture notes from URLs into sections."""

from __future__ import annotations

import base64
import hashlib
import os.path
import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

_MAX_HTML_BYTES = 2 * 1024 * 1024  # 2 MB
_MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB per image
_MAX_SECTIONS = 200
_HEADING_TAGS = {"h1", "h2", "h3"}
_FETCH_TIMEOUT = 30
_IMAGE_FETCH_TIMEOUT = 15

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class URLFetchError(RuntimeError):
    """Raised when a URL cannot be fetched."""


class URLValidationError(ValueError):
    """Raised when fetched content is invalid."""


@dataclass
class ParsedSection:
    index: int
    heading_level: int
    heading_text: str
    html_content: str
    text_content: str


@dataclass
class ImageInfo:
    url: str
    alt: str
    section_index: int


def fetch_url_content(url: str, timeout: int = _FETCH_TIMEOUT) -> str:
    """Fetch HTML from *url*. Returns the HTML string."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise URLValidationError(f"URL scheme must be http or https, got '{parsed.scheme}'")
    if not parsed.netloc:
        raise URLValidationError("Invalid URL: missing hostname")

    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.TimeoutException:
        raise URLFetchError(f"Timed out fetching URL (>{timeout}s)")
    except httpx.HTTPStatusError as exc:
        raise URLFetchError(f"HTTP {exc.response.status_code} fetching URL")
    except httpx.HTTPError as exc:
        raise URLFetchError(f"Failed to fetch URL: {exc}")

    content_type = resp.headers.get("content-type", "")
    if "html" not in content_type and "text" not in content_type:
        raise URLValidationError(f"Expected HTML content, got content-type: {content_type}")

    if len(resp.content) > _MAX_HTML_BYTES:
        raise URLValidationError(f"Page too large ({len(resp.content)} bytes, max {_MAX_HTML_BYTES})")

    return resp.text


def parse_sections(html: str, source_url: str) -> list[ParsedSection]:
    """Parse *html* into heading-delimited sections.

    Headings may be nested inside container ``<div>`` elements; the parser
    finds *all* heading tags in document order and splits content between
    consecutive headings into sections.

    Relative URLs in ``<img src>`` and ``<a href>`` are resolved against
    *source_url*.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Resolve relative URLs.
    _resolve_relative_urls(soup, source_url)

    # Find the main content container.
    body = soup.find("main") or soup.find("article") or soup.find("body")
    if body is None:
        raise URLValidationError("Could not find content in the HTML page")

    # Locate all heading tags anywhere in the document body.
    headings = body.find_all(_HEADING_TAGS)

    if not headings:
        # No headings at all – treat the entire body as a single section.
        full_text = body.get_text(separator=" ", strip=True)
        if full_text:
            return [
                ParsedSection(
                    index=0,
                    heading_level=1,
                    heading_text=_extract_page_title(soup),
                    html_content=str(body),
                    text_content=full_text,
                )
            ]
        return []

    sections: list[ParsedSection] = []

    # Build a set of heading elements for O(1) lookup.
    heading_set = set(id(h) for h in headings)

    # Collect content between consecutive headings by walking the DOM
    # with ``next_element`` (which crosses nesting boundaries, unlike
    # ``next_sibling``).
    for i, heading in enumerate(headings):
        heading_text = heading.get_text(strip=True)
        heading_level = int(heading.name[1])
        next_heading = headings[i + 1] if i + 1 < len(headings) else None

        # Walk all DOM nodes after this heading until we reach the next
        # heading (or the end of the document).  We collect only
        # *top-level* elements -- tags that are not children of another
        # already-collected tag.
        collected_html_parts: list[str] = [str(heading)]
        collected_text_parts: list[str] = [heading.get_text(separator=" ", strip=True)]

        node = heading
        # Track which nodes we have already "consumed" via a parent so
        # we don't double-count them.
        skip_descendants_of: Tag | None = None

        while True:
            node = node.next_element
            if node is None:
                break
            # Reached the next heading – stop.
            if isinstance(node, Tag) and id(node) in heading_set and node is not heading:
                break
            # If we are inside a tag we already serialised, skip.
            if skip_descendants_of is not None:
                if _is_descendant_of(node, skip_descendants_of):
                    continue
                skip_descendants_of = None
            # Collect top-level tags that are siblings (or cousin-level)
            # of the heading.
            if isinstance(node, Tag):
                # Skip tags that are ancestors of future headings --
                # they are structural wrappers, not content.
                if next_heading and _is_descendant_of(next_heading, node):
                    continue
                collected_html_parts.append(str(node))
                collected_text_parts.append(node.get_text(separator=" ", strip=True))
                skip_descendants_of = node
            else:
                s = str(node).strip()
                if s:
                    collected_text_parts.append(s)

        html_content = "\n".join(collected_html_parts)
        text_content = "\n".join(t for t in collected_text_parts if t)

        if not text_content.strip():
            continue

        sections.append(
            ParsedSection(
                index=len(sections),
                heading_level=heading_level,
                heading_text=heading_text,
                html_content=html_content,
                text_content=text_content,
            )
        )

        if len(sections) >= _MAX_SECTIONS:
            break

    return sections


def compute_html_content_hash(html: str) -> str:
    """Return a SHA-256 hex digest of the normalised HTML content."""
    normalized = re.sub(r"\s+", " ", html.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def extract_page_title(html: str) -> str:
    """Best-effort extraction of the page ``<title>``."""
    soup = BeautifulSoup(html, "html.parser")
    return _extract_page_title(soup)


def extract_images_from_html(html: str, section_index: int = 0) -> list[ImageInfo]:
    """Extract all ``<img>`` tags from *html* and return their metadata."""
    soup = BeautifulSoup(html, "html.parser")
    images: list[ImageInfo] = []
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        alt = (img.get("alt") or "").strip()
        images.append(ImageInfo(url=src, alt=alt, section_index=section_index))
    return images


def fetch_image_as_base64(url: str, timeout: int = _IMAGE_FETCH_TIMEOUT) -> tuple[str, str] | None:
    """Fetch an image from *url* and return ``(base64_data, media_type)``.

    Returns ``None`` on any failure (timeout, too large, unsupported format).
    SVG images are skipped because the Anthropic API does not support them.
    """
    parsed = urlparse(url)
    ext = os.path.splitext(parsed.path)[1].lower() if parsed.path else ""

    if ext == ".svg":
        return None

    try:
        with httpx.Client(follow_redirects=True, timeout=timeout) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError:
        return None

    if len(resp.content) > _MAX_IMAGE_BYTES or len(resp.content) == 0:
        return None

    content_type = resp.headers.get("content-type", "")
    if "svg" in content_type:
        return None

    media_type = ""
    for supported in ("image/png", "image/jpeg", "image/gif", "image/webp"):
        if supported in content_type:
            media_type = supported
            break

    if not media_type:
        media_type = _MIME_BY_EXT.get(ext, "image/png")

    data = base64.standard_b64encode(resp.content).decode("utf-8")
    return (data, media_type)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_page_title(soup: BeautifulSoup) -> str:
    title_tag = soup.find("title")
    if title_tag:
        return title_tag.get_text(strip=True)
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return "Lecture Notes"


def _is_descendant_of(node, ancestor: Tag) -> bool:
    """Return ``True`` if *node* is a descendant of *ancestor*."""
    parent = getattr(node, "parent", None)
    while parent is not None:
        if parent is ancestor:
            return True
        parent = getattr(parent, "parent", None)
    return False


def _resolve_relative_urls(soup: BeautifulSoup, base_url: str) -> None:
    """Rewrite relative ``src`` and ``href`` attributes to absolute URLs."""
    for tag in soup.find_all(["img", "a", "source", "link", "script"]):
        for attr in ("src", "href"):
            val = tag.get(attr)
            if val and not val.startswith(("http://", "https://", "data:", "#", "mailto:", "javascript:")):
                tag[attr] = urljoin(base_url, val)
