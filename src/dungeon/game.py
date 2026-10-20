"""Pure Python dungeon generation, combat, and enemy simulation."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum
import heapq
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .ai import OllamaClient
    from .bots import Brain

WIDTH, HEIGHT, FOV_RADIUS = 60, 25, 8


class Tile(str, Enum):
    WALL = "wall"
    FLOOR = "floor"
    STAIRS_DOWN = "stairs_down"


class Action(str, Enum):
    MOVE_TOWARD = "move_toward"
    MOVE_AWAY = "move_away"
    ATTACK = "attack"
    WAIT = "wait"
    HEAL = "heal"


@dataclass(frozen=True, slots=True)
class Position:
    x: int
    y: int


@dataclass(slots=True)
class Player:
    position: Position
    hp: int = 20
    max_hp: int = 20
    attack: int = 4


@dataclass(slots=True)
class Enemy:
    kind: str
    position: Position
    hp: int
    attack: int
    max_hp: int | None = None
    abilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.max_hp is None:
            self.max_hp = self.hp


@dataclass(frozen=True, slots=True)
class Item:
    """A collectible item placed on a walkable dungeon tile."""

    kind: str
    position: Position


Entity = Enemy


@dataclass(slots=True)
class GameState:
    map: list[list[Tile]]
    player: Player
    entities: dict[str, Enemy] = field(default_factory=dict)
    items: dict[str, Item] = field(default_factory=dict)
    inventory: list[str] = field(default_factory=list)
    score: int = 0
    turn: int = 0
    message_log: list[str] = field(default_factory=list)
    explored: set[Position] = field(default_factory=set)
    visible: set[Position] = field(default_factory=set)
    floor: int = 1
    game_over: bool = False
    seed: int | None = None
    brain: Brain | None = None

    @property
    def enemies(self) -> dict[str, Enemy]:
        """Alias for the entity collection used by callers that call them enemies."""
        return self.entities


@dataclass(frozen=True, slots=True)
class Room:
    x: int
    y: int
    width: int
    height: int

    @property
    def center(self) -> Position:
        return Position(self.x + self.width // 2, self.y + self.height // 2)


def _carve_room(grid: list[list[Tile]], room: Room) -> None:
    for y in range(room.y, room.y + room.height):
        for x in range(room.x, room.x + room.width):
            grid[y][x] = Tile.FLOOR


def _carve_corridor(grid: list[list[Tile]], first: Position, second: Position) -> None:
    x, y = first.x, first.y
    while x != second.x:
        grid[y][x] = Tile.FLOOR
        x += 1 if second.x > x else -1
    while y != second.y:
        grid[y][x] = Tile.FLOOR
        y += 1 if second.y > y else -1
    grid[y][x] = Tile.FLOOR


def generate_map(seed: int | None = None, width: int = WIDTH, height: int = HEIGHT) -> tuple[list[list[Tile]], Position]:
    """Generate a reproducible connected dungeon map and player start."""
    if width < 10 or height < 8:
        raise ValueError("dungeon dimensions are too small")
    rng = random.Random(seed)
    grid = [[Tile.WALL for _ in range(width)] for _ in range(height)]
    rooms: list[Room] = []
    target, attempts = rng.randint(6, 9), 0
    while len(rooms) < target and attempts < target * 30:
        attempts += 1
        room = Room(rng.randint(1, width - 12), rng.randint(1, height - 8), rng.randint(5, min(11, width - 2)), rng.randint(4, min(7, height - 2)))
        if room.x + room.width >= width - 1 or room.y + room.height >= height - 1:
            continue
        if any(room.x < o.x + o.width + 1 and room.x + room.width + 1 > o.x and room.y < o.y + o.height + 1 and room.y + room.height + 1 > o.y for o in rooms):
            continue
        rooms.append(room)
        _carve_room(grid, room)
    if not rooms:
        raise RuntimeError("failed to generate a room")
    for first, second in zip(rooms, rooms[1:]):
        _carve_corridor(grid, first.center, second.center)
    start, stairs = rooms[0].center, rooms[-1].center
    if stairs == start:
        stairs = Position(start.x + 1, start.y)
    grid[stairs.y][stairs.x] = Tile.STAIRS_DOWN
    return grid, start


def _spawn_enemies(grid: list[list[Tile]], start: Position, floor: int, seed: int | None) -> dict[str, Enemy]:
    rng = random.Random((seed or 0) + floor * 7919)
    candidates = [Position(x, y) for y, row in enumerate(grid) for x, tile in enumerate(row) if tile != Tile.WALL and Position(x, y) != start and tile != Tile.STAIRS_DOWN]
    rng.shuffle(candidates)
    count = min(len(candidates), 2 + floor)
    enemies: dict[str, Enemy] = {}
    kinds = ("goblin", "orc", "bat")
    for index, position in enumerate(candidates[:count]):
        kind = kinds[index % len(kinds)]
        stats = {"goblin": (5 + floor, 2), "orc": (9 + floor * 2, 3), "bat": (3 + floor, 1)}[kind]
        enemies[f"{kind}-{index}"] = Enemy(kind, position, stats[0], stats[1], stats[0], frozenset({"heal"}) if kind == "orc" else frozenset())
    if floor % 3 == 0 and len(candidates) > count:
        position = candidates[count]
        boss_hp = 18 + floor * 3
        enemies["boss"] = Enemy("boss", position, boss_hp, 5 + floor, boss_hp, frozenset({"heal"}))
    return enemies


def _spawn_items(
    grid: list[list[Tile]],
    start: Position,
    enemies: dict[str, Enemy],
    floor: int,
    seed: int | None,
) -> dict[str, Item]:
    """Place one health potion and one weapon upgrade when space permits."""
    rng = random.Random((seed or 0) + floor * 1543)
    occupied = {start, *(enemy.position for enemy in enemies.values())}
    candidates = [
        Position(x, y)
        for y, row in enumerate(grid)
        for x, tile in enumerate(row)
        if tile != Tile.WALL and tile != Tile.STAIRS_DOWN and Position(x, y) not in occupied
    ]
    rng.shuffle(candidates)
    kinds = ("health_potion", "weapon_upgrade")
    return {
        kind: Item(kind, position)
        for kind, position in zip(kinds, candidates)
    }


def new_game(
    seed: int | None = None,
    ai_enabled: bool = False,
    ai_client: OllamaClient | None = None,
) -> GameState:
    """Create a new offline game with rule based enemy brains."""
    dungeon_map, start = generate_map(seed)
    from .bots import RuleBot
    brain = RuleBot()
    if ai_enabled:
        from .ai import AIBrain, OllamaClient
        # Keep the client injectable so callers and tests can provide a local
        # transport without making the game logic know anything about HTTP.
        brain = AIBrain(ai_client if ai_client is not None else OllamaClient())
    state = GameState(dungeon_map, Player(start), message_log=["You enter the dungeon."], seed=seed, brain=brain)
    state.entities = _spawn_enemies(dungeon_map, start, state.floor, seed)
    state.items = _spawn_items(dungeon_map, start, state.entities, state.floor, seed)
    update_visibility(state)
    return state


def legal_moves(state: GameState) -> tuple[tuple[int, int], ...]:
    """Return cardinal player moves that stay on walkable tiles."""
    result = []
    for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        x, y = state.player.position.x + dx, state.player.position.y + dy
        if 0 <= y < len(state.map) and 0 <= x < len(state.map[0]) and state.map[y][x] != Tile.WALL:
            result.append((dx, dy))
    return tuple(result)


def _enemy_at(state: GameState, position: Position) -> tuple[str, Enemy] | None:
    return next(((key, enemy) for key, enemy in state.entities.items() if enemy.position == position), None)


def _player_attack(state: GameState, enemy: Enemy) -> None:
    enemy.hp -= state.player.attack
    state.message_log.append(f"You hit the {enemy.kind} for {state.player.attack} damage.")
    if enemy.hp <= 0:
        key = next(key for key, value in state.entities.items() if value is enemy)
        del state.entities[key]
        state.score += 10
        state.message_log.append(f"The {enemy.kind} dies.")


def move_player(state: GameState, dx: int, dy: int) -> bool:
    """Move or attack in one cardinal direction, then advance enemy turns."""
    if state.game_over:
        return False
    if (dx, dy) not in ((0, -1), (1, 0), (0, 1), (-1, 0)):
        raise ValueError("movement must be cardinal")
    target = Position(state.player.position.x + dx, state.player.position.y + dy)
    enemy_hit = _enemy_at(state, target)
    if enemy_hit:
        _player_attack(state, enemy_hit[1])
    elif not (0 <= target.y < len(state.map) and 0 <= target.x < len(state.map[0])) or state.map[target.y][target.x] == Tile.WALL:
        state.message_log.append("A wall blocks your way.")
        return False
    else:
        state.player.position = target
        state.message_log.append("You move through the dungeon.")
        _collect_item(state)
    state.turn += 1
    if state.map[state.player.position.y][state.player.position.x] == Tile.STAIRS_DOWN:
        _next_floor(state)
    else:
        _enemy_turns(state)
    update_visibility(state)
    return True


def _next_floor(state: GameState) -> None:
    state.floor += 1
    state.map, start = generate_map((state.seed or 0) + state.floor)
    state.player.position = start
    state.entities = _spawn_enemies(state.map, start, state.floor, state.seed)
    state.items = _spawn_items(state.map, start, state.entities, state.floor, state.seed)
    state.message_log.append(f"You descend to floor {state.floor}.")


def _collect_item(state: GameState) -> None:
    """Collect and apply any item at the player's current position."""
    found = next(
        ((key, item) for key, item in state.items.items() if item.position == state.player.position),
        None,
    )
    if found is None:
        return
    key, item = found
    del state.items[key]
    state.inventory.append(item.kind)
    if item.kind == "health_potion":
        healed = min(state.player.max_hp - state.player.hp, 6)
        state.player.hp += healed
        state.message_log.append(f"You found a health potion and recover {healed} HP.")
    elif item.kind == "weapon_upgrade":
        state.player.attack += 2
        state.message_log.append("You found a weapon upgrade. Your attacks deal +2 damage.")


