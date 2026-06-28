import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from petitdb import Database, PetitDBError, execute  # noqa: E402


class TestApi(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        self.db.create_table("people", {"name": "str", "age": "int"})

    def test_insert_and_select(self):
        t = self.db.table("people")
        t.insert_many([
            {"name": "Ada", "age": 36},
            {"name": "Linus", "age": 54},
            {"name": "Grace", "age": 45},
        ])
        self.assertEqual(len(t), 3)
        rows = t.select(where=lambda r: r["age"] > 40, order_by="age")
        self.assertEqual([r["name"] for r in rows], ["Grace", "Linus"])

    def test_projection_and_limit(self):
        t = self.db.table("people")
        t.insert_many([{"name": n, "age": a} for n, a in [("a", 1), ("b", 2), ("c", 3)]])
        rows = t.select(columns=["name"], order_by="age", desc=True, limit=2)
        self.assertEqual(rows, [{"name": "c"}, {"name": "b"}])

    def test_type_coercion(self):
        t = self.db.table("people")
        rid = t.insert({"name": "x", "age": "29"})  # str -> int
        self.assertEqual(t.select()[0]["age"], 29)
        self.assertIsInstance(rid, int)

    def test_bad_column_and_type(self):
        t = self.db.table("people")
        with self.assertRaises(PetitDBError):
            t.insert({"name": "x", "age": "not-a-number"})
        with self.assertRaises(PetitDBError):
            t.insert({"name": "x", "age": 1, "extra": True})

    def test_delete(self):
        t = self.db.table("people")
        t.insert_many([{"name": "a", "age": 1}, {"name": "b", "age": 2}])
        self.assertEqual(t.delete(where=lambda r: r["age"] == 1), 1)
        self.assertEqual(len(t), 1)


class TestSql(unittest.TestCase):
    def setUp(self):
        self.db = Database()

    def test_round_trip(self):
        execute(self.db, "CREATE TABLE t (id int, name str, vip bool)")
        execute(self.db, "INSERT INTO t (id, name, vip) VALUES (1, 'Ada', true)")
        execute(self.db, "INSERT INTO t VALUES (2, 'Bob', false)")
        execute(self.db, "INSERT INTO t VALUES (3, 'Cleo', true)")
        rows = execute(self.db, "SELECT name FROM t WHERE vip = true ORDER BY name DESC")
        self.assertEqual(rows, [{"name": "Cleo"}, {"name": "Ada"}])

    def test_where_and_limit(self):
        execute(self.db, "CREATE TABLE n (x int)")
        for i in range(5):
            execute(self.db, f"INSERT INTO n VALUES ({i})")
        rows = execute(self.db, "SELECT x FROM n WHERE x >= 2 AND x < 4 ORDER BY x")
        self.assertEqual([r["x"] for r in rows], [2, 3])
        self.assertEqual(execute(self.db, "SELECT * FROM n LIMIT 1"), [{"x": 0}])

    def test_quoted_string_with_escape(self):
        execute(self.db, "CREATE TABLE q (s str)")
        execute(self.db, "INSERT INTO q VALUES ('it''s fine')")
        self.assertEqual(execute(self.db, "SELECT s FROM q"), [{"s": "it's fine"}])

    def test_delete_and_drop(self):
        execute(self.db, "CREATE TABLE t (x int)")
        execute(self.db, "INSERT INTO t VALUES (1)")
        execute(self.db, "INSERT INTO t VALUES (2)")
        self.assertEqual(execute(self.db, "DELETE FROM t WHERE x = 1"), 1)
        execute(self.db, "DROP TABLE t")
        self.assertNotIn("t", self.db)

    def test_parse_errors(self):
        with self.assertRaises(PetitDBError):
            execute(self.db, "SELEKT * FROM nope")


class TestPersistence(unittest.TestCase):
    def test_log_survives_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(d)
            execute(db, "CREATE TABLE t (id int, name str)")
            execute(db, "INSERT INTO t VALUES (1, 'Ada')")
            execute(db, "INSERT INTO t VALUES (2, 'Bob')")
            execute(db, "DELETE FROM t WHERE id = 1")

            reopened = Database(d)
            rows = execute(reopened, "SELECT id, name FROM t")
            self.assertEqual(rows, [{"id": 2, "name": "Bob"}])

            # ids keep climbing after reload (no reuse of deleted id)
            new_id = execute(reopened, "INSERT INTO t VALUES (9, 'Cleo')")
            self.assertEqual(new_id, 3)

    def test_compaction_preserves_rows(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(d)
            db.create_table("t", {"x": "int"})
            t = db.table("t")
            t.insert_many([{"x": i} for i in range(10)])
            t.delete(where=lambda r: r["x"] % 2 == 0)
            t.compact()

            reopened = Database(d)
            xs = sorted(r["x"] for r in reopened.table("t").select())
            self.assertEqual(xs, [1, 3, 5, 7, 9])


if __name__ == "__main__":
    unittest.main()
