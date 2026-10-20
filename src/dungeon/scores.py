"""Small, offline high-score persistence helpers."""
from __future__ import annotations

from pathlib import Path

DEFAULT_SCORE_FILE = ".dungeon_high_score"


def high_score_path(path: Path | None = None) -> Path:
    """Return the configured score file, defaulting to the user's home."""
    return path if path is not None else Path.home() / DEFAULT_SCORE_FILE


def load_high_score(path: Path | None = None) -> int:
    """Read the saved high score, treating missing or malformed files as zero."""
    try:
        return max(0, int(high_score_path(path).read_text(encoding="utf-8").strip()))
    except (OSError, ValueError):
        return 0


def save_high_score(score: int, path: Path | None = None) -> int:
    """Persist the highest of ``score`` and the existing score."""
    target = high_score_path(path)
    best = max(load_high_score(target), score)
    try:
        target.write_text(f"{best}\n", encoding="utf-8")
    except OSError:
        return best
    return best
