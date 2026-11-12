"""游戏化：XP、连胜、每日目标、关卡（单元）完成。"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from . import config, db
from .quiz import SPELLING


def get_goal(conn: sqlite3.Connection) -> int:
    """每日目标（settings.daily_goal，默认 20）。"""
    raw = db.get_setting(conn, "daily_goal")
    if raw and raw.isdigit() and int(raw) > 0:
        return int(raw)
    return config.DEFAULT_DAILY_GOAL


def xp_for(qtype: str, correct: bool) -> int:
    """单题 XP：选择题对 +5、拼写对 +10、答错 0。"""
    if not correct:
        return 0
    return config.XP_SPELLING_CORRECT if qtype == SPELLING else config.XP_MCQ_CORRECT


def record_answer(
    conn: sqlite3.Connection, date_str: str, *, is_new: bool, correct: bool, xp: int
) -> None:
    """记录一次作答（计入单词数维度与 XP）。"""
    counters: dict[str, int] = {"answered": 1, "xp_earned": xp}
    if correct:
        counters["correct"] = 1
    if is_new:
        counters["new_learned"] = 1
    else:
        counters["reviews_done"] = 1
    db.bump_daily(conn, date_str, **counters)


def record_retry(conn: sqlite3.Connection, date_str: str, *, correct: bool, xp: int) -> None:
    """记录一次错词重练：只计入答题数与 XP，不重复计入单词数（不膨胀目标进度）。"""
    counters: dict[str, int] = {"answered": 1, "xp_earned": xp}
    if correct:
        counters["correct"] = 1
    db.bump_daily(conn, date_str, **counters)


def words_done_today(conn: sqlite3.Connection, date_str: str) -> int:
    """今日已练单词数（新学 + 复习）。"""
    row = db.get_daily(conn, date_str)
    if not row:
        return 0
    return row["new_learned"] + row["reviews_done"]


def check_goal(conn: sqlite3.Connection, date_str: str, goal: int) -> bool:
    """若今日首次达成目标：标记 goal_met 并发放 +20 XP，返回 True。"""
    row = db.get_daily(conn, date_str)
    if not row or row["goal_met"]:
        return False
    if row["new_learned"] + row["reviews_done"] < goal:
        return False
    db.set_goal_met(conn, date_str)
    db.bump_daily(conn, date_str, xp_earned=config.XP_GOAL_BONUS)
    return True


def calc_streak(conn: sqlite3.Connection, today: str) -> int:
    """连续达标天数。今天还没达标则从昨天往回数（当天没做不算断签）。"""
    dates = db.met_dates(conn)
    if not dates:
        return 0
    d = date.fromisoformat(today)
    if today not in dates:
        d -= timedelta(days=1)
    n = 0
    while d.isoformat() in dates:
        n += 1
        d -= timedelta(days=1)
    return n


def current_unit(conn: sqlite3.Connection, book_id: int) -> int:
    """当前关卡：第一个还有未学单词的单元；全部学完则返回最后一关。"""
    row = conn.execute(
        """
        SELECT MIN(w.unit) FROM words w
        LEFT JOIN word_progress p ON p.word_id = w.id
        WHERE w.book_id = ? AND (p.word_id IS NULL OR p.status = 'new')
        """,
        (book_id,),
    ).fetchone()
    if row and row[0]:
        return row[0]
    row = conn.execute(
        "SELECT COALESCE(MAX(unit), 1) FROM words WHERE book_id = ?", (book_id,)
    ).fetchone()
    return row[0]


def unit_completed(conn: sqlite3.Connection, book_id: int, unit: int) -> bool:
    """单元完成条件：单元内所有单词都至少学过一次（status != new）。"""
    row = conn.execute(
        """
        SELECT COUNT(*) FROM words w
        LEFT JOIN word_progress p ON p.word_id = w.id
        WHERE w.book_id = ? AND w.unit = ?
          AND (p.word_id IS NULL OR p.status = 'new')
        """,
        (book_id, unit),
    ).fetchone()
    total = conn.execute(
        "SELECT COUNT(*) FROM words WHERE book_id = ? AND unit = ?", (book_id, unit)
    ).fetchone()
    return total[0] > 0 and row[0] == 0


def award_unit_bonus(conn: sqlite3.Connection, date_str: str, book_id: int, unit: int) -> bool:
    """关卡完成 +30 XP，每关只发一次，返回是否发放。"""
    key = f"unit_bonus:{book_id}:{unit}"
    if db.get_setting(conn, key):
        return False
    db.set_setting(conn, key, date_str)
    db.bump_daily(conn, date_str, xp_earned=config.XP_UNIT_BONUS)
    return True
