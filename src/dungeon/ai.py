"""Optional Ollama powered enemy decisions and narration."""
from __future__ import annotations
import os
import string
from typing import Any
import httpx
from .game import Action, Enemy, GameState, legal_actions
from .bots import Brain, RuleBot

class OllamaClient:
    """Small synchronous client for a local Ollama server."""
    def __init__(self, model: str | None = None, client: Any | None = None) -> None:
        self.model = model or os.getenv("DUNGEON_MODEL", "llama3.2:3b")
        self.client = client if client is not None else httpx.Client(timeout=10.0)
    def chat(self, prompt: str) -> str | None:
        """Return assistant content, or None on any network or format error."""
        try:
            response = self.client.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=10.0,
            )
            response.raise_for_status()
            content = response.json().get("message", {}).get("content")
            return content if isinstance(content, str) else None
        except Exception:
            return None
    def reachable(self) -> bool:
        """Return whether the local Ollama API responds."""
        try:
            response = self.client.get("http://localhost:11434/api/tags", timeout=10.0)
            response.raise_for_status()
            return True
        except Exception:
            return False

class AIBrain:
    """Ask Ollama for boss actions periodically, with RuleBot as fallback."""
    def __init__(self, client: OllamaClient, fallback: Brain | None = None) -> None:
        self.client, self.fallback = client, fallback or RuleBot()
        self._last_valid: dict[int, Action] = {}
    def decide(self, state: GameState, enemy: Enemy) -> Action:
        legal = legal_actions(state, enemy)
        fallback = self.fallback.decide(state, enemy)
        if enemy.kind != "boss":
            return fallback if fallback in legal else Action.WAIT
        if state.turn % 3 != 0:
            previous = self._last_valid.get(id(enemy), fallback)
            return previous if previous in legal else fallback
        prompt = (
            f"Boss hp={enemy.hp}; player hp={state.player.hp}; "
            f"distance={abs(enemy.position.x - state.player.position.x) + abs(enemy.position.y - state.player.position.y)}; "
            f"legal actions={[action.name for action in legal]}. Reply with ONLY one action name."
        )
        action = self._parse_action(self.client.chat(prompt), legal)
        if action is None:
            return fallback if fallback in legal else Action.WAIT
        self._last_valid[id(enemy)] = action
        return action
    @staticmethod
    def _parse_action(reply: str | None, legal: list[Action]) -> Action | None:
        if not reply:
            return None
        cleaned = reply.strip().strip(string.punctuation).strip().lower()
        for action in legal:
            if cleaned in {action.name.lower(), action.value.lower()}:
                return action
        return None

class Narrator:
    """Generate optional flavor text for an already recorded game event."""
    def __init__(self, client: OllamaClient) -> None:
        self.client = client
    def narrate(self, event: str) -> str | None:
        """Ask for one short sentence; return no text when Ollama fails."""
        reply = self.client.chat(
            f"Write one short sentence of flavor text for this event: {event}"
        )
        if not reply:
            return None
        sentence = " ".join(reply.strip().split())
        return sentence or None
