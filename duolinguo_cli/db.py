"""SQLite 存储层：建表与 CRUD。

不做 schema 迁移：个人工具，结构变更直接删库重建（~/.duolinguo/learning.db）。
日期一律存 ISO 字符串（YYYY-MM-DD），字符串比较即时间比较。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from . import config

DDL = """
CREATE TABLE IF NOT EXISTS books (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    slug        TEXT NOT NULL UNIQUE,
    source      TEXT NOT NULL DEFAULT 'builtin',
    description TEXT NOT NULL DEFAULT '',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS words (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id  INTEGER NOT NULL REFERENCES books(id),
    word     TEXT NOT NULL,
    phonetic TEXT NOT NULL DEFAULT '',
    meaning  TEXT NOT NULL,
    example  TEXT NOT NULL DEFAULT '',
    unit     INTEGER NOT NULL DEFAULT 1,
    UNIQUE(book_id, word)
);

CREATE TABLE IF NOT EXISTS word_progress (
    word_id          INTEGER PRIMARY KEY REFERENCES words(id),
    status           TEXT NOT NULL DEFAULT 'new',
    ease             REAL NOT NULL DEFAULT 2.5,
    interval_days    INTEGER NOT NULL DEFAULT 0,
    reps             INTEGER NOT NULL DEFAULT 0,
    lapses           INTEGER NOT NULL DEFAULT 0,
    due_at           TEXT NOT NULL DEFAULT '',
    last_reviewed_at TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS review_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word_id     INTEGER NOT NULL REFERENCES words(id),
    reviewed_at TEXT NOT NULL,
    qtype       TEXT NOT NULL,
    correct     INTEGER NOT NULL,
    response    TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS daily_stats (
    date         TEXT PRIMARY KEY,
    new_learned  INTEGER NOT NULL DEFAULT 0,
    reviews_done INTEGER NOT NULL DEFAULT 0,
    correct      INTEGER NOT NULL DEFAULT 0,
    answered     INTEGER NOT NULL DEFAULT 0,
    xp_earned    INTEGER NOT NULL DEFAULT 0,
    goal_met     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def now_str() -> str:
    """当前时间，格式 YYYY-MM-DD HH:MM:SS。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def today_str() -> str:
    """今天日期，格式 YYYY-MM-DD。"""
    return datetime.now().strftime("%Y-%m-%d")


def get_conn(db_file: Path | None = None) -> sqlite3.Connection:
    """打开数据库连接（自动建目录、启用外键与 Row 工厂）。"""
    path = Path(db_file) if db_file else config.DB_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    """建表（幂等）。"""
    conn.executescript(DDL)
    conn.commit()


# ---------------------------------------------------------------- 词书 / 单词


def get_book(conn: sqlite3.Connection, slug: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM books WHERE slug = ?", (slug,)).fetchone()


def list_books(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """所有词书，附带词数与已学（status != new）词数。"""
    return conn.execute(
        """
        SELECT b.*,
               COUNT(w.id) AS word_count,
               SUM(CASE WHEN p.status IS NOT NULL AND p.status != 'new' THEN 1 ELSE 0 END)
                   AS learned_count
        FROM books b
        LEFT JOIN words w ON w.book_id = b.id
        LEFT JOIN word_progress p ON p.word_id = w.id
        GROUP BY b.id
        ORDER BY b.id
        """
    ).fetchall()


def insert_book(
    conn: sqlite3.Connection,
    name: str,
    slug: str,
    source: str = "builtin",
    description: str = "",
) -> int:
    """插入词书；slug 已存在时返回既有 id（幂等）。"""
    row = get_book(conn, slug)
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO books (name, slug, source, description, created_at) VALUES (?, ?, ?, ?, ?)",
        (name, slug, source, description, now_str()),
    )
    return cur.lastrowid


def insert_words(
    conn: sqlite3.Connection,
    book_id: int,
    entries: list[dict],
    unit_size: int = config.UNIT_SIZE,
) -> int:
    """批量插入单词（忽略重复），返回新增条数。unit 按每 unit_size 词一关自动切分。"""
    added = 0
    for i, e in enumerate(entries):
        unit = i // unit_size + 1
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO words (book_id, word, phonetic, meaning, example, unit)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (book_id, e["word"], e.get("phonetic", ""), e["meaning"], e.get("example", ""), unit),
        )
        added += cur.rowcount
    return added


def get_word(conn: sqlite3.Connection, word_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM words WHERE id = ?", (word_id,)).fetchone()


def fetch_new(conn: sqlite3.Connection, book_id: int, limit: int) -> list[sqlite3.Row]:
    """未学过的词，按 (unit, id) 升序（顺着关卡推进）。"""
    return conn.execute(
        """
        SELECT w.* FROM words w
        LEFT JOIN word_progress p ON p.word_id = w.id
        WHERE w.book_id = ? AND p.word_id IS NULL
        ORDER BY w.unit, w.id
        LIMIT ?
        """,
        (book_id, limit),
    ).fetchall()


def fetch_due(conn: sqlite3.Connection, book_id: int, today: str, limit: int) -> list[sqlite3.Row]:
    """已学过且到期（due_at <= today）的词，按到期日升序。"""
    return conn.execute(
        """
        SELECT w.* FROM words w
        JOIN word_progress p ON p.word_id = w.id
        WHERE w.book_id = ? AND p.status != 'new' AND p.due_at <= ?
        ORDER BY p.due_at, w.id
        LIMIT ?
        """,
        (book_id, today, limit),
    ).fetchall()


# ---------------------------------------------------------------- 单词进度


def get_progress(conn: sqlite3.Connection, word_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM word_progress WHERE word_id = ?", (word_id,)
    ).fetchone()


def upsert_progress(
    conn: sqlite3.Connection,
    word_id: int,
    status: str,
    ease: float,
    interval_days: int,
    reps: int,
    lapses: int,
    due_at: str,
    last_reviewed_at: str,
) -> None:
    conn.execute(
        """
        INSERT INTO word_progress
            (word_id, status, ease, interval_days, reps, lapses, due_at, last_reviewed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(word_id) DO UPDATE SET
            status = excluded.status,
            ease = excluded.ease,
            interval_days = excluded.interval_days,
            reps = excluded.reps,
            lapses = excluded.lapses,
            due_at = excluded.due_at,
            last_reviewed_at = excluded.last_reviewed_at
        """,
        (word_id, status, ease, interval_days, reps, lapses, due_at, last_reviewed_at),
    )


def add_review_log(
    conn: sqlite3.Connection,
    word_id: int,
    reviewed_at: str,
    qtype: str,
    correct: bool,
    response: str = "",
) -> None:
    conn.execute(
        "INSERT INTO review_log (word_id, reviewed_at, qtype, correct, response) "
        "VALUES (?, ?, ?, ?, ?)",
        (word_id, reviewed_at, qtype, 1 if correct else 0, response),
    )


# ---------------------------------------------------------------- 每日统计


def bump_daily(conn: sqlite3.Connection, date: str, **counters: int) -> None:
    """累加某日统计（键：new_learned/reviews_done/correct/answered/xp_earned）。"""
    conn.execute("INSERT OR IGNORE INTO daily_stats (date) VALUES (?)", (date,))
    sets = ", ".join(f"{k} = {k} + ?" for k in counters)
    if sets:
        conn.execute(f"UPDATE daily_stats SET {sets} WHERE date = ?", (*counters.values(), date))


def get_daily(conn: sqlite3.Connection, date: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM daily_stats WHERE date = ?", (date,)).fetchone()


def set_goal_met(conn: sqlite3.Connection, date: str) -> None:
    conn.execute("INSERT OR IGNORE INTO daily_stats (date) VALUES (?)", (date,))
    conn.execute("UPDATE daily_stats SET goal_met = 1 WHERE date = ?", (date,))


def met_dates(conn: sqlite3.Connection) -> set[str]:
    """所有已达成目标的日期集合。"""
    rows = conn.execute("SELECT date FROM daily_stats WHERE goal_met = 1").fetchall()
    return {r["date"] for r in rows}


def total_xp(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COALESCE(SUM(xp_earned), 0) AS xp FROM daily_stats").fetchone()
    return row["xp"]


# ---------------------------------------------------------------- 设置


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


# 可修改的配置项
CONFIG_KEYS = ("daily_goal", "current_book")


def apply_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    """校验并保存设置（含提交）；非法值抛 ValueError（中文说明）。

    注意：current_book 校验只查库，调用方如需内置词书请先 ensure_builtins。
    """
    if key not in CONFIG_KEYS:
        raise ValueError(f"未知配置项：{key}（可选：{', '.join(CONFIG_KEYS)}）")
    if key == "daily_goal":
        if not value.isdigit() or int(value) < 1:
            raise ValueError("daily_goal 必须是正整数")
    else:  # current_book
        if not get_book(conn, value):
            raise ValueError(f"词书不存在：{value}")
    set_setting(conn, key, value)
    conn.commit()
