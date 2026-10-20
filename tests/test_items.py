from pathlib import Path

from dungeon.game import GameState, Item, Player, Position, Tile, move_player
from dungeon.scores import load_high_score, save_high_score


def item_state(kind: str) -> GameState:
    grid = [[Tile.FLOOR for _ in range(5)] for _ in range(5)]
    player = Player(Position(2, 2), hp=10, max_hp=20, attack=4)
    return GameState(
        grid,
        player,
        items={kind: Item(kind, Position(3, 2))},
        message_log=[],
    )


def test_health_potion_is_collected_and_heals_player() -> None:
    state = item_state("health_potion")

    assert move_player(state, 1, 0) is True
    assert state.player.hp == 16
    assert state.inventory == ["health_potion"]
    assert state.items == {}


def test_weapon_upgrade_is_collected_and_increases_attack() -> None:
    state = item_state("weapon_upgrade")

    assert move_player(state, 1, 0) is True
    assert state.player.attack == 6
    assert state.inventory == ["weapon_upgrade"]


def test_high_score_is_saved_and_never_lowered(tmp_path: Path) -> None:
    score_file = tmp_path / "score"

    assert save_high_score(42, score_file) == 42
    assert save_high_score(12, score_file) == 42
    assert load_high_score(score_file) == 42
