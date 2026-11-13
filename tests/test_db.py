"""存储层测试。"""

from __future__ import annotations

import pytest

from duolinguo_cli import config, db


def test_init_db_idempotent(conn):
    db.init_db(conn)
    db.init_db(conn)
    tables = {
        r["name"]
        for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"books", "words", "word_progress", "review_log", "daily_stats", "settings"} <= tables


def test_insert_book_idempotent(conn):
    id1 = db.insert_book(conn, "词书A", "book_a")
    id2 = db.insert_book(conn, "词书A改名", "book_a")
    assert id1 == id2
    assert db.get_book(conn, "book_a")["name"] == "词书A"


def test_insert_words_counts_and_units(conn, sample_book):
    # 重复插入被忽略
    added = db.insert_words(
        conn, sample_book["id"], [{"word": "word01", "meaning": "释义1"}], unit_size=4
    )
    assert added == 0
    total = conn.execute("SELECT COUNT(*) c FROM words").fetchone()["c"]
    assert total == 8
    units = {
        r["unit"] for r in conn.execute("SELECT DISTINCT unit FROM words").fetchall()
    }
    assert units == {1, 2}


def test_fetch_new_order_and_limit(conn, sample_book):
    rows = db.fetch_new(conn, sample_book["id"], 3)
    assert [r["word"] for r in rows] == ["word01", "word02", "word03"]
    # 学过 word01 后它不再出现在新词里
    db.upsert_progress(conn, rows[0]["id"], "learning", 2.5, 1, 1, 0, "2026-11-13", "2026-11-12")
    conn.commit()
    rows2 = db.fetch_new(conn, sample_book["id"], 3)
    assert [r["word"] for r in rows2] == ["word02", "word03", "word04"]


def test_fetch_due(conn, sample_book):
    w1, w2 = db.fetch_new(conn, sample_book["id"], 2)
    # w1 今天到期、w2 明天才到期、都不该出现在 new 之外的查询里若 status=new
    db.upsert_progress(conn, w1["id"], "learning", 2.5, 1, 1, 0, "2026-11-12", "2026-11-11")
    db.upsert_progress(conn, w2["id"], "learning", 2.5, 2, 1, 0, "2026-11-13", "2026-11-11")
    conn.commit()
    due = db.fetch_due(conn, sample_book["id"], "2026-11-12", 10)
    assert [r["word"] for r in due] == ["word01"]
    # 未学的词不算到期
    assert all(r["word"] != "word03" for r in due)


def test_upsert_progress_updates(conn, sample_book):
    w = db.fetch_new(conn, sample_book["id"], 1)[0]
    db.upsert_progress(conn, w["id"], "learning", 2.5, 0, 0, 0, "", "")
    db.upsert_progress(conn, w["id"], "mastered", 2.7, 7, 3, 1, "2026-11-19", "2026-11-12")
    conn.commit()
    p = db.get_progress(conn, w["id"])
    assert p["status"] == "mastered"
    assert p["ease"] == pytest.approx(2.7)
    assert p["lapses"] == 1


def test_daily_stats_accumulate(conn):
    db.bump_daily(conn, "2026-11-12", new_learned=5, answered=5, correct=4, xp_earned=20)
    db.bump_daily(conn, "2026-11-12", reviews_done=3, answered=3, correct=3, xp_earned=15)
    conn.commit()
    row = db.get_daily(conn, "2026-11-12")
    assert row["new_learned"] == 5
    assert row["reviews_done"] == 3
    assert row["answered"] == 8
    assert row["xp_earned"] == 35
    assert row["goal_met"] == 0


def test_met_dates_and_total_xp(conn):
    db.bump_daily(conn, "2026-11-10", xp_earned=30)
    db.set_goal_met(conn, "2026-11-10")
    db.bump_daily(conn, "2026-11-11", xp_earned=10)
    db.set_goal_met(conn, "2026-11-11")
    db.bump_daily(conn, "2026-11-12", xp_earned=5)
    conn.commit()
    assert db.met_dates(conn) == {"2026-11-10", "2026-11-11"}
    assert db.total_xp(conn) == 45


def test_settings_roundtrip(conn):
    assert db.get_setting(conn, "daily_goal") is None
    assert db.get_setting(conn, "daily_goal", "20") == "20"
    db.set_setting(conn, "daily_goal", "30")
    db.set_setting(conn, "daily_goal", "40")
    conn.commit()
    assert db.get_setting(conn, "daily_goal") == "40"


def test_apply_setting_valid(conn, sample_book):
    db.apply_setting(conn, "daily_goal", "30")
    assert db.get_setting(conn, "daily_goal") == "30"
    db.apply_setting(conn, "current_book", "test_book")
    assert db.get_setting(conn, "current_book") == "test_book"


def test_apply_setting_validation(conn):
    with pytest.raises(ValueError, match="正整数"):
        db.apply_setting(conn, "daily_goal", "0")
    with pytest.raises(ValueError, match="正整数"):
        db.apply_setting(conn, "daily_goal", "abc")
    with pytest.raises(ValueError, match="词书不存在"):
        db.apply_setting(conn, "current_book", "nope")
    with pytest.raises(ValueError, match="未知配置项"):
        db.apply_setting(conn, "hacker", "1")
    # 全部被拒绝，无一落库
    assert db.get_setting(conn, "daily_goal") is None
    assert db.get_setting(conn, "current_book") is None


def test_reevaluate_today_goal(conn):
    """目标变更后重算今日达成：提高→清除旧✓；降低→补达标记+奖励。"""
    today = db.today_str()
    # 今天已按旧目标(20)达标
    db.bump_daily(conn, today, new_learned=20, answered=20, correct=16, xp_earned=100)
    db.set_goal_met(conn, today)
    db.bump_daily(conn, today, xp_earned=config.XP_GOAL_BONUS)
    conn.commit()

    # 目标提高到 100：75<100 → 清除达成标记，已发 XP 不追回
    db.reevaluate_today_goal(conn, today, 100)
    row = db.get_daily(conn, today)
    assert row["goal_met"] == 0
    assert row["xp_earned"] == 100 + config.XP_GOAL_BONUS

    # 目标降回 10：20≥10 → 补达标记 + 再发一次奖励
    db.reevaluate_today_goal(conn, today, 10)
    row = db.get_daily(conn, today)
    assert row["goal_met"] == 1
    assert row["xp_earned"] == 100 + 2 * config.XP_GOAL_BONUS

    # 幂等：重复调用不再变化
    db.reevaluate_today_goal(conn, today, 10)
    row = db.get_daily(conn, today)
    assert row["xp_earned"] == 100 + 2 * config.XP_GOAL_BONUS


def test_apply_setting_reevaluates_goal(conn):
    """通过 apply_setting 改 daily_goal 同样触发今日重算。"""
    today = db.today_str()
    db.bump_daily(conn, today, new_learned=20, reviews_done=0, answered=20, correct=15,
                  xp_earned=100)
    db.set_goal_met(conn, today)
    conn.commit()
    db.apply_setting(conn, "daily_goal", "50")  # 提高目标 → 20<50 → 清除
    assert db.get_setting(conn, "daily_goal") == "50"
    assert db.get_daily(conn, today)["goal_met"] == 0
    db.apply_setting(conn, "daily_goal", "15")  # 降低 → 20≥15 → 恢复
    assert db.get_daily(conn, today)["goal_met"] == 1
