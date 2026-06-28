import sys

from .repl import run

run(sys.argv[1] if len(sys.argv) > 1 else None)
