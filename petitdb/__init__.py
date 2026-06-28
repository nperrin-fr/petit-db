"""petit-db — a tiny toy database, for poking at database internals."""

from .database import Database, HashIndex, PetitDBError, Table
from .predicate import Comparison, Where
from .query import execute

__all__ = [
    "Database", "Table", "HashIndex", "PetitDBError",
    "Comparison", "Where", "execute",
]
__version__ = "0.2.0"
