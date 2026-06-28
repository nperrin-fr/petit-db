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


class TestUpdate(unittest.TestCase):
    def test_update_api(self):
        db = Database()
        t = db.create_table("p", {"name": "str", "age": "int"})
        t.insert_many([{"name": "a", "age": 1}, {"name": "b", "age": 2}])
        changed = t.update({"age": 9}, where=lambda r: r["name"] == "a")
        self.assertEqual(changed, 1)
        self.assertEqual(t.select(where=lambda r: r["name"] == "a")[0]["age"], 9)

    def test_update_sql(self):
        db = Database()
        execute(db, "CREATE TABLE p (name str, age int)")
        execute(db, "INSERT INTO p VALUES ('a', 1)")
        execute(db, "INSERT INTO p VALUES ('b', 2)")
        n = execute(db, "UPDATE p SET age = 99 WHERE name = 'b'")
        self.assertEqual(n, 1)
        rows = execute(db, "SELECT name, age FROM p ORDER BY name")
        self.assertEqual(rows, [{"name": "a", "age": 1}, {"name": "b", "age": 99}])

    def test_update_rejects_unknown_column(self):
        db = Database()
        db.create_table("p", {"name": "str"})
        with self.assertRaises(PetitDBError):
            db.table("p").update({"nope": 1})


class TestCount(unittest.TestCase):
    def test_count_sql(self):
        db = Database()
        execute(db, "CREATE TABLE n (x int)")
        for i in range(5):
            execute(db, f"INSERT INTO n VALUES ({i})")
        self.assertEqual(execute(db, "SELECT COUNT(*) FROM n"), [{"count": 5}])
        self.assertEqual(execute(db, "SELECT COUNT(*) FROM n WHERE x >= 3"), [{"count": 2}])


class TestIndex(unittest.TestCase):
    def setUp(self):
        self.db = Database()
        execute(self.db, "CREATE TABLE people (name str, city str, age int)")
        execute(self.db, "INSERT INTO people VALUES ('Ada', 'Lausanne', 36)")
        execute(self.db, "INSERT INTO people VALUES ('Bob', 'Geneva', 41)")
        execute(self.db, "INSERT INTO people VALUES ('Cleo', 'Lausanne', 29)")

    def test_explain_switches_path(self):
        plan = execute(self.db, "EXPLAIN SELECT * FROM people WHERE city = 'Lausanne'")
        self.assertEqual(plan, "Seq scan on people")
        execute(self.db, "CREATE INDEX ON people (city)")
        plan = execute(self.db, "EXPLAIN SELECT * FROM people WHERE city = 'Lausanne'")
        self.assertEqual(plan, "Index lookup on people.city")

    def test_index_returns_same_rows_as_scan(self):
        scan = execute(self.db, "SELECT name FROM people WHERE city = 'Lausanne' ORDER BY name")
        execute(self.db, "CREATE INDEX ON people (city)")
        indexed = execute(self.db, "SELECT name FROM people WHERE city = 'Lausanne' ORDER BY name")
        self.assertEqual(indexed, scan)
        self.assertEqual([r["name"] for r in indexed], ["Ada", "Cleo"])

    def test_index_only_for_equality(self):
        execute(self.db, "CREATE INDEX ON people (age)")
        # range query can't use the hash index -> still a seq scan
        plan = execute(self.db, "EXPLAIN SELECT * FROM people WHERE age > 30")
        self.assertEqual(plan, "Seq scan on people")

    def test_index_tracks_writes(self):
        execute(self.db, "CREATE INDEX ON people (city)")
        idx = self.db.table("people").indexes["city"]
        self.assertEqual(len(idx.lookup("Lausanne")), 2)
        execute(self.db, "UPDATE people SET city = 'Bern' WHERE name = 'Ada'")
        self.assertEqual(len(idx.lookup("Lausanne")), 1)
        self.assertEqual(len(idx.lookup("Bern")), 1)
        execute(self.db, "DELETE FROM people WHERE name = 'Cleo'")
        self.assertEqual(idx.lookup("Lausanne"), ())


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

    def test_update_op_survives_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(d)
            execute(db, "CREATE TABLE t (id int, name str)")
            execute(db, "INSERT INTO t VALUES (1, 'Ada')")
            execute(db, "UPDATE t SET name = 'Adele' WHERE id = 1")

            reopened = Database(d)
            self.assertEqual(execute(reopened, "SELECT name FROM t"), [{"name": "Adele"}])

    def test_index_survives_reopen(self):
        with tempfile.TemporaryDirectory() as d:
            db = Database(d)
            execute(db, "CREATE TABLE t (id int, city str)")
            execute(db, "INSERT INTO t VALUES (1, 'Lausanne')")
            execute(db, "CREATE INDEX ON t (city)")

            reopened = Database(d)
            self.assertIn("city", reopened.table("t").indexes)
            plan = execute(reopened, "EXPLAIN SELECT * FROM t WHERE city = 'Lausanne'")
            self.assertEqual(plan, "Index lookup on t.city")

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