def astar_path(grid: list[list[Tile]], start: Position, goal: Position, occupied: set[Position] | None = None) -> list[Position]:
    """Find a shortest cardinal path, excluding walls and occupied tiles."""
    if start == goal:
        return [start]
    occupied = occupied or set()
    frontier: list[tuple[int, int, Position]] = [(0, 0, start)]
    came_from: dict[Position, Position | None] = {start: None}
    costs = {start: 0}
    counter = 0
    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current == goal:
            path = [current]
            while came_from[path[-1]] is not None:
                path.append(came_from[path[-1]])  # type: ignore[arg-type]
            return list(reversed(path))
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            nxt = Position(current.x + dx, current.y + dy)
            if not (0 <= nxt.y < len(grid) and 0 <= nxt.x < len(grid[0])) or grid[nxt.y][nxt.x] == Tile.WALL or (nxt in occupied and nxt != goal):
                continue
            new_cost = costs[current] + 1
            if new_cost < costs.get(nxt, 10**9):
                costs[nxt] = new_cost
                counter += 1
                heuristic = abs(goal.x - nxt.x) + abs(goal.y - nxt.y)
                heapq.heappush(frontier, (new_cost + heuristic, counter, nxt))
                came_from[nxt] = current
    return []


def legal_actions(state: GameState, enemy: Enemy) -> list[Action]:
    """Return actions currently valid for an enemy."""
    if enemy not in state.entities.values() or state.game_over:
        return [Action.WAIT]
    distance = abs(enemy.position.x - state.player.position.x) + abs(enemy.position.y - state.player.position.y)
    actions = [Action.WAIT]
    if distance == 1:
        actions.append(Action.ATTACK)
    occupied = {other.position for other in state.entities.values() if other is not enemy}
    if astar_path(state.map, enemy.position, state.player.position, occupied):
        actions.append(Action.MOVE_TOWARD)
    if any(
        0 <= enemy.position.y + dy < len(state.map)
        and 0 <= enemy.position.x + dx < len(state.map[0])
        and state.map[enemy.position.y + dy][enemy.position.x + dx] != Tile.WALL
        and Position(enemy.position.x + dx, enemy.position.y + dy) not in occupied
        and Position(enemy.position.x + dx, enemy.position.y + dy) != state.player.position
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0))
    ):
        actions.append(Action.MOVE_AWAY)
    if "heal" in enemy.abilities and enemy.hp < (enemy.max_hp or enemy.hp):
        actions.append(Action.HEAL)
    return actions


