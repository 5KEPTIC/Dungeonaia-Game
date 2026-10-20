"""Offline rule based enemy brains."""
from __future__ import annotations
from typing import Protocol
from .game import Action, Enemy, GameState, astar_path, legal_actions

class Brain(Protocol):
    """Interface used by every enemy decision."""
    def decide(self, state: GameState, enemy: Enemy) -> Action: ...

class RuleBot:
    """A deterministic brain using visibility, distance, and A* paths."""
    def decide(self, state: GameState, enemy: Enemy) -> Action:
        distance = abs(enemy.position.x - state.player.position.x) + abs(enemy.position.y - state.player.position.y)
        if distance == 1:
            return Action.ATTACK
        if enemy.hp < (enemy.max_hp or enemy.hp) * 0.25:
            return Action.MOVE_AWAY if Action.MOVE_AWAY in legal_actions(state, enemy) else Action.WAIT
        if distance <= 10 or enemy.position in state.visible:
            return Action.MOVE_TOWARD if astar_path(state.map, enemy.position, state.player.position) else Action.WAIT
        return Action.WAIT
