"""Local SQLite history of dictations.

Failed dictations (no network, bad key, API outage) are stored with status
"failed" and the path of the saved recording so they can be retried later.
"""
import sqlite3
import threading
import time

_COLUMNS = {"audio_path": "TEXT", "error": "TEXT"}  # added after FlowLite's original schema


class History:
    def __init__(self, path: str):
        self._lock = threading.Lock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS history (
            id INTEGER PRIMARY KEY,
            ts REAL NOT NULL,
            app TEXT,
            window_title TEXT,
            raw_text TEXT,
            final_text TEXT,
            status TEXT,
            audio_ms INTEGER,
            asr_ms INTEGER,
            llm_ms INTEGER
        )""")
        have = {r["name"] for r in self.db.execute("PRAGMA table_info(history)")}
        for col, typ in _COLUMNS.items():
            if col not in have:
                self.db.execute(f"ALTER TABLE history ADD COLUMN {col} {typ}")
        self.db.commit()

    def add(self, **row) -> int:
        row.setdefault("ts", time.time())
        cols = ",".join(row)
        with self._lock:
            cur = self.db.execute(f"INSERT INTO history ({cols}) VALUES ({','.join('?' * len(row))})", tuple(row.values()))
            self.db.commit()
            return cur.lastrowid

    def update(self, row_id: int, **fields) -> None:
        sets = ",".join(f"{k}=?" for k in fields)
        with self._lock:
            self.db.execute(f"UPDATE history SET {sets} WHERE id=?", (*fields.values(), row_id))
            self.db.commit()

    def get(self, row_id: int) -> dict | None:
        with self._lock:
            r = self.db.execute("SELECT * FROM history WHERE id=?", (row_id,)).fetchone()
        return dict(r) if r else None

    def recent(self, query: str = "", limit: int = 300) -> list[dict]:
        sql = "SELECT * FROM history"
        args: tuple = ()
        if query:
            esc = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " WHERE final_text LIKE ? ESCAPE '\\' OR raw_text LIKE ? ESCAPE '\\' OR app LIKE ? ESCAPE '\\'"
            args = (f"%{esc}%",) * 3
        sql += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            return [dict(r) for r in self.db.execute(sql, (*args, limit))]

    def stats(self) -> tuple[int, int]:
        """(number of dictations, total words) across everything transcribed."""
        with self._lock:
            rows = self.db.execute("SELECT final_text FROM history WHERE final_text != ''").fetchall()
        return len(rows), sum(len(r[0].split()) for r in rows)

    def last_text(self) -> str | None:
        with self._lock:
            r = self.db.execute("SELECT final_text FROM history WHERE final_text != '' "
                                "AND status != 'failed' ORDER BY id DESC LIMIT 1").fetchone()
        return r[0] if r else None
