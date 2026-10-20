# Dungeon

An offline-first terminal dungeon game built with Python 3.11 or newer.

## Run

Create and activate a virtual environment, then install the project with its development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

Start the game with:

```bash
dungeon
```

Run the test suite with:

```bash
pytest
```

The game is intended to work offline by default. Optional AI integrations must not be required to play.

## Optional local AI

The optional AI layer uses [Ollama](https://ollama.com/) on your own machine. Install Ollama, then pull the default model:

```bash
ollama pull llama3.2:3b
```

Start Ollama and run the game with AI enabled:

```bash
dungeon --ai
```

You can choose another installed model with `DUNGEON_MODEL`, or enable AI without the flag with `DUNGEON_AI=1`. If Ollama is unavailable, the game logs a warning and continues with the offline rule-based enemies.
# Dungeonaia-Game
