"""The core engine: a Database holds Tables, a Table holds rows.

Everything here is plain in-memory Python dicts. If the Database is given a
directory path, each table also writes its schema and an append-only log so
state survives a restart (see storage.py).

Tables can carry hash indexes on a column. A select with an equality filter on
an indexed column uses the index instead of scanning every row; `explain()`
shows which path the planner picked.
"""

import json
import os

from .predicate import Where, evaluator
from .storage import LogStore

TYPES = {"int": int, "float": float, "str": str, "bool": bool}


class PetitDBError(Exception):
    pass


class HashIndex:
    """value -> set of row ids. Equality lookups only -- a real engine would
    reach for a B-tree once range queries mattered."""

    def __init__(self, column):
        self.column = column
        self.buckets = {}

    def add(self, rid, row):
        self.buckets.setdefault(row[self.column], set()).add(rid)

    def remove(self, rid, row):
        bucket = self.buckets.get(row[self.column])
        if bucket is not None:
            bucket.discard(rid)
            if not bucket:
                del self.buckets[row[self.column]]

    def lookup(self, value):
        return self.buckets.get(value, ())


class Table:
    def __init__(self, name, schema, store=None):
        self.name = name
        self.schema = schema          # {column: type_name}
        self.store = store            # LogStore or None (in-memory only)
        self._rows = {}               # id -> row dict
        self._next_id = 1
        self.indexes = {}             # column -> HashIndex
        if store is not None:
            self._rows = store.replay()
            if self._rows:
                self._next_id = max(self._rows) + 1

    # -- type checking --
    def _coerce_value(self, col, val):
        typ = self.schema[col]
        py = TYPES[typ]
        try:
            if py is bool and isinstance(val, str):
                return {"true": True, "false": False}[val.lower()]
            return py(val)
        except (ValueError, KeyError):
            raise PetitDBError(f"cannot store {val!r} as {typ} in {self.name}.{col}")

    def _coerce(self, row):
        missing = set(self.schema) - set(row)
        if missing:
            raise PetitDBError(f"missing column(s) {sorted(missing)} for table {self.name!r}")
        extra = set(row) - set(self.schema)
        if extra:
            raise PetitDBError(f"unknown column(s) {sorted(extra)} for table {self.name!r}")
        return {col: self._coerce_value(col, row[col]) for col in self.schema}

    # -- indexes --
    def add_index(self, column):
        if column not in self.schema:
            raise PetitDBError(f"cannot index unknown column {column!r} on {self.name!r}")
        if column not in self.indexes:
            idx = HashIndex(column)
            for rid, row in self._rows.items():
                idx.add(rid, row)
            self.indexes[column] = idx
        return self.indexes[column]

    # -- writes --
    def insert(self, row):
        clean = self._coerce(row)
        rid = self._next_id
        self._next_id += 1
        self._rows[rid] = clean
        for idx in self.indexes.values():
            idx.add(rid, clean)
        if self.store is not None:
            self.store.append({"op": "insert", "id": rid, "row": clean})
        return rid

    def insert_many(self, rows):
        return [self.insert(r) for r in rows]

    def update(self, changes, where=None):
        """Set `changes` (a {col: value} dict) on every matching row. Returns
        the number of rows changed."""
        if not changes:
            return 0
        unknown = set(changes) - set(self.schema)
        if unknown:
            raise PetitDBError(f"unknown column(s) {sorted(unknown)} for table {self.name!r}")
        coerced = {c: self._coerce_value(c, v) for c, v in changes.items()}
        pred = evaluator(where)
        targets = [rid for rid, row in self._rows.items() if pred(row)]
        for rid in targets:
            old = self._rows[rid]
            new = dict(old)
            new.update(coerced)
            for idx in self.indexes.values():
                idx.remove(rid, old)
                idx.add(rid, new)
            self._rows[rid] = new
            if self.store is not None:
                self.store.append({"op": "update", "id": rid, "row": new})
        return len(targets)

    def delete(self, where=None):
        pred = evaluator(where)
        victims = [rid for rid, row in self._rows.items() if pred(row)]
        for rid in victims:
            row = self._rows.pop(rid)
            for idx in self.indexes.values():
                idx.remove(rid, row)
            if self.store is not None:
                self.store.append({"op": "delete", "id": rid})
        return len(victims)

    # -- reads --
    def _candidate_ids(self, where):
        """Ids the planner thinks are worth looking at, or None to mean
        'scan everything'."""
        if isinstance(where, Where) and self.indexes:
            hit = where.equality_on(self.indexes)
            if hit is not None:
                col, value = hit
                return list(self.indexes[col].lookup(value))
        return None

    def _scan(self, where):
        pred = evaluator(where)
        ids = self._candidate_ids(where)
        if ids is None:
            return [row for row in self._rows.values() if pred(row)]
        return [self._rows[i] for i in ids if pred(self._rows[i])]

    def select(self, columns=None, where=None, order_by=None, desc=False, limit=None):
        cols = list(self.schema) if columns is None else columns
        for c in cols:
            if c not in self.schema:
                raise PetitDBError(f"unknown column {c!r} in select on {self.name!r}")
        result = self._scan(where)
        if order_by is not None:
            if order_by not in self.schema:
                raise PetitDBError(f"unknown column {order_by!r} in order by")
            result.sort(key=lambda r: r[order_by], reverse=desc)
        if limit is not None:
            result = result[:limit]
        return [{c: row[c] for c in cols} for row in result]

    def count(self, where=None):
        return len(self._scan(where))

    def explain(self, where=None):
        """A one-line description of the access path the planner would use."""
        if isinstance(where, Where) and self.indexes:
            hit = where.equality_on(self.indexes)
            if hit is not None:
                return f"Index lookup on {self.name}.{hit[0]}"
        return f"Seq scan on {self.name}"

    def compact(self):
        """Drop dead rows from the on-disk log."""
        if self.store is not None:
            self.store.rewrite(self._rows)

    def __len__(self):
        return len(self._rows)


