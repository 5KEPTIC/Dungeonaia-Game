"""Textual presentation layer."""
from __future__ import annotations
import asyncio
import os
import sys
import time
from dataclasses import dataclass
from math import hypot

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.theme import Theme
from textual.widgets import Button, Footer, Header, Label, ProgressBar, RichLog, Static
from rich.text import Text
from .ai import Narrator, OllamaClient
from .game import GameState, Position, Tile, move_player, new_game
from .rendering import wall_glyph
from .scores import load_high_score, save_high_score

try:
    from pyfiglet import figlet_format
except ImportError:  # Keep the offline UI usable before dependencies are installed.
    def figlet_format(text: str, font: str = "slant") -> str:
        del font
        return text


DUNGEON_THEME = Theme(
    name="dungeon",
    primary="#d6a85f",
    secondary="#705c49",
    accent="#e4b86a",
    warning="#e4b86a",
    error="#a94b4b",
    success="#83b27b",
    foreground="#d4c7b0",
    background="#0b0d10",
    surface="#12171c",
    panel="#1b2026",
    boost="#293039",
    dark=True,
    variables={
        "footer-key-foreground": "#f0c674",
        "footer-description-foreground": "#b7a995",
    },
)


class HelpScreen(ModalScreen[None]):
    """Show keyboard controls above the current game screen."""

    BINDINGS = [Binding("escape", "close", "Close", show=False)]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Static("Controls", id="help-title")
            yield Static(
                "WASD / arrows  Move\n"
                "Space         Wait\n"
                "I             Inventory\n"
                "?             Help\n"
                "Q             Quit\n\n"
                "Walk into an enemy to attack. Find loot and reach the stairs.",
                id="help-controls",
            )
            yield Button("Close", id="close-help", variant="primary")

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "close-help":
            self.dismiss(None)


class TitleLogo(Static):
    """Render the title logo with a warm-to-teal line gradient."""

    def render(self) -> Text:
        logo = figlet_format("DUNGEON", font="slant").rstrip("\n")
        lines = logo.splitlines() or ["DUNGEON"]
        rendered = Text()
        colors = ("#f0c674", "#d6a85f", "#a99b72", "#6f9c91", "#4f9c9c")
        for index, line in enumerate(lines):
            if index:
                rendered.append("\n")
            color = colors[min(index, len(colors) - 1)]
            rendered.append(line, style=f"bold {color}")
        return rendered


class GameOverScreen(ModalScreen[None]):
    """Present the final run statistics without blocking the event loop."""

    BINDINGS = [Binding("r", "restart", "Restart"), Binding("escape", "close", "Close", show=False)]

    def compose(self) -> ComposeResult:
        state = self.app.state
        with Vertical(id="game-over-dialog"):
            yield Static("YOU DIED", id="death-banner")
            yield Static(
                f"Floor reached   {state.floor}\n"
                f"Turns survived  {state.turn}\n"
                f"Enemies killed  {state.score // 10}\n"
                f"Score           {state.score}\n\n"
                "Press r to restart",
                id="death-stats",
            )

    def action_restart(self) -> None:
        self.app.restart_game()

    def action_close(self) -> None:
        self.dismiss(None)


@dataclass(slots=True)
class FloatingDamage:
    position: Position
    text: str
    started: float
    duration: float = 0.5


@dataclass(slots=True)
class FadingDeath:
    position: Position
    started: float
    glyph: str = "x"
    duration: float = 0.42


class NearbyEnemies(Static):
    """Render visible enemies and compact health bars."""

    def __init__(self, state: GameState) -> None:
        super().__init__()
        self.state = state

    def render(self) -> Text:
        player = self.state.player.position
        enemies = sorted(
            (enemy for enemy in self.state.entities.values() if enemy.position in self.state.visible),
            key=lambda enemy: abs(enemy.position.x - player.x) + abs(enemy.position.y - player.y),
        )
        if not enemies:
            return Text("No enemies in sight.", style="dim #81796e")
        rendered = Text()
        for index, enemy in enumerate(enemies):
            label = {"goblin": "g", "orc": "o", "bat": "b", "boss": "B"}.get(enemy.kind, "e")
            ratio = max(0.0, min(1.0, enemy.hp / max(1, enemy.max_hp or enemy.hp)))
            filled = round(ratio * 6)
            bar = "|" * filled + "." * (6 - filled)
            color = "#d05d55" if enemy.kind != "boss" else "#c084fc"
            if index:
                rendered.append("\n")
            rendered.append(f"{label} {enemy.kind[:8]:8} ", style=f"bold {color}" if enemy.kind == "boss" else color)
            rendered.append(bar, style=color)
            rendered.append(f" {enemy.hp}/{enemy.max_hp}", style="#b7a995")
        return rendered


