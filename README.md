# petit-db

A tiny toy database, written in pure Python with no dependencies. It's a place
to poke at the ideas behind database internals — an append-only log, a little
query parser, type-checked rows — without any of the weight of a real engine.

Not meant for anything serious. Meant for reading and tinkering.

## What's in it

- **Storage** is an append-only JSONL log per table. Inserts, updates and
  deletes are appended as operations; replaying the log rebuilds the live rows.
  A `compact()` rewrites the log without the dead rows. (`petitdb/storage.py`)
- **The engine** is a `Database` of `Table`s, each a dict of rows with a typed
  schema. Tables can carry hash indexes. (`petitdb/database.py`)
- **A structured WHERE** — a conjunction of comparisons rather than an opaque
  lambda, so the planner can look inside it. (`petitdb/predicate.py`)
- **A tiny planner** — a `SELECT` with an equality filter on an indexed column
  uses the index; everything else is a sequential scan. `EXPLAIN` shows which.
- **A small SQL front end** over all of it — `CREATE TABLE`, `CREATE INDEX`,
  `INSERT`, `SELECT … WHERE … ORDER BY … LIMIT`, `COUNT(*)`, `UPDATE`, `DELETE`,
  `EXPLAIN`, `DROP TABLE`. No joins, on purpose. (`petitdb/query.py`)

## Python API

```python
from petitdb import Database

db = Database()                      # in-memory; pass a path to persist
people = db.create_table("people", {"name": "str", "age": "int"})
people.insert_many([
    {"name": "Ada", "age": 36},
    {"name": "Grace", "age": 45},
])

people.select(where=lambda r: r["age"] > 40, order_by="age")
# -> [{"name": "Grace", "age": 45}]
```

## SQL

```python
from petitdb import Database, execute

db = Database("./data")              # writes a log under ./data
execute(db, "CREATE TABLE notes (topic str, done bool)")
execute(db, "INSERT INTO notes VALUES ('join ordering', false)")
execute(db, "SELECT topic FROM notes WHERE done = false ORDER BY topic")
# -> [{"topic": "join ordering"}]
```

## Indexes and the planner

A hash index turns an equality filter from a full scan into a bucket lookup.
`EXPLAIN` reports the access path the planner picks:

```python
execute(db, "EXPLAIN SELECT * FROM people WHERE city = 'Lausanne'")
# -> "Seq scan on people"

execute(db, "CREATE INDEX ON people (city)")
execute(db, "EXPLAIN SELECT * FROM people WHERE city = 'Lausanne'")
# -> "Index lookup on people.city"
```

The index is kept in sync through `INSERT`, `UPDATE` and `DELETE`, and it's
rebuilt from the log when a database is reopened. It only helps equality (`=`)
filters — a range like `age > 30` still scans, which is exactly why the next
thing on the list below is a B-tree.

## Shell

```
python -m petitdb            # in-memory
python -m petitdb ./data     # persisted to ./data
```

```
petit> CREATE TABLE t (id int, name str)
petit> INSERT INTO t VALUES (1, 'Ada')
petit> SELECT * FROM t
id  name
--  ----
1   Ada
(1 row)
```

## Running things

```
python examples/demo.py
python -m unittest discover -s tests -v
```

## Maybe later

- a B-tree index, so range queries aren't a full scan either
- cost-based planning once there's more than one index to choose from
- a write-ahead log that's actually crash-safe

MIT licensed.
