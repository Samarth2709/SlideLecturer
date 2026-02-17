"""Tool definitions and execution for additional content retrieval."""

from __future__ import annotations

import json
from typing import Any

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

ALL_TOOLS = [TOOL_LIST_CONTENT, TOOL_GET_CONTENT]


class ContentToolResolver:
    """Resolves tool calls against an in-memory dict of content entries."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
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

    def has_content(self) -> bool:
        return len(self._by_name) > 0

    def content_names_summary(self) -> str:
        """Text block listing available item names for inclusion in the user message."""
        if not self._by_name:
            return ""
        lines = []
        for name, entry in self._by_name.items():
            lines.append(f'- "{name}" ({entry.get("type", "text")})')
        return (
            "The student has provided the following additional content items. "
            "You can use the list_additional_content and get_additional_content tools to access them:\n"
            + "\n".join(lines)
        )

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
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

        return f'Error: Unknown tool "{tool_name}"'
