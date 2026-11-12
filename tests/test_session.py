"""会话引擎测试：队列编排、答题循环、错词重练、退出。"""

from __future__ import annotations

import random

import pytest

from duolinguo_cli import config, db, display, session

TODAY = db.today_str()


# ---------------------------------------------------------------- 队列编排


def mark_due(conn, words, due_at):
    for w in words:
        db.upsert_progress(
            conn, w["id"], "learning", 2.5, 1, 1, 0, due_at, "2026-11-01"
        )
    conn.commit()


def test_compose_queue_review_priority(conn, sample_book):
    """复习占一半名额，新词补足。"""
    due_words = db.fetch_new(conn, sample_book["id"], 4)
    mark_due(conn, due_words, TODAY)
    queue = session.compose_queue(conn, sample_book["id"], TODAY, count=6)
    assert len(queue) == 6
    due_part = [w for w, is_new in queue if not is_new]
    new_part = [w for w, is_new in queue if is_new]
    assert len(due_part) == 3  # 6//2
    assert len(new_part) == 3
    # 复习在前，且确实是已学词
    learned_ids = {w["id"] for w in due_words}
    assert all(w["id"] in learned_ids for w, _ in queue[:3])


def test_compose_queue_due_shortage_fills_with_new(conn, sample_book):
    mark_due(conn, db.fetch_new(conn, sample_book["id"], 1), TODAY)
    queue = session.compose_queue(conn, sample_book["id"], TODAY, count=6)
    assert len(queue) == 6
    assert sum(1 for _, is_new in queue if not is_new) == 1
    assert sum(1 for _, is_new in queue if is_new) == 5


def test_compose_queue_new_exhausted_uses_more_due(conn, sample_book):
    """新词学完（全复习）：名额全部给到期词。"""
    all_words = db.fetch_new(conn, sample_book["id"], 10)
    mark_due(conn, all_words, TODAY)
    queue = session.compose_queue(conn, sample_book["id"], TODAY, count=6)
    assert len(queue) == 6
    assert all(not is_new for _, is_new in queue)


def test_compose_queue_nothing_available(conn, sample_book):
    # 词都学了但都没到期 → 空队列
    mark_due(conn, db.fetch_new(conn, sample_book["id"], 10), "2999-01-01")
    assert session.compose_queue(conn, sample_book["id"], TODAY, count=6) == []


def test_compose_queue_review_mode(conn, sample_book):
    mark_due(conn, db.fetch_new(conn, sample_book["id"], 2), TODAY)
    queue = session.compose_queue(conn, sample_book["id"], TODAY, count=10, mode="review")
    assert len(queue) == 2
    # review 模式不混入新词
    assert all(not is_new for _, is_new in queue)


# ---------------------------------------------------------------- 会话交互


@pytest.fixture
def scripted(monkeypatch):
    """把会话中的题目捕获下来，按脚本自动作答。"""

    class Scripted:
        def __init__(self):
            self.current = None
            self.calls = 0
            self.script: list = []  # 每次作答的策略：'correct' | 'wrong' | 'q' | callable

        def print_question(self, idx, total, q):
            self.current = q

        def input_fn(self, prompt):
            self.calls += 1
            strategy = self.script.pop(0) if self.script else "correct"
            q = self.current
            if strategy == "q":
                return "q"
            if callable(strategy):
                raw = strategy(q)
                if raw not in ("correct", "wrong"):
                    return raw  # 直接作为用户原始输入（如非法值、? 提示）
                strategy = raw
            if strategy == "wrong":
                if q.qtype == "spelling":
                    return "zzz-wrong"
                return str(1 if q.answer_index != 0 else 2)
            # correct
            if q.qtype == "spelling":
                return q.answer
            return str(q.answer_index + 1)

        def n_questions(self):
            return self.calls

    s = Scripted()
    monkeypatch.setattr(display, "print_question", s.print_question)
    return s


def test_run_session_all_correct(conn, sample_book, scripted, monkeypatch):
    scripted.script = ["correct"] * 4
    result = session.run_session(
        conn, sample_book, count=4, rng=random.Random(1), input_fn=scripted.input_fn
    )
    assert result.answered == 4
    assert result.correct == 4
    assert result.new_learned == 4
    assert result.reviews_done == 0
    assert result.retries == 0
    assert result.quit_early is False
    assert result.xp >= 4 * config.XP_MCQ_CORRECT  # 至少都是选择题
    # 进度落库：4 个词已非 new，due 在明天之后
    learned = conn.execute(
        "SELECT COUNT(*) c FROM word_progress WHERE status != 'new'"
    ).fetchone()["c"]
    assert learned == 4
    # 每日统计
    row = db.get_daily(conn, TODAY)
    assert row["new_learned"] == 4
    assert row["answered"] == 4
    assert row["correct"] == 4
    assert row["xp_earned"] == result.xp