def _enemy_turns(state: GameState) -> None:
    """Apply one Brain decision for each living enemy."""
    if state.brain is None:
        return
    for enemy in list(state.entities.values()):
        if state.game_over:
            break
        action = state.brain.decide(state, enemy)
        if action not in legal_actions(state, enemy):
            action = Action.WAIT
        if action == Action.ATTACK:
            state.player.hp -= enemy.attack
            state.message_log.append(f"The {enemy.kind} hits you for {enemy.attack} damage.")
            if state.player.hp <= 0:
                state.player.hp = 0
                state.game_over = True
                state.message_log.append("You have fallen. Press R to restart.")
        elif action == Action.HEAL:
            enemy.hp = min(enemy.max_hp or enemy.hp, enemy.hp + 2)
            state.message_log.append(f"The {enemy.kind} heals.")
        elif action in (Action.MOVE_TOWARD, Action.MOVE_AWAY):
            _move_enemy(state, enemy, action == Action.MOVE_TOWARD)


def _move_enemy(state: GameState, enemy: Enemy, toward: bool) -> None:
    occupied = {other.position for other in state.entities.values() if other is not enemy}
    path = astar_path(state.map, enemy.position, state.player.position, occupied)
    if toward and len(path) > 1:
        candidate = path[1]
    else:
        options = []
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            candidate = Position(enemy.position.x + dx, enemy.position.y + dy)
            if 0 <= candidate.y < len(state.map) and 0 <= candidate.x < len(state.map[0]) and state.map[candidate.y][candidate.x] != Tile.WALL and candidate not in occupied and candidate != state.player.position:
                options.append(candidate)
        if not options:
            return
        candidate = max(options, key=lambda p: abs(p.x - state.player.position.x) + abs(p.y - state.player.position.y))
    if candidate != state.player.position:
        enemy.position = candidate


