"""Compatibility entry point; prefer ``python -m sciencenet_bot``."""

from sciencenet_bot.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
