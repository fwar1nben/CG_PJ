"""Prompt loading and lightweight schema checks."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

PROMPT_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
VALID_CATEGORIES = {"ui", "object", "scene"}
VALID_STYLES = {"line", "filled", "mixed"}


@dataclass(frozen=True)
class PromptItem:
    id: str
    category: str
    prompt: str
    style: str
    palette: tuple[str, str, str]


def load_prompts(path: str | Path) -> list[PromptItem]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("Prompt file must contain a JSON list.")

    prompts = [_parse_prompt(item, index) for index, item in enumerate(raw)]
    ids = [item.id for item in prompts]
    duplicates = sorted({item_id for item_id in ids if ids.count(item_id) > 1})
    if duplicates:
        raise ValueError(f"Duplicate prompt ids: {', '.join(duplicates)}")
    return prompts


def _parse_prompt(item: Any, index: int) -> PromptItem:
    if not isinstance(item, dict):
        raise ValueError(f"Prompt item {index} must be an object.")

    required = {"id", "category", "prompt", "style", "palette"}
    missing = sorted(required.difference(item))
    extra = sorted(set(item).difference(required))
    if missing:
        raise ValueError(f"Prompt item {index} is missing fields: {', '.join(missing)}")
    if extra:
        raise ValueError(f"Prompt item {index} has unsupported fields: {', '.join(extra)}")

    prompt_id = _expect_string(item["id"], index, "id")
    category = _expect_string(item["category"], index, "category")
    prompt = _expect_string(item["prompt"], index, "prompt")
    style = _expect_string(item["style"], index, "style")
    palette_raw = item["palette"]

    if not PROMPT_ID_RE.match(prompt_id):
        raise ValueError(f"Prompt item {index} has invalid id: {prompt_id}")
    if category not in VALID_CATEGORIES:
        raise ValueError(f"Prompt item {index} has invalid category: {category}")
    if style not in VALID_STYLES:
        raise ValueError(f"Prompt item {index} has invalid style: {style}")
    if len(prompt) < 20:
        raise ValueError(f"Prompt item {index} prompt is too short.")
    if not isinstance(palette_raw, list) or len(palette_raw) != 3:
        raise ValueError(f"Prompt item {index} palette must contain exactly 3 colors.")

    palette = tuple(_expect_string(color, index, "palette") for color in palette_raw)
    for color in palette:
        if not HEX_RE.match(color):
            raise ValueError(f"Prompt item {index} has invalid palette color: {color}")

    return PromptItem(
        id=prompt_id,
        category=category,
        prompt=prompt,
        style=style,
        palette=(palette[0], palette[1], palette[2]),
    )


def _expect_string(value: Any, index: int, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Prompt item {index} field {field} must be a non-empty string.")
    return value.strip()

