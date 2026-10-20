"""Application entry point."""
import argparse
import os

from .ui import DungeonApp

def main() -> None:
    """Start the game."""
    parser = argparse.ArgumentParser(description="Play the offline dungeon game.")
    parser.add_argument("--ai", action="store_true", help="enable optional local Ollama AI")
    parser.add_argument("--ascii", action="store_true", help="use ASCII map glyphs")
    parser.add_argument("--no-effects", action="store_true", help="disable visual combat and transition effects")
    args = parser.parse_args()
    ai_enabled = args.ai or os.getenv("DUNGEON_AI") == "1"
    DungeonApp(ai_enabled=ai_enabled, ascii_only=args.ascii, no_effects=args.no_effects).run()

if __name__ == "__main__":
    main()