class InventoryView(Static):
    """Render inventory entries with single-width item icons."""

    ICONS = {"health_potion": "!", "weapon_upgrade": "w"}

    def __init__(self, state: GameState) -> None:
        super().__init__()
        self.state = state

    def render(self) -> Text:
        if not self.state.inventory:
            return Text("Empty", style="dim #81796e")
        counts: dict[str, int] = {}
        for item in self.state.inventory:
            counts[item] = counts.get(item, 0) + 1
        rendered = Text()
        for index, (item, count) in enumerate(counts.items()):
            if index:
                rendered.append("  ")
            rendered.append(self.ICONS.get(item, "?"), style="bold #e4b86a")
            rendered.append(f" {item.replace('_', ' ')} x{count}", style="#d4c7b0")
        return rendered


class Minimap(Static):
    """Render a compact explored-room overview."""

    def __init__(self, state: GameState, *, ascii_only: bool = False) -> None:
        super().__init__()
        self.state = state
        self.ascii_only = ascii_only

    def render(self) -> Text:
        grid = self.state.map
        height = len(grid)
        width = len(grid[0]) if height else 0
        scale_x, scale_y = 3, 2
        player = self.state.player.position
        stairs = next(
            (Position(x, y) for y, row in enumerate(grid) for x, tile in enumerate(row) if tile == Tile.STAIRS_DOWN),
            None,
        )
        rendered = Text()
        for y in range(0, height, scale_y):
            for x in range(0, width, scale_x):
                cells = [Position(px, py) for py in range(y, min(y + scale_y, height)) for px in range(x, min(x + scale_x, width))]
                char, style = " ", ""
                if player in cells:
                    char, style = "@", "bold #f0c674"
                elif stairs is not None and stairs in cells and stairs in self.state.explored:
                    char, style = (">" if self.ascii_only else "▼"), "#e4b86a"
                elif any(cell in self.state.explored and grid[cell.y][cell.x] == Tile.FLOOR for cell in cells):
                    char, style = ".", "#71808e"
                elif any(cell in self.state.explored and grid[cell.y][cell.x] == Tile.WALL for cell in cells):
                    char, style = "#", "#4b5965"
                rendered.append(char, style=style)
            if y + scale_y < height:
                rendered.append("\n")
        return rendered


