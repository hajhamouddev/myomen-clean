"""Entry point. Routes to the command line, which opens the window by default."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
