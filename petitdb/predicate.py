"""A structured representation of a WHERE clause.

Instead of compiling WHERE straight into an opaque lambda, we keep it as a
conjunction of comparisons. That little bit of structure is what lets the
planner peek inside and notice "oh, there's an equality on an indexed column,
I can use the index" instead of always scanning every row.
"""

import operator

CMP = {
    "=": operator.eq, "==": operator.eq,
    "!=": operator.ne, "<>": operator.ne,
    "<": operator.lt, "<=": operator.le,
    ">": operator.gt, ">=": operator.ge,
}

EQUALITY = ("=", "==")


class Comparison:
    __slots__ = ("col", "op", "value")

    def __init__(self, col, op, value):
        self.col = col
        self.op = op
        self.value = value

    def matches(self, row):
        return self.col in row and CMP[self.op](row[self.col], self.value)


class Where:
    """A conjunction (AND) of comparisons."""

    __slots__ = ("conds",)

    def __init__(self, conds):
        self.conds = list(conds)

    def matches(self, row):
        return all(c.matches(row) for c in self.conds)

    def equality_on(self, columns):
        """First `col = value` comparison whose column is in `columns`, else None."""
        for c in self.conds:
            if c.op in EQUALITY and c.col in columns:
                return c.col, c.value
        return None


def evaluator(where):
    """A function(row) -> bool for any accepted `where`: None, a Where, or a
    plain callable (the Python API still lets you pass your own predicate)."""
    if where is None:
        return lambda row: True
    if isinstance(where, Where):
        return where.matches
    return where