class DungeonMap(Static):
    """Render the explored dungeon viewport with inexpensive lighting."""
    def __init__(self, state: GameState, *, ascii_only: bool = False, effects_enabled: bool = True) -> None:
        super().__init__()
        self.state = state
        self.ascii_only = ascii_only
        self.effects_enabled = effects_enabled
        self._flicker_step = 0
        self._style_cache: dict[tuple[str, int, int], str] = {}
        self._flashed_enemies: dict[Position, float] = {}
        self._floating_damage: list[FloatingDamage] = []
        self._fading_deaths: list[FadingDeath] = []
        self._shake_frames = 0

    def on_mount(self) -> None:
        self.set_interval(0.3, self._flicker)
        if self.effects_enabled:
            self.set_interval(0.05, self._tick_effects)

    def flash_enemy(self, position: Position) -> None:
        if self.effects_enabled:
            self._flashed_enemies[position] = time.monotonic() + 0.15
            self.refresh()

    def add_damage(self, position: Position, amount: int) -> None:
        if self.effects_enabled:
            self._floating_damage.append(FloatingDamage(position, f"-{amount}", time.monotonic()))
            self.refresh()

    def add_death(self, position: Position, *, boss: bool = False) -> None:
        if self.effects_enabled:
            self._fading_deaths.append(FadingDeath(position, time.monotonic(), "%" if boss else "x"))
            self.refresh()

    def shake(self, *, frames: int = 5) -> None:
        if self.effects_enabled:
            self._shake_frames = max(self._shake_frames, frames)

    def _tick_effects(self) -> None:
        now = time.monotonic()
        changed = False
        for position, expiry in list(self._flashed_enemies.items()):
            if expiry <= now:
                del self._flashed_enemies[position]
                changed = True
        old_damage = len(self._floating_damage)
        self._floating_damage = [effect for effect in self._floating_damage if now - effect.started < effect.duration]
        changed = changed or len(self._floating_damage) != old_damage
        old_deaths = len(self._fading_deaths)
        self._fading_deaths = [effect for effect in self._fading_deaths if now - effect.started < effect.duration]
        changed = changed or len(self._fading_deaths) != old_deaths
        if self._shake_frames:
            offsets = ((-1, 0), (1, 0), (0, 1), (-1, 0), (0, 0))
            offset = offsets[min(len(offsets) - 1, 5 - self._shake_frames)]
            self.styles.offset = offset
            self._shake_frames -= 1
            changed = True
            if not self._shake_frames:
                self.styles.offset = (0, 0)
        if changed:
            self.refresh()

    def _flicker(self) -> None:
        """Change the torch falloff only when the next frame differs."""
        next_step = (self._flicker_step + 1) % 4
        if next_step != self._flicker_step:
            self._flicker_step = next_step
            self._style_cache.clear()
            self.refresh()

    def _viewport(self) -> tuple[int, int, int, int]:
        height = len(self.state.map)
        width = len(self.state.map[0]) if height else 0
        viewport_width = min(width, max(1, self.size.width or width))
        viewport_height = min(height, max(1, self.size.height or height))
        player = self.state.player.position
        left = min(max(0, player.x - viewport_width // 2), max(0, width - viewport_width))
        top = min(max(0, player.y - viewport_height // 2), max(0, height - viewport_height))
        return left, top, viewport_width, viewport_height

    def _light_style(self, kind: str, distance: float, *, bold: bool = False) -> str:
        """Return a cached radial-light style for a tile/entity category."""
        radius = 8.0 + (self._flicker_step - 1.5) * 0.22
        bucket = min(8, max(0, int(distance * 8 / radius)))
        key = (kind + (":bold" if bold else ""), bucket, self._flicker_step)
        if key in self._style_cache:
            return self._style_cache[key]
        warm = {"floor": (230, 164, 93), "wall": (198, 133, 75), "stairs": (255, 208, 96)}.get(kind, (220, 150, 75))
        cool = (49, 68, 92)
        if kind == "enemy":
            warm = (239, 104, 91)
        elif kind == "boss":
            warm = (206, 112, 255)
        elif kind == "item":
            warm = (255, 220, 112)
        amount = bucket / 8
        color = tuple(round(warm[i] * (1 - amount) + cool[i] * amount) for i in range(3))
        prefix = "bold " if bold else ""
        style = f"{prefix}rgb({color[0]},{color[1]},{color[2]})"
        self._style_cache[key] = style
        return style

    def _remembered_style(self, kind: str, *, bold: bool = False) -> str:
        return f"{'bold ' if bold else ''}rgb(61,73,88)"

    def render(self) -> Text:
        player = self.state.player.position
        left, top, viewport_width, viewport_height = self._viewport()
        entities = {enemy.position: enemy for enemy in self.state.entities.values()}
        items = {item.position: item for item in self.state.items.values()}
        now = time.monotonic()
        overlays: dict[Position, tuple[str, str]] = {}
        for effect in self._fading_deaths:
            progress = min(1.0, max(0.0, (now - effect.started) / effect.duration))
            color = round(255 * (1.0 - progress))
            overlays[effect.position] = (effect.glyph, f"bold rgb({color},{color},{color})")
        for effect in self._floating_damage:
            progress = min(1.0, max(0.0, (now - effect.started) / effect.duration))
            floating_position = Position(effect.position.x, max(0, effect.position.y - 1 - int(progress * 2)))
            overlays[floating_position] = (effect.text, "bold #f0c674")
        rendered = Text()
        for viewport_y in range(viewport_height):
            y = top + viewport_y
            for viewport_x in range(viewport_width):
                x = left + viewport_x
                tile = self.state.map[y][x]
                pos = Position(x, y)
                visible = pos in self.state.visible
                explored = pos in self.state.explored
                distance = hypot(x - player.x, y - player.y)
                if pos in overlays:
                    char, style = overlays[pos]
                elif pos == player:
                    char, style = "@", self._light_style("player", distance, bold=True)
                elif visible and (enemy := entities.get(pos)) is not None:
                    char = {"goblin": "g", "orc": "o", "bat": "b", "boss": "B"}.get(enemy.kind, "e")
                    if pos in self._flashed_enemies:
                        style = "bold white" if enemy.kind == "boss" else "white"
                    else:
                        style = self._light_style("boss" if enemy.kind == "boss" else "enemy", distance, bold=enemy.kind == "boss")
                elif visible and (item := items.get(pos)) is not None:
                    char = {"health_potion": "!", "weapon_upgrade": "w"}.get(item.kind, "?")
                    style = self._light_style("item", distance)
                elif not explored:
                    char, style = " ", ""
                elif tile == Tile.WALL:
                    char = wall_glyph(self.state.map, x, y, ascii_only=self.ascii_only)
                    style = self._light_style("wall", distance) if visible else self._remembered_style("wall")
                elif tile == Tile.STAIRS_DOWN:
                    char = ">" if self.ascii_only else "▼"
                    style = self._light_style("stairs", distance) if visible else self._remembered_style("stairs")
                else:
                    char = "." if self.ascii_only else "·"
                    style = self._light_style("floor", distance) if visible else self._remembered_style("floor")
                rendered.append(char, style=style)
            if viewport_y < viewport_height - 1:
                rendered.append("\n")
        return rendered

class DungeonApp(App[None]):
    """Playable Textual application."""
    CSS_PATH = "dungeon.tcss"
    TITLE = "Dungeon"
    BINDINGS = [
        ("w", "noop", "Move"),
        ("space", "noop", "Wait"),
        ("i", "noop", "Inventory"),
        ("?", "show_help", "Help"),
        ("q", "quit", "Quit"),
    ]
    def __init__(
        self,
        seed: int | None = None,
        ai_enabled: bool | None = None,
        ai_client: OllamaClient | None = None,
        ascii_only: bool | None = None,
        no_effects: bool | None = None,
    ) -> None:
        super().__init__()
        self.register_theme(DUNGEON_THEME)
        self.theme = "dungeon"
        self.ascii_only = "--ascii" in sys.argv if ascii_only is None else ascii_only
        self.effects_enabled = not ("--no-effects" in sys.argv if no_effects is None else no_effects)
        requested_ai = ai_enabled if ai_enabled is not None else os.getenv("DUNGEON_AI") == "1"
        self.ai_enabled = requested_ai
        self._ai_client = ai_client if ai_client is not None else OllamaClient()
        self.narrator: Narrator | None = None
        self._announced_messages = 1
        self._log_cursor = 0
        self._message_turns: list[int] = []
        self._narration_messages: set[str] = set()
        self._game_over_shown = False
        self.high_score = load_high_score()
        if requested_ai and not self._ai_client.reachable():
            self.ai_enabled = False
            self.state = new_game(seed)
            self.state.message_log.append("Warning: Ollama is unavailable; continuing without AI.")
            self._announced_messages = len(self.state.message_log)
        else:
            self.state = new_game(seed, ai_enabled=self.ai_enabled, ai_client=self._ai_client)
            if self.ai_enabled:
                self.narrator = Narrator(self._ai_client)
    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Vertical(id="title-screen"):
            yield TitleLogo(id="title-art")
            yield Button("Start", id="start")
            yield Button("How to play", id="how-to-play")
            yield Button("Quit", id="quit-title")
            yield Static("", id="help-text")
        with Vertical(id="game-screen"):
            with Horizontal(id="main-row"):
                dungeon_map = DungeonMap(self.state, ascii_only=self.ascii_only, effects_enabled=self.effects_enabled)
                dungeon_map.border_title = "Dungeon"
                yield dungeon_map
                with Vertical(id="sidebar"):
                    hero = Vertical(id="hero-panel")
                    hero.border_title = "Hero"
                    with hero:
                        yield Label("Hero", id="hero-name")
                        yield Label("HP 20/20", id="hp-label")
                        yield ProgressBar(total=self.state.player.max_hp, show_percentage=False, show_eta=False, id="hp-bar", classes="hp-good")
                        yield Label(f"Floor  {self.state.floor}", id="floor")
                        yield Label("Turn   0", id="turn")
                        yield Label("Score  0", id="score")
                        yield Label(f"Best   {self.high_score}", id="high-score")
                    with Vertical(id="nearby-panel"):
                        nearby = NearbyEnemies(self.state)
                        nearby.border_title = "Nearby"
                        yield nearby
                    with Vertical(id="inventory-panel"):
                        inventory = InventoryView(self.state)
                        inventory.border_title = "Inventory"
                        yield inventory
                    with Vertical(id="minimap-panel"):
                        minimap = Minimap(self.state, ascii_only=self.ascii_only)
                        minimap.border_title = "Minimap"
                        yield minimap
            log = RichLog(max_lines=100, auto_scroll=True, wrap=True, id="messages")
            log.border_title = "Log"
            yield log
            yield Static("", id="game-over")
            yield Static("", id="floor-transition")
        yield Footer()

    def on_mount(self) -> None:
        """Show the title screen before the dungeon begins."""
        self.query_one("#game-screen").display = False
        self._sync_log()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle title-screen menu choices."""
        if event.button.id == "start":
            self._start_game()
        elif event.button.id == "how-to-play":
            self.query_one("#help-text", Static).update(
                "Move with arrows or WASD. Walk into enemies to attack. "
                "Find items and reach the stairs."
            )
        elif event.button.id == "quit-title":
            self.exit()

    def _start_game(self) -> None:
        """Switch from the title screen to the dungeon view."""
        self.query_one("#title-screen").display = False
        self.query_one("#game-screen").display = True

    def action_noop(self) -> None:
        """Provide footer-only hints for controls handled by ``on_key``."""

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def on_key(self, event: object) -> None:
        key = getattr(event, "key", "")
        if key in {"?", "question_mark"}:
            self.action_show_help()
            return
        if self.query_one("#title-screen").display:
            if key == "enter":
                self._start_game()
                return
            if key not in {"q"}:
                self._start_game()
        if key == "r" and self.state.game_over:
            self.restart_game()
            return
        directions = {"up": (0, -1), "w": (0, -1), "k": (0, -1), "right": (1, 0), "d": (1, 0), "l": (1, 0), "down": (0, 1), "s": (0, 1), "j": (0, 1), "left": (-1, 0), "a": (-1, 0), "h": (-1, 0)}
        if key in directions:
            previous_hp = self.state.player.hp
            previous_floor = self.state.floor
            previous_messages = len(self.state.message_log)
            previous_enemies = {
                key: (enemy.position, enemy.hp, enemy.kind)
                for key, enemy in self.state.entities.items()
            }
            move_player(self.state, *directions[key])
            self._trigger_combat_effects(previous_hp, previous_floor, previous_messages, previous_enemies)
            self._refresh_widgets()

    def restart_game(self) -> None:
        """Reset game state and presentation after a game-over restart."""
        self.state = new_game(self.state.seed, ai_enabled=self.ai_enabled, ai_client=self._ai_client)
        self._announced_messages = len(self.state.message_log)
        self.query_one(DungeonMap).state = self.state
        self.query_one(NearbyEnemies).state = self.state
        self.query_one(InventoryView).state = self.state
        self.query_one(Minimap).state = self.state
        self._narration_messages.clear()
        self._game_over_shown = False
        if isinstance(self.screen, GameOverScreen):
            self.pop_screen()
        self._sync_log(reset=True)
        self._refresh_widgets()

    def _trigger_combat_effects(
        self,
        previous_hp: int,
        previous_floor: int,
        previous_messages: int,
        previous_enemies: dict[str, tuple[Position, int, str]],
    ) -> None:
        """Translate a completed turn into short-lived presentation effects."""
        dungeon_map = self.query_one(DungeonMap)
        if not self.effects_enabled:
            return
        if self.state.player.hp < previous_hp:
            self._flash_damage()
        for key, (old_position, old_hp, kind) in previous_enemies.items():
            enemy = self.state.entities.get(key)
            new_hp = enemy.hp if enemy is not None else 0
            damage = old_hp - new_hp
            if damage <= 0:
                continue
            target = enemy.position if enemy is not None else old_position
            dungeon_map.add_damage(target, damage)
            if enemy is not None:
                dungeon_map.flash_enemy(target)
            else:
                dungeon_map.add_death(old_position, boss=kind == "boss")
            if damage >= 5 or kind == "boss":
                dungeon_map.shake()
        new_messages = self.state.message_log[previous_messages:]
        boss_attack = any("boss hits you" in message for message in new_messages)
        player_damage = previous_hp - self.state.player.hp
        if player_damage >= 5 or boss_attack:
            dungeon_map.shake(frames=7)
        if self.state.floor != previous_floor:
            self._show_floor_transition(self.state.floor)

    def _update_hp_style(self) -> None:
        hp_bar = self.query_one("#hp-bar", ProgressBar)
        hp_bar.remove_class("hp-good", "hp-warning", "hp-danger")
        ratio = self.state.player.hp / max(1, self.state.player.max_hp)
        hp_bar.add_class("hp-good" if ratio > 0.6 else "hp-warning" if ratio > 0.3 else "hp-danger")

    def _sync_log(self, *, reset: bool = False) -> None:
        log = self.query_one("#messages", RichLog)
        if reset:
            log.clear()
            self._log_cursor = 0
            self._message_turns.clear()
        new_messages = self.state.message_log[self._log_cursor :]
        for message in new_messages:
            turn = self.state.turn
            self._message_turns.append(turn)
            style = "#d4c7b0"
            if message in self._narration_messages:
                style = "italic #c084fc"
            elif "hits you" in message or "fallen" in message:
                style = "#d05d55"
            elif "hit the" in message or "damage" in message:
                style = "#e08b4f"
            elif "recover" in message or "heals" in message:
                style = "#83b27b"
            elif "found" in message:
                style = "#e4b86a"
            line = Text.assemble((f"[{turn:03d}] ", "dim #69727b"), (message, style))
            log.write(line, scroll_end=True)
        self._log_cursor = len(self.state.message_log)

    def _refresh_sidebar(self) -> None:
        self.query_one(NearbyEnemies).refresh()
        self.query_one(InventoryView).refresh()
        self.query_one(Minimap).refresh()
        self.query_one("#hp-label", Label).update(f"HP     {self.state.player.hp}/{self.state.player.max_hp}")
        self._update_hp_style()

    def _flash_damage(self) -> None:
        """Briefly tint the dungeon map border after the player is hit."""
        dungeon_map = self.query_one(DungeonMap)
        dungeon_map.add_class("damage-flash")
        self.set_timer(0.18, lambda: dungeon_map.remove_class("damage-flash"))

    def _show_floor_transition(self, floor: int) -> None:
        """Show a non-blocking one-second floor card between dungeon floors."""
        if not self.effects_enabled:
            return
        transition = self.query_one("#floor-transition", Static)
        transition.update(f"Floor {floor}")
        transition.display = True
        transition.styles.opacity = 1.0

        def fade() -> None:
            transition.styles.animate(
                "opacity",
                0.0,
                duration=0.35,
                on_complete=lambda: setattr(transition, "display", False),
            )

        self.set_timer(0.65, fade)

    def _refresh_widgets(self) -> None:
        self._queue_narration_for_new_messages()
        self.query_one(DungeonMap).refresh()
        self._refresh_sidebar()
        self.query_one("#floor", Label).update(f"Floor  {self.state.floor}")
        self.query_one("#turn", Label).update(f"Turn   {self.state.turn}")
        self.query_one("#hp-bar", ProgressBar).update(progress=self.state.player.hp)
        self.query_one("#score", Label).update(f"Score  {self.state.score}")
        self.high_score = save_high_score(self.state.score) if self.state.score > self.high_score else self.high_score
        self.query_one("#high-score", Label).update(f"Best   {self.high_score}")
        self._sync_log()
        game_over = self.query_one("#game-over", Static)
        game_over.update("GAME OVER — press R to restart" if self.state.game_over else "")
        game_over.display = self.state.game_over
        if self.state.game_over and not self._game_over_shown:
            self._game_over_shown = True
            self.push_screen(GameOverScreen())

    def _queue_narration_for_new_messages(self) -> None:
        """Keep game messages immediate while optional flavor runs in workers."""
        if self.narrator is None:
            self._announced_messages = len(self.state.message_log)
            return
        new_messages = self.state.message_log[self._announced_messages :]
        self._announced_messages = len(self.state.message_log)
        for event in new_messages:
            self.run_worker(self._narrate_event(event), exclusive=False)

    async def _narrate_event(self, event: str) -> None:
        """Append AI flavor text without blocking Textual's event loop."""
        assert self.narrator is not None
        try:
            sentence = await asyncio.wait_for(
                asyncio.to_thread(self.narrator.narrate, event), timeout=10.0
            )
        except Exception:
            return
        if sentence:
            self.state.message_log.append(sentence)
            self._narration_messages.add(sentence)
            self._announced_messages = len(self.state.message_log)
            self.call_after_refresh(self._refresh_widgets)