def reachable_floor_tiles(grid: list[list[Tile]], start: Position) -> set[Position]:
    """Return every non-wall tile reachable from ``start``."""
    seen, queue = {start}, deque([start])
    while queue:
        current = queue.popleft()
        for dx, dy in ((0, -1), (1, 0), (0, 1), (-1, 0)):
            neighbor = Position(current.x + dx, current.y + dy)
            if neighbor not in seen and 0 <= neighbor.y < len(grid) and 0 <= neighbor.x < len(grid[0]) and grid[neighbor.y][neighbor.x] != Tile.WALL:
                seen.add(neighbor)
                queue.append(neighbor)
    return seen


def a_star(grid: list[list[Tile]], start: Position, goal: Position, occupied: set[Position] | None = None) -> list[Position]:
    """Compatibility spelling for :func:`astar_path`."""
    return astar_path(grid, start, goal, occupied)


def _line_of_sight(start: Position, end: Position, grid: list[list[Tile]]) -> bool:
    steps = max(abs(end.x - start.x), abs(end.y - start.y))
    for i in range(1, steps):
        x, y = round(start.x + (end.x - start.x) * i / steps), round(start.y + (end.y - start.y) * i / steps)
        if grid[y][x] == Tile.WALL:
            return False
    return True


def visible_tiles(state: GameState, radius: int = FOV_RADIUS) -> set[Position]:
    """Return tiles within radius visible from the player."""
    origin, result = state.player.position, set()
    for y in range(max(0, origin.y - radius), min(len(state.map), origin.y + radius + 1)):
        for x in range(max(0, origin.x - radius), min(len(state.map[0]), origin.x + radius + 1)):
            if (x - origin.x) ** 2 + (y - origin.y) ** 2 <= radius**2 and _line_of_sight(origin, Position(x, y), state.map):
                result.add(Position(x, y))
    return result


def update_visibility(state: GameState) -> None:
    """Refresh visible tiles and retain them as explored."""
    state.visible = visible_tiles(state)
    state.explored.update(state.visible)
