import httpx

from dungeon.ai import AIBrain, OllamaClient
from dungeon.bots import RuleBot
from dungeon.game import Action, Enemy, GameState, Player, Position, Tile, _next_floor, new_game


class MockHttpClient:
    def __init__(self, reply: str | None = None, error: Exception | None = None) -> None:
        self.reply = reply
        self.error = error

    def post(self, *args: object, **kwargs: object) -> object:
        if self.error:
            raise self.error
        return MockResponse(self.reply)

    def get(self, *args: object, **kwargs: object) -> object:
        if self.error:
            raise self.error
        return MockResponse(None)


class MockResponse:
    def __init__(self, reply: str | None) -> None:
        self.reply = reply

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return {"message": {"content": self.reply}} if self.reply is not None else {}


def boss_state() -> tuple[GameState, Enemy]:
    grid = [[Tile.FLOOR for _ in range(7)] for _ in range(7)]
    player = Player(Position(3, 3))
    boss = Enemy("boss", Position(3, 2), 20, 5, 20, frozenset())
    state = GameState(grid, player, {"boss": boss}, turn=3)
    return state, boss


def test_ai_brain_accepts_only_a_legal_action_name() -> None:
    state, boss = boss_state()
    brain = AIBrain(OllamaClient(client=MockHttpClient("  attack!!!  ")))

    assert brain.decide(state, boss) == Action.ATTACK


def test_ai_brain_uses_rule_bot_for_garbage_reply() -> None:
    state, boss = boss_state()
    brain = AIBrain(OllamaClient(client=MockHttpClient("cast meteor")))

    assert brain.decide(state, boss) == RuleBot().decide(state, boss)
    assert brain.decide(state, boss) in [Action.WAIT, Action.ATTACK, Action.MOVE_TOWARD, Action.MOVE_AWAY, Action.HEAL]


def test_ai_brain_uses_rule_bot_when_model_times_out() -> None:
    state, boss = boss_state()
    brain = AIBrain(OllamaClient(client=MockHttpClient(error=httpx.ReadTimeout("slow"))))

    assert brain.decide(state, boss) == RuleBot().decide(state, boss)


def test_ollama_client_returns_none_when_server_is_unreachable() -> None:
    client = OllamaClient(client=MockHttpClient(error=ConnectionError("offline")))

    assert client.chat("hello") is None
    assert client.reachable() is False


def test_every_third_floor_has_an_ai_boss_when_ai_is_enabled() -> None:
    state = new_game(8, ai_enabled=True, ai_client=OllamaClient(client=MockHttpClient("wait")))
    _next_floor(state)
    _next_floor(state)

    assert state.floor == 3
    assert state.entities["boss"].kind == "boss"
    assert type(state.brain).__name__ == "AIBrain"
