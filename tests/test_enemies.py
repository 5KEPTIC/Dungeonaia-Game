import random

from dungeon.bots import RuleBot
from dungeon.game import Action, Enemy, Position, Tile, astar_path, legal_actions, legal_moves, move_player, new_game


def test_a_star_finds_shortest_path_around_walls() -> None:
    grid = [[Tile.FLOOR] * 5 for _ in range(5)]
    for y in range(1, 4):
        grid[y][2] = Tile.WALL
    path = astar_path(grid, Position(0, 2), Position(4, 2))
    assert len(path) - 1 == 8
    assert all(grid[p.y][p.x] != Tile.WALL for p in path)


def test_rule_bot_flees_at_low_health() -> None:
    state = new_game(2)
    enemy = Enemy("goblin", Position(state.player.position.x + 3, state.player.position.y), 1, 2, 10)
    state.entities = {"goblin": enemy}
    assert RuleBot().decide(state, enemy) == Action.MOVE_AWAY


def test_legal_actions_only_contains_available_actions() -> None:
    state = new_game(4)
    enemy = next(iter(state.entities.values()))
    for action in legal_actions(state, enemy):
        if action == Action.ATTACK:
            assert abs(enemy.position.x - state.player.position.x) + abs(enemy.position.y - state.player.position.y) == 1
        if action == Action.HEAL:
            assert "heal" in enemy.abilities and enemy.hp < (enemy.max_hp or enemy.hp)


def test_random_player_survives_500_turns_without_crashing() -> None:
    state = new_game(12)
    rng = random.Random(9)
    for _ in range(500):
        if state.game_over:
            break
        moves = legal_moves(state)
        if moves:
            move_player(state, *rng.choice(moves))
    assert state.turn <= 500