class Database:
    def __init__(self, path=None):
        self.path = path
        self.tables = {}
        if path is not None:
            os.makedirs(path, exist_ok=True)
            self._load_existing()

    # -- paths --
    def _schema_path(self, name):
        return os.path.join(self.path, f"{name}.schema.json")

    def _log_path(self, name):
        return os.path.join(self.path, f"{name}.log")

    def _meta_path(self, name):
        return os.path.join(self.path, f"{name}.meta.json")

    def _save_meta(self, table):
        if self.path is not None:
            with open(self._meta_path(table.name), "w", encoding="utf-8") as f:
                json.dump({"indexes": sorted(table.indexes)}, f, indent=2)

    def _load_existing(self):
        for fn in sorted(os.listdir(self.path)):
            if fn.endswith(".schema.json"):
                name = fn[: -len(".schema.json")]
                with open(os.path.join(self.path, fn), encoding="utf-8") as f:
                    schema = json.load(f)
                table = Table(name, schema, LogStore(self._log_path(name)))
                self.tables[name] = table
                meta_path = self._meta_path(name)
                if os.path.exists(meta_path):
                    with open(meta_path, encoding="utf-8") as f:
                        meta = json.load(f)
                    for col in meta.get("indexes", []):
                        table.add_index(col)

    # -- schema ops --
    def create_table(self, name, schema):
        if name in self.tables:
            raise PetitDBError(f"table {name!r} already exists")
        for col, typ in schema.items():
            if typ not in TYPES:
                raise PetitDBError(f"unknown type {typ!r} for column {col!r}")
        store = None
        if self.path is not None:
            with open(self._schema_path(name), "w", encoding="utf-8") as f:
                json.dump(schema, f, indent=2)
            store = LogStore(self._log_path(name))
        table = Table(name, schema, store)
        self.tables[name] = table
        return table

    def create_index(self, table_name, column):
        table = self.table(table_name)
        table.add_index(column)
        self._save_meta(table)

    def table(self, name):
        if name not in self.tables:
            raise PetitDBError(f"no such table {name!r}")
        return self.tables[name]

    def drop_table(self, name):
        self.table(name)  # existence check
        del self.tables[name]
        if self.path is not None:
            for p in (self._schema_path(name), self._log_path(name), self._meta_path(name)):
                if os.path.exists(p):
                    os.remove(p)

    def __contains__(self, name):
        return name in self.tables
