"""Tool definitions and execution for additional content and section image retrieval."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from .url_service import extract_images_from_html, fetch_image_as_base64

if TYPE_CHECKING:
    from .deck_service import DeckRecord

TOOL_LIST_CONTENT = {
    "name": "list_additional_content",
    "description": (
        "Returns a list of all additional content items the student has provided. "
        "Each item has a 'name' and a 'type' (text or file). "
        "Use this to see what supplementary materials are available."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
        "required": [],
    },
}

TOOL_GET_CONTENT = {
    "name": "get_additional_content",
    "description": (
        "Retrieves the full text content of a specific additional content item by name. "
        "Use this when you need to read the student's supplementary materials to answer their question."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The exact name of the content item to retrieve.",
            },
        },
        "required": ["name"],
    },
}

TOOL_LIST_SECTION_IMAGES = {
    "name": "list_section_images",
    "description": (
        "Lists all images found in the lecture notes. Returns a JSON array of objects, "
        "each with 'section_index', 'section_heading', 'url', and 'alt' fields. "
        "Optionally filter by a specific section index. "
        "Use this to discover what images are available in the lecture content."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "section_index": {
                "type": "integer",
                "description": "Optional. If provided, only list images from this specific section (0-based index).",
            },
        },
        "required": [],
    },
}

TOOL_GET_SECTION_IMAGE = {
    "name": "get_section_image",
    "description": (
        "Fetches a specific image from the lecture notes by its URL and returns it for visual inspection. "
        "Use the list_section_images tool first to find available image URLs, "
        "then use this tool to view a specific image."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "The URL of the image to fetch, as returned by list_section_images.",
            },
        },
        "required": ["url"],
    },
}


def get_tools(has_additional_content: bool, has_url_images: bool) -> list[dict] | None:
    """Build the tool list based on what content is available."""
    tools: list[dict] = []
    if has_additional_content:
        tools.extend([TOOL_LIST_CONTENT, TOOL_GET_CONTENT])
    if has_url_images:
        tools.extend([TOOL_LIST_SECTION_IMAGES, TOOL_GET_SECTION_IMAGE])
    return tools if tools else None


class ContentToolResolver:
    """Resolves tool calls against an in-memory dict of content entries and optional deck images."""

    def __init__(
        self,
        entries: list[dict[str, Any]],
        deck: DeckRecord | None = None,
    ) -> None:
        self._by_name: dict[str, dict[str, Any]] = {}
        for entry in entries:
            name = entry["name"]
            # Deduplicate names by appending a suffix.
            if name in self._by_name:
                counter = 2
                while f"{name} ({counter})" in self._by_name:
                    counter += 1
                name = f"{name} ({counter})"
                entry = {**entry, "name": name}
            self._by_name[name] = entry

        self._deck = deck
        self._image_cache: dict[str, tuple[str, str]] = {}

    def has_additional_content(self) -> bool:
        return len(self._by_name) > 0

    def has_url_images(self) -> bool:
        return self._deck is not None and self._deck.content_type == "url"

    def has_content(self) -> bool:
        return self.has_additional_content() or self.has_url_images()

    def content_names_summary(self) -> str:
        """Text block listing available capabilities for inclusion in the user message."""
        parts: list[str] = []

        if self._by_name:
            lines = []
            for name, entry in self._by_name.items():
                lines.append(f'- "{name}" ({entry.get("type", "text")})')
            parts.append(
                "The student has provided the following additional content items. "
                "You can use the list_additional_content and get_additional_content tools to access them:\n"
                + "\n".join(lines)
            )

        if self.has_url_images():
            parts.append(
                "The lecture content contains images embedded in sections. "
                "You can use list_section_images to discover available images "
                "and get_section_image to view a specific image when it would help answer a question."
            )

        return "\n\n".join(parts)

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str | list[dict]:
        if tool_name == "list_additional_content":
            items = [
                {"name": name, "type": entry.get("type", "text")}
                for name, entry in self._by_name.items()
            ]
            return json.dumps(items)

        if tool_name == "get_additional_content":
            name = tool_input.get("name", "")
            entry = self._by_name.get(name)
            if entry is None:
                available = list(self._by_name.keys())
                return f'Error: No content item found with name "{name}". Available: {available}'
            return entry["content"]

        if tool_name == "list_section_images":
            return self._list_section_images(tool_input)

        if tool_name == "get_section_image":
            return self._get_section_image(tool_input)

        return f'Error: Unknown tool "{tool_name}"'

    def _list_section_images(self, tool_input: dict[str, Any]) -> str:
        if self._deck is None or self._deck.content_type != "url":
            return "Error: Image listing is only available for URL-based lecture content."

        target_section = tool_input.get("section_index")
        all_images: list[dict] = []

        for i, html in enumerate(self._deck.section_html):
            if target_section is not None and i != target_section:
                continue
            heading = self._deck.section_headings[i] if i < len(self._deck.section_headings) else ""
            for img in extract_images_from_html(html, section_index=i):
                all_images.append({
                    "section_index": i,
                    "section_heading": heading,
                    "url": img.url,
                    "alt": img.alt,
                })

        return json.dumps(all_images)

    def _get_section_image(self, tool_input: dict[str, Any]) -> str | list[dict]:
        url = tool_input.get("url", "")
        if not url:
            return "Error: 'url' parameter is required."

        if url in self._image_cache:
            b64_data, media_type = self._image_cache[url]
        else:
            result = fetch_image_as_base64(url)
            if result is None:
                return f"Error: Could not fetch image from URL: {url}"
            b64_data, media_type = result
            self._image_cache[url] = (b64_data, media_type)

        return [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64_data,
                },
            }
        ]
