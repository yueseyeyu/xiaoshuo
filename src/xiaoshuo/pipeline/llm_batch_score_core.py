"""Side-effect-free helpers for the legacy LLM batch-score facade."""

from collections.abc import Mapping, Sequence
from typing import Any


def _normalize_hook(hook_val: Any) -> str:
    """Normalize a rubric hook value without reading process or module state."""
    if not hook_val:
        return "none"
    value = str(hook_val)
    if value in ("none", "weak", "strong"):
        return value
    try:
        numeric = float(value)
        if numeric >= 7:
            return "strong"
        if numeric >= 4:
            return "weak"
        return "none"
    except (TypeError, ValueError):
        return "none"


def _truncate_reference_text(text: str, max_len: int = 400) -> str:
    """Keep the legacy head/tail truncation boundary."""
    if len(text) <= max_len:
        return text
    head_len = min(150, max_len // 3)
    return text[:head_len] + "\n...[省略]...\n" + text[-(max_len - head_len - 20):]


def _select_references(
    references: Sequence[Mapping[str, Any]],
    exclude_book: str | None = None,
    exclude_ch_num: int | None = None,
) -> list[Mapping[str, Any]]:
    """Select one nearest reference for each fixed score band."""
    bands = ("low", "medium_low", "medium_high", "high")
    band_centers = {"low": 2.5, "medium_low": 4.5, "medium_high": 6.5, "high": 8.5}
    selected: list[Mapping[str, Any]] = []

    for band in bands:
        candidates = [
            reference
            for reference in references
            if reference["band"] == band
            and not (
                reference["book"] == exclude_book
                and reference["ch_num"] == exclude_ch_num
            )
        ]
        if not candidates:
            candidates = [reference for reference in references if reference["band"] == band]
        if not candidates:
            continue
        center = band_centers[band]
        selected.append(min(candidates, key=lambda item: abs(item["human_intensity"] - center)))
    return selected

