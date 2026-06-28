"""A very small SQL-ish front end.

Supported, and not much more:

    CREATE TABLE t (col type, ...)        types: int, float, str, bool
    INSERT INTO t [(cols)] VALUES (...)
    SELECT * | cols FROM t [WHERE ...] [ORDER BY col [ASC|DESC]] [LIMIT n]
    DELETE FROM t [WHERE ...]
    DROP TABLE t

WHERE is a chain of `col <op> literal` joined by AND. Operators: = == != <> < <= > >=.
No joins, no subqueries, no aggregates -- on purpose.
"""

import operator
import re

from .database import PetitDBError

_TOKEN = re.compile(
    r"""
      (?P<str>'(?:[^']|'')*')      # 'quoted string', '' escapes a quote
    | (?P<num>-?\d+\.\d+|-?\d+)    # int or float
    | (?P<op><=|>=|<>|!=|=|<|>)    # comparison operators (longest first)
    | (?P<punc>[(),*])             # structural punctuation
    | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    """,
    re.VERBOSE,
)

_OPS = {
    "=": operator.eq, "==": operator.eq,
    "!=": operator.ne, "<>": operator.ne,
    "<": operator.lt, "<=": operator.le,
    ">": operator.gt, ">=": operator.ge,
}


def tokenize(sql):
    tokens, pos, n = [], 0, len(sql)
    while pos < n:
        if sql[pos].isspace():
            pos += 1
            continue
        m = _TOKEN.match(sql, pos)
        if not m:
            raise PetitDBError(f"cannot parse near: {sql[pos:pos + 20]!r}")
        kind, val = m.lastgroup, m.group()
        if kind == "str":
            val = val[1:-1].replace("''", "'")
        tokens.append((kind, val))
        pos = m.end()
    return tokens


class _Stream:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def next(self):
        tok = self.peek()
        self.i += 1
        return tok

    def at_word(self, word):
        kind, val = self.peek()
        return kind == "word" and val.upper() == word.upper()

    def word(self):
        kind, val = self.next()
        if kind != "word":
            raise PetitDBError(f"expected a name, got {val!r}")
        return val

    def expect_word(self, word):
        if not self.at_word(word):
            raise PetitDBError(f"expected {word!r}, got {self.peek()[1]!r}")
        return self.next()[1]

    def expect_punc(self, p):
        kind, val = self.next()
        if val != p:
            raise PetitDBError(f"expected {p!r}, got {val!r}")


def _literal(s):
    kind, val = s.next()
    if kind == "num":
        return float(val) if "." in val else int(val)
    if kind == "str":
        return val
    if kind == "word" and val.lower() in ("true", "false"):
        return val.lower() == "true"
    raise PetitDBError(f"expected a literal, got {val!r}")


def _comparison(s):
    col = s.word()
    okind, opv = s.next()
    if okind != "op":
        raise PetitDBError(f"expected a comparison operator, got {opv!r}")
    rhs = _literal(s)
    fn = _OPS[opv]
    return lambda row: col in row and fn(row[col], rhs)


def _condition(s):
    preds = [_comparison(s)]
    while s.at_word("AND"):
        s.next()
        preds.append(_comparison(s))
    return lambda row: all(p(row) for p in preds)


def _select(db, s):
    if s.peek() == ("punc", "*"):
        s.next()
        cols = None
    else:
        cols = [s.word()]
        while s.peek() == ("punc", ","):
            s.next()
            cols.append(s.word())
    s.expect_word("FROM")
    name = s.word()
    where = order_by = limit = None
    desc = False
    if s.at_word("WHERE"):
        s.next()
        where = _condition(s)
    if s.at_word("ORDER"):
        s.next()
        s.expect_word("BY")
        order_by = s.word()
        if s.at_word("ASC"):
            s.next()
        elif s.at_word("DESC"):
            s.next()
            desc = True
    if s.at_word("LIMIT"):
        s.next()
        kind, val = s.next()
        if kind != "num":
            raise PetitDBError(f"expected a number after LIMIT, got {val!r}")
        limit = int(val)
    return db.table(name).select(cols, where, order_by, desc, limit)


def _create(db, s):
    s.expect_word("TABLE")
    name = s.word()
    s.expect_punc("(")
    schema = {}
    while True:
        col = s.word()
        typ = s.word()
        schema[col] = typ
        _, val = s.next()
        if val == ",":
            continue
        if val == ")":
            break
        raise PetitDBError(f"expected ',' or ')', got {val!r}")
    db.create_table(name, schema)


def _insert(db, s):
    s.expect_word("INTO")
    name = s.word()
    cols = None
    if s.peek() == ("punc", "("):
        s.next()
        cols = [s.word()]
        while s.peek() == ("punc", ","):
            s.next()
            cols.append(s.word())
        s.expect_punc(")")
    s.expect_word("VALUES")
    s.expect_punc("(")
    vals = [_literal(s)]
    while s.peek() == ("punc", ","):
        s.next()
        vals.append(_literal(s))
    s.expect_punc(")")
    table = db.table(name)
    if cols is None:
        cols = list(table.schema)
    if len(cols) != len(vals):
        raise PetitDBError(f"{len(cols)} columns but {len(vals)} values")
    return table.insert(dict(zip(cols, vals)))


def _delete(db, s):
    s.expect_word("FROM")
    name = s.word()
    where = None
    if s.at_word("WHERE"):
        s.next()
        where = _condition(s)
    return db.table(name).delete(where)


def _drop(db, s):
    s.expect_word("TABLE")
    db.drop_table(s.word())


_DISPATCH = {
    "CREATE": _create,
    "INSERT": _insert,
    "SELECT": _select,
    "DELETE": _delete,
    "DROP": _drop,
}


def execute(db, sql):
    """Run one statement. SELECT returns a list of row dicts; INSERT returns the
    new row id; DELETE returns a count; the rest return None."""
    sql = sql.strip().rstrip(";").strip()
    if not sql:
        return None
    s = _Stream(tokenize(sql))
    kind, head = s.next()
    if kind != "word" or head.upper() not in _DISPATCH:
        raise PetitDBError(f"unsupported statement: {head!r}")
    return _DISPATCH[head.upper()](db, s)
