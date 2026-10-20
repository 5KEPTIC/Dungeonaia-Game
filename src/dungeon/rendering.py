"""Pure helpers for drawing the dungeon map."""
from __future__ import annotations

from collections.abc import Sequence

from .game import Tile


_WALL_GLYPHS: dict[tuple[bool, bool, bool, bool], str] = {
    (False, False, False, False): "·",
    (True, False, False, False): "╵",
    (False, True, False, False): "╴",
    (False, False, True, False): "╷",
    (False, False, False, True): "╶",
    (True, False, True, False): "║",
    (False, True, False, True): "═",
    (False, True, True, False): "╔",
    (False, False, True, True): "╗",
    (True, True, False, False): "╚",
    (True, False, False, True): "╝",
    (True, True, True, False): "╠",
    (True, False, True, True): "╣",
    (False, True, True, True): "╦",
    (True, True, False, True): "╩",
    (True, True, True, True): "╬",
}


def wall_glyph(
    grid: Sequence[Sequence[Tile]],
    x: int,
    y: int,
    *,
    ascii_only: bool = False,
) -> str:
    """Return the wall glyph selected from its north/east/south/west walls."""
    if ascii_only:
        return "#"
    height = len(grid)
    width = len(grid[0]) if height else 0

    def is_wall(nx: int, ny: int) -> bool:
        return 0 <= ny < height and 0 <= nx < width and grid[ny][nx] == Tile.WALL

    connections = (
        is_wall(x, y - 1),
        is_wall(x + 1, y),
        is_wall(x, y + 1),
        is_wall(x - 1, y),
    )
    return _WALL_GLYPHS[connections]
