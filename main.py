"""Entry point for Vertex."""

import os
import sys

# The app's modules live in src/ and import each other flatly ("import core"),
# so src/ has to be on the path before the first of them is imported. Resolved
# from this file, not the cwd, because the desktop entry launches from anywhere.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

import gui  # noqa: E402 — needs the path above


if __name__ == "__main__":
    gui.main()
