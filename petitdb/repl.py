"""A tiny interactive shell. Run with `python -m petitdb [data-dir]`."""

import sys

from .database import Database, PetitDBError
from .query import execute


def _print_rows(rows):
    if not rows:
        print("(0 rows)")
        return
    cols = list(rows[0])
    width = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(c.ljust(width[c]) for c in cols))
    print("  ".join("-" * width[c] for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(width[c]) for c in cols))
    print(f"({len(rows)} row{'s' if len(rows) != 1 else ''})")


def run(path=None):
    db = Database(path)
    where = path if path else "in memory"
    print(f"petit-db — tiny SQL shell ({where}). Try .help, .exit")
    while True:
        try:
            line = input("petit> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in (".exit", ".quit"):
            break
        if line == ".help":
            print("statements: CREATE TABLE, CREATE INDEX, INSERT, SELECT, UPDATE,")
            print("            DELETE, EXPLAIN SELECT, DROP TABLE")
            print("commands:   .tables, .exit")
            continue
        if line == ".tables":
            print(", ".join(db.tables) or "(none)")
            continue
        try:
            result = execute(db, line)
        except PetitDBError as e:
            print(f"error: {e}")
            continue
        if isinstance(result, list):
            _print_rows(result)
        elif isinstance(result, str):
            print(result)            # EXPLAIN plan
        elif isinstance(result, int):
            print(f"{result} row(s) affected")
        else:
            print("ok")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else None)
