# petit-db

A tiny toy database, written in pure Python with no dependencies. It's a place
to poke at the ideas behind database internals — an append-only log, a little
query parser, type-checked rows — without any of the weight of a real engine.

Not meant for anything serious. Meant for reading and tinkering.

## What's in it

- **Storage** is an append-only JSONL log per table. Inserts and deletes are
  appended as operations; replaying the log rebuilds the live rows. A
  `compact()` rewrites the log without the dead rows. (`petitdb/storage.py`)
- **The engine** is a `Database` of `Table`s, each a dict of rows with a typed
  schema. (`petitdb/database.py`)
- **A small SQL front end** over the same engine — `CREATE TABLE`, `INSERT`,
  `SELECT … WHERE … ORDER BY … LIMIT`, `DELETE`, `DROP TABLE`. No joins, no
  aggregates, on purpose. (`petitdb/query.py`)

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

- a real WHERE planner instead of a chain of predicates
- a B-tree index on a column, so lookups aren't a full scan
- a write-ahead log that's actually crash-safe

MIT licensed.
