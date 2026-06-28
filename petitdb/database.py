"""The core engine: a Database holds Tables, a Table holds rows.

Everything here is plain in-memory Python dicts. If the Database is given a
directory path, each table also writes its schema and an append-only log so
state survives a restart (see storage.py).
"""

import json
import os

from .storage import LogStore

TYPES = {"int": int, "float": float, "str": str, "bool": bool}


class PetitDBError(Exception):
    pass


class Table:
    def __init__(self, name, schema, store=None):
        self.name = name
        self.schema = schema          # {column: type_name}
        self.store = store            # LogStore or None (in-memory only)
        self._rows = {}               # id -> row dict
        self._next_id = 1
        if store is not None:
            self._rows = store.replay()
            if self._rows:
                self._next_id = max(self._rows) + 1

    # -- internal --
    def _coerce(self, row):
        clean = {}
        for col, typ in self.schema.items():
            if col not in row:
                raise PetitDBError(f"missing column {col!r} for table {self.name!r}")
            py = TYPES[typ]
            val = row[col]
            try:
                if py is bool and isinstance(val, str):
                    val = {"true": True, "false": False}[val.lower()]
                else:
                    val = py(val)
            except (ValueError, KeyError):
                raise PetitDBError(f"cannot store {val!r} as {typ} in {self.name}.{col}")
            clean[col] = val
        extra = set(row) - set(self.schema)
        if extra:
            raise PetitDBError(f"unknown column(s) {sorted(extra)} for table {self.name!r}")
        return clean

    # -- writes --
    def insert(self, row):
        clean = self._coerce(row)
        rid = self._next_id
        self._next_id += 1
        self._rows[rid] = clean
        if self.store is not None:
            self.store.append({"op": "insert", "id": rid, "row": clean})
        return rid

    def insert_many(self, rows):
        return [self.insert(r) for r in rows]

    def delete(self, where=None):
        victims = [rid for rid, row in self._rows.items() if where is None or where(row)]
        for rid in victims:
            del self._rows[rid]
            if self.store is not None:
                self.store.append({"op": "delete", "id": rid})
        return len(victims)

    # -- reads --
    def select(self, columns=None, where=None, order_by=None, desc=False, limit=None):
        cols = list(self.schema) if columns is None else columns
        for c in cols:
            if c not in self.schema:
                raise PetitDBError(f"unknown column {c!r} in select on {self.name!r}")
        result = [row for row in self._rows.values() if where is None or where(row)]
        if order_by is not None:
            if order_by not in self.schema:
                raise PetitDBError(f"unknown column {order_by!r} in order by")
            result.sort(key=lambda r: r[order_by], reverse=desc)
        if limit is not None:
            result = result[:limit]
        return [{c: row[c] for c in cols} for row in result]

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

    def _load_existing(self):
        for fn in sorted(os.listdir(self.path)):
            if fn.endswith(".schema.json"):
                name = fn[: -len(".schema.json")]
                with open(os.path.join(self.path, fn), encoding="utf-8") as f:
                    schema = json.load(f)
                self.tables[name] = Table(name, schema, LogStore(self._log_path(name)))

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

    def table(self, name):
        if name not in self.tables:
            raise PetitDBError(f"no such table {name!r}")
        return self.tables[name]

    def drop_table(self, name):
        self.table(name)  # existence check
        del self.tables[name]
        if self.path is not None:
            for p in (self._schema_path(name), self._log_path(name)):
                if os.path.exists(p):
                    os.remove(p)

    def __contains__(self, name):
        return name in self.tables
