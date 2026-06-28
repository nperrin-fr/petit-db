"""Append-only storage for a single table.

Each table is persisted as a JSONL log. Every line is one operation:

    {"op": "insert", "id": <int>, "row": {...}}
    {"op": "delete", "id": <int>}

Replaying the log left-to-right reconstructs the live rows. This is a small
imitation of how log-structured engines work: writes only ever append to the
end of the file, and a periodic compaction rewrites the log without the dead
rows. It's not fast and it's not durable in any serious sense -- it's just
enough to see the shape of the idea.
"""

import json
import os


class LogStore:
    def __init__(self, path):
        self.path = path

    def replay(self):
        """Rebuild the {id: row} map by replaying the whole log."""
        rows = {}
        if not os.path.exists(self.path):
            return rows
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                op = json.loads(line)
                if op["op"] == "insert":
                    rows[op["id"]] = op["row"]
                elif op["op"] == "delete":
                    rows.pop(op["id"], None)
        return rows

    def append(self, op):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(op, ensure_ascii=False) + "\n")

    def rewrite(self, rows):
        """Compaction: replace the log with one fresh insert per live row."""
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for rid, row in rows.items():
                line = {"op": "insert", "id": rid, "row": row}
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)
