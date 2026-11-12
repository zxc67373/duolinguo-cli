"""游戏化测试：XP、目标、连胜、关卡。"""

from __future__ import annotations

from duolinguo_cli import config, db, gamify
from duolinguo_cli.quiz import MCQ_EN2ZH, SPELLING


def test_get_goal_default_and_override(conn):
    assert gamify.get_goal(conn) == config.DEFAULT_DAILY_GOAL
    db.set_setting(conn, "daily_goal", "50")
    assert gamify.get_goal(conn) == 50
    db.set_setting(conn, "daily_goal", "abc")  # 非法值回退默认
    assert gamify.get_goal(conn) == config.DEFAULT_DAILY_GOAL


def test_xp_for():
    assert gamify.xp_for(MCQ_EN2ZH, True) == config.XP_MCQ_CORRECT
    assert gamify.xp_for(SPELLING, True) == config.XP_SPELLING_CORRECT
    assert gamify.xp_for(SPELLING, False) == 0
    assert gamify.xp_for(MCQ_EN2ZH, False) == 0


def test_record_answer_dimensions(conn):
    gamify.record_answer(conn, "2026-11-12", is_new=True, correct=True, xp=5)
    gamify.record_answer(conn, "2026-11-12", is_new=False, correct=False, xp=0)
    conn.commit()
    row = db.get_daily(conn, "2026-11-12")
    assert row["new_learned"] == 1
    assert row["reviews_done"] == 1
    assert row["answered"] == 2
    assert row["correct"] == 1
    assert row["xp_earned"] == 5


def test_record_retry_does_not_inflate_word_counts(conn):
    gamify.record_retry(conn, "2026-11-12", correct=True, xp=10)
    conn.commit()
    row = db.get_daily(conn, "2026-11-12")
    assert row["new_learned"] == 0
    assert row["reviews_done"] == 0
    assert row["answered"] == 1
    assert row["xp_earned"] == 10


def test_words_done_today(conn):
    assert gamify.words_done_today(conn, "2026-11-12") == 0
    gamify.record_answer(conn, "2026-11-12", is_new=True, correct=True, xp=5)
    gamify.record_answer(conn, "2026-11-12", is_new=False, correct=True, xp=5)
    conn.commit()
    assert gamify.words_done_today(conn, "2026-11-12") == 2


def test_check_goal_first_time_only(conn):
    # 未达标
    gamify.record_answer(conn, "2026-11-12", is_new=True, correct=True, xp=5)
    assert gamify.check_goal(conn, "2026-11-12", goal=3) is False
    # 首次达标 → 发放奖励
    gamify.record_answer(conn, "2026-11-12", is_new=True, correct=True, xp=5)
    gamify.record_answer(conn, "2026-11-12", is_new=True, correct=True, xp=5)
    assert gamify.check_goal(conn, "2026-11-12", goal=3) is True
    conn.commit()
    row = db.get_daily(conn, "2026-11-12")
    assert row["goal_met"] == 1
    assert row["xp_earned"] == 15 + config.XP_GOAL_BONUS
    # 再次调用不重复发放
    assert gamify.check_goal(conn, "2026-11-12", goal=3) is False
    assert db.get_daily(conn, "2026-11-12")["xp_earned"] == 15 + config.XP_GOAL_BONUS


def test_check_goal_no_stats_row(conn):
    assert gamify.check_goal(conn, "2026-11-12", goal=1) is False


def test_calc_streak_empty(conn):
    assert gamify.calc_streak(conn, "2026-11-12") == 0


def test_calc_streak_with_db(conn):
    for d in ("2026-11-10", "2026-11-11", "2026-11-12"):
        db.set_goal_met(conn, d)
    conn.commit()
    # 今天已达标：12、11、10 → 3
    assert gamify.calc_streak(conn, "2026-11-12") == 3

    # 今天未达标但昨天达标：从 11 往回 → 2（今天没做不算断签）
    assert gamify.calc_streak(conn, "2026-11-13") == 3  # 12,11,10 都 met
    db.set_goal_met(conn, "2026-11-13")
    conn.commit()
    assert gamify.calc_streak(conn, "2026-11-13") == 4

    # 中间断档：2026-11-09 不达标 → 断在 10
    assert gamify.calc_streak(conn, "2026-11-09") == 0  # 09 与之前都不在集合
    # 隔天未达标：11-14 没达标，从 13 往回数
    assert gamify.calc_streak(conn, "2026-11-14") == 4


def test_current_unit_progression(conn, sample_book):
    assert gamify.current_unit(conn, sample_book["id"]) == 1
    # 学完单元 1（word01-04）→ 当前关卡变 2
    for row in db.fetch_new(conn, sample_book["id"], 4):
        db.upsert_progress(
            conn, row["id"], "learning", 2.5, 1, 1, 0, "2026-11-13", "2026-11-12"
        )
    conn.commit()
    assert gamify.current_unit(conn, sample_book["id"]) == 2
    # 全部学完 → 仍是最后一关
    for row in db.fetch_new(conn, sample_book["id"], 10):
        db.upsert_progress(
            conn, row["id"], "learning", 2.5, 1, 1, 0, "2026-11-13", "2026-11-12"
        )
    conn.commit()
    assert gamify.current_unit(conn, sample_book["id"]) == 2


def test_unit_completed(conn, sample_book):
    assert gamify.unit_completed(conn, sample_book["id"], 1) is False
    for row in db.fetch_new(conn, sample_book["id"], 4):  # 只学单元 1 的 4 个词
        db.upsert_progress(
            conn, row["id"], "learning", 2.5, 1, 1, 0, "2026-11-13", "2026-11-12"
        )
    conn.commit()
    assert gamify.unit_completed(conn, sample_book["id"], 1) is True
    assert gamify.unit_completed(conn, sample_book["id"], 2) is False
    assert gamify.unit_completed(conn, sample_book["id"], 99) is False  # 空单元


def test_award_unit_bonus_once(conn):
    assert gamify.award_unit_bonus(conn, "2026-11-12", 1, 1) is True
    conn.commit()
    assert gamify.award_unit_bonus(conn, "2026-11-13", 1, 1) is False  # 不重复发放
    assert gamify.award_unit_bonus(conn, "2026-11-12", 1, 2) is True  # 其他关卡独立
    conn.commit()
    assert db.get_daily(conn, "2026-11-12")["xp_earned"] == config.XP_UNIT_BONUS * 2