def test_run_session_wrong_triggers_spelling_retry(conn, sample_book, scripted):
    # 主循环 4 题全错 → 重练 4 次（拼写，答对）
    scripted.script = ["wrong"] * 4 + ["correct"] * 4
    result = session.run_session(
        conn, sample_book, count=4, rng=random.Random(1), input_fn=scripted.input_fn
    )
    assert result.answered == 8  # 4 主 + 4 重练
    assert result.retries == 4
    assert result.correct == 4
    assert result.new_learned == 4
    # XP = 重练拼写对 4×10 + 关卡完成 +30（单元1的4词都学过）
    assert result.units_completed == [1]
    assert result.xp == 4 * config.XP_SPELLING_CORRECT + config.XP_UNIT_BONUS
    # 错词重练不重复计入单词数维度
    row = db.get_daily(conn, TODAY)
    assert row["new_learned"] == 4
    assert row["reviews_done"] == 0
    assert row["answered"] == 8
    # SRS：先错后对 → interval=1、明天到期
    prog = conn.execute(
        "SELECT * FROM word_progress WHERE word_id = (SELECT id FROM words ORDER BY id LIMIT 1)"
    ).fetchone()
    assert prog["status"] == "learning"
    assert prog["interval_days"] == 1
    assert prog["lapses"] == 1
    assert prog["reps"] == 1


def test_run_session_quit_early(conn, sample_book, scripted):
    scripted.script = ["q"]
    result = session.run_session(
        conn, sample_book, count=4, rng=random.Random(1), input_fn=scripted.input_fn
    )
    assert result.quit_early is True
    assert result.answered == 0
    assert result.queued == 4  # 队列已编排但未作答
    assert conn.execute("SELECT COUNT(*) c FROM review_log").fetchone()["c"] == 0


def test_run_session_goal_bonus(conn, sample_book, scripted):
    scripted.script = ["correct"] * 4
    result = session.run_session(
        conn, sample_book, count=4, goal=3, rng=random.Random(1), input_fn=scripted.input_fn
    )
    assert result.goal_met_now is True
    assert db.get_setting(conn, "daily_goal") == "3"  # --goal 持久化
    # 第 3 题达成目标 +20，第 4 题不再重复
    expected_base = result.xp - config.XP_GOAL_BONUS
    assert expected_base >= 4 * config.XP_MCQ_CORRECT
    assert db.get_daily(conn, TODAY)["goal_met"] == 1


def test_run_session_review_mode_only_due(conn, sample_book, scripted):
    mark_due(conn, db.fetch_new(conn, sample_book["id"], 2), TODAY)
    scripted.script = ["correct"] * 2
    result = session.run_session(
        conn,
        sample_book,
        count=10,
        mode="review",
        rng=random.Random(1),
        input_fn=scripted.input_fn,
    )
    assert result.answered == 2
    assert result.reviews_done == 2
    assert result.new_learned == 0


def test_run_session_no_content(conn, sample_book):
    # 全部学完且未到期 → 空队列分支
    mark_due(conn, db.fetch_new(conn, sample_book["id"], 10), "2999-01-01")
    result = session.run_session(
        conn, sample_book, count=4, rng=random.Random(1), input_fn=lambda p: "q"
    )
    assert result.queued == 0
    assert result.answered == 0


def test_run_session_invalid_input_reprompts(conn, sample_book, scripted):
    # 非法输入两次（mcq 拒绝数字外输入；拼写用 ? 看提示不计数）后给正确答案
    scripted.script = [
        lambda q: ("9" if q.qtype != "spelling" else "?"),
        lambda q: ("x" if q.qtype != "spelling" else "?"),
        "correct",
        "q",
    ]
    result = session.run_session(
        conn, sample_book, count=4, rng=random.Random(1), input_fn=scripted.input_fn
    )
    # 第 1 题两次非法输入后答对 → answered=1；第 2 题输入 q 退出
    assert result.answered == 1
    assert result.correct == 1
    assert result.quit_early is True
