import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "island.db"

# 模拟额度数据：(key, 名称, 已用百分比, 重置说明)
MOCK_QUOTAS = [
    ("claude", "Claude", 62, "2h14m 后重置"),
    ("codex", "Codex", 35, "4h 后重置"),
]


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with conn() as c:
        c.execute("CREATE TABLE IF NOT EXISTS quota (key TEXT PRIMARY KEY, name TEXT, used INTEGER, reset TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS liked (title TEXT, artist TEXT, PRIMARY KEY (title, artist))")
        c.executemany("INSERT OR IGNORE INTO quota VALUES (?,?,?,?)", MOCK_QUOTAS)
        c.execute("DELETE FROM quota WHERE key='muse'")
        c.execute("CREATE TABLE IF NOT EXISTS setting (key TEXT PRIMARY KEY, value TEXT)")


def get_setting(key):
    with conn() as c:
        r = c.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
        return r["value"] if r else None


def set_setting(key, value):
    with conn() as c:
        c.execute("INSERT OR REPLACE INTO setting VALUES (?,?)", (key, str(value)))


def quotas():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM quota")]


def is_liked(title, artist):
    with conn() as c:
        return c.execute("SELECT 1 FROM liked WHERE title=? AND artist=?", (title, artist)).fetchone() is not None


def toggle_like(title, artist):
    with conn() as c:
        if is_liked(title, artist):
            c.execute("DELETE FROM liked WHERE title=? AND artist=?", (title, artist))
            return False
        c.execute("INSERT INTO liked VALUES (?,?)", (title, artist))
        return True
