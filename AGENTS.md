# Project rules

1. Game logic (map, movement, combat, pathfinding) is pure Python and must NOT import textual.
2. The UI layer (`ui.py`) only renders state and forwards key presses to game logic.
3. Every enemy decision goes through the Brain interface: `decide(state) -> Action`.
4. Any AI/LLM output is untrusted. Validate it against the list of legal actions, and fall back to the rule-based bot on any error, timeout or invalid output.
5. The game must run fully offline with no AI by default.
6. Add type hints and a pytest test for every new game-logic function.
7. Run `pytest` after every change and fix failures before finishing.
