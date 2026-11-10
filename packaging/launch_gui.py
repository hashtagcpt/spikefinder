"""Entry point used by PyInstaller (see README, 'Standalone app')."""
from spikefinder.cli import main_gui

if __name__ == "__main__":
    raise SystemExit(main_gui())
