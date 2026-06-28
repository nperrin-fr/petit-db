"""petit-db — a tiny toy database, for poking at database internals."""

from .database import Database, PetitDBError, Table
from .query import execute

__all__ = ["Database", "Table", "PetitDBError", "execute"]
__version__ = "0.1.0"
