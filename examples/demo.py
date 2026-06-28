"""A short walk through both the Python API and the SQL layer.

    python examples/demo.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from petitdb import Database, execute


def main():
    db = Database()  # in-memory; pass a directory to persist

    # --- Python API ---
    movies = db.create_table("movies", {"title": "str", "year": "int", "rating": "float"})
    movies.insert_many([
        {"title": "Sans Soleil", "year": 1983, "rating": 4.4},
        {"title": "Stalker", "year": 1979, "rating": 4.3},
        {"title": "La Jetee", "year": 1962, "rating": 4.2},
    ])

    print("via the API — pre-1980, newest first:")
    for row in movies.select(where=lambda r: r["year"] < 1980, order_by="year", desc=True):
        print(f"  {row['year']}  {row['title']}")

    # --- SQL layer ---
    execute(db, "CREATE TABLE notes (topic str, done bool)")
    execute(db, "INSERT INTO notes VALUES ('join ordering', false)")
    execute(db, "INSERT INTO notes VALUES ('buffer pool', true)")
    execute(db, "INSERT INTO notes VALUES ('vectorized exec', false)")

    print("\nvia SQL — still to read:")
    todo = execute(db, "SELECT topic FROM notes WHERE done = false ORDER BY topic")
    for row in todo:
        print(f"  - {row['topic']}")

    # --- the planner: an index changes the access path ---
    execute(db, "CREATE TABLE people (name str, city str)")
    for name, city in [("Ada", "Lausanne"), ("Bob", "Geneva"), ("Cleo", "Lausanne")]:
        execute(db, f"INSERT INTO people VALUES ('{name}', '{city}')")

    print("\nplanner — before and after an index on city:")
    select_lausanne = "SELECT * FROM people WHERE city = 'Lausanne'"
    count_lausanne = "SELECT COUNT(*) FROM people WHERE city = 'Lausanne'"

    print(f"  {execute(db, 'EXPLAIN ' + select_lausanne)}")
    execute(db, "CREATE INDEX ON people (city)")
    print(f"  {execute(db, 'EXPLAIN ' + select_lausanne)}")
    print(f"  count in Lausanne: {execute(db, count_lausanne)[0]['count']}")

    # --- update, with the index kept in sync ---
    execute(db, "UPDATE people SET city = 'Bern' WHERE name = 'Ada'")
    print(f"  after moving Ada to Bern, Lausanne now has "
          f"{execute(db, count_lausanne)[0]['count']}")


if __name__ == "__main__":
    main()
