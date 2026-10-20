import pytest

from dungeon.game import legal_moves
from dungeon.game import Tile
from dungeon.rendering import wall_glyph
from dungeon.ui import DungeonApp, DungeonMap


@pytest.mark.asyncio
async def test_movement_keys_change_player_position() -> None:
    async with DungeonApp(seed=21).run_test() as pilot:
        app = pilot.app
        start = app.state.player.position
        direction_keys = {(0, -1): "w", (1, 0): "d", (0, 1): "s", (-1, 0): "a"}
        key = direction_keys[legal_moves(app.state)[0]]
        await pilot.press(key)
        assert app.state.player.position != start


@pytest.mark.asyncio
async def test_q_quits_cleanly() -> None:
    app = DungeonApp(seed=22)
    async with app.run_test() as pilot:
        await pilot.press("q")
        assert app.return_value is None
        assert app.is_running is False


@pytest.mark.asyncio
async def test_game_over_screen_and_restart() -> None:
    async with DungeonApp(seed=23).run_test() as pilot:
        app = pilot.app
        app.state.player.hp = 0
        app.state.game_over = True
        app._refresh_widgets()
        game_over = app.query_one("#game-over")
        assert game_over.display is True
        assert "GAME OVER" in str(game_over.render())
        await pilot.press("r")
        assert app.state.game_over is False
        assert app.state.player.hp > 0
        assert app.query_one("#game-over").display is False


@pytest.mark.asyncio
async def test_scripted_session_with_fixed_seed_has_no_exceptions() -> None:
    keys = ("w", "d", "s", "a", "up", "right", "down", "left", "h", "j", "k", "l") * 17
    async with DungeonApp(seed=24).run_test() as pilot:
        await pilot.press(*keys[:200])
        assert pilot.app.state.turn <= 200
        assert pilot.app.query_one(DungeonMap)


def test_wall_autotiling_selects_box_drawing_connections() -> None:
    grid = [[Tile.FLOOR for _ in range(3)] for _ in range(3)]
    grid[1][1] = Tile.WALL
    grid[0][1] = Tile.WALL
    grid[1][2] = Tile.WALL
    grid[2][1] = Tile.WALL
    grid[1][0] = Tile.WALL
    assert wall_glyph(grid, 1, 1) == "╬"

    grid[0][1] = Tile.FLOOR
    assert wall_glyph(grid, 1, 1) == "╦"
    assert wall_glyph(grid, 1, 1, ascii_only=True) == "#"
