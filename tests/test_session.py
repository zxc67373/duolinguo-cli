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
            if "重新输入" in prompt:  # 拼写订正循环：自动输入正确答案放行
                return self.current.answer
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


def test_run_session_shuffles_queue(conn, sample_book, monkeypatch):
    """会话内打乱：复习+新词混合出题，集合不变、顺序打乱。"""
    mark_due(conn, db.fetch_new(conn, sample_book["id"], 4), TODAY)
    composed = [
        row["id"]
        for row, _ in session.compose_queue(conn, sample_book["id"], TODAY, count=8)
    ]
    assert len(composed) == 8  # 4 到期 + 4 新词

    seen: list[int] = []
    box: dict = {}

    def spy(idx, total, q):
        seen.append(q.word["id"])
        box["q"] = q

    monkeypatch.setattr(display, "print_question", spy)

    def input_fn(prompt):
        q = box["q"]
        return q.answer if q.qtype == "spelling" else str(q.answer_index + 1)

    result = session.run_session(
        conn, sample_book, count=8, rng=random.Random(1), input_fn=input_fn
    )
    assert result.answered == 8
    assert sorted(seen) == sorted(composed)  # 同一批词，一道不少
    assert seen != composed  # 但顺序被打乱（种子固定 → 确定性断言）


# ---------------------------------------------------------------- 拼写订正


def _spelling_question(word_text="word01"):
    from duolinguo_cli import quiz

    return quiz.Question(
        qtype=quiz.SPELLING,
        word={"id": 1, "word": word_text, "phonetic": "/w1/", "meaning": "释义1"},
        prompt="释义1",
        answer=word_text,
        hint="/w1/",
    )


def test_ask_spelling_wrong_then_corrected():
    """拼写答错 → 显示答案 → 输入正确才放行；判分仍为错。"""
    from duolinguo_cli.session import _ask

    q = _spelling_question()
    inputs = iter(["word01x", "word01"])  # 首答错 → 订正输入正确
    correct, resp = _ask(q, lambda p: next(inputs))
    assert correct is False
    assert resp == "word01x"  # 判分以首次作答为准
    # 订正过程消耗了第二次输入
    try:
        next(inputs)
        raise AssertionError("订正后不应再有待答输入")
    except StopIteration:
        pass


def test_ask_spelling_correction_retries_until_right():
    """订正循环：空输入、错输入都不放行，直到输对才返回。"""
    from duolinguo_cli.session import _ask

    q = _spelling_question()
    inputs = iter(["bad1", "", "nope", "word01"])  # 首答错 → 订正：空、错、对
    correct, resp = _ask(q, lambda p: next(inputs))
    assert correct is False and resp == "bad1"  # 判分以首次作答为准
    with pytest.raises(StopIteration):  # 4 个输入全部按序消耗
        next(inputs)


def test_ask_spelling_quit_during_correction():
    """订正过程中 q 退出 → 抛 QuitSession。"""
    import pytest

    from duolinguo_cli.session import QuitSession, _ask

    q = _spelling_question()
    inputs = iter(["bad", "q"])
    with pytest.raises(QuitSession):
        _ask(q, lambda p: next(inputs))


def test_session_spelling_wrong_logged_once(conn, sample_book, scripted, monkeypatch):
    """端到端：拼写答错触发订正；订正不重复记日志/SRS；错词仍进会话末重练。"""
    monkeypatch.setattr(session.quiz, "pick_qtype", lambda *a, **k: session.quiz.SPELLING)
    # Q1 答错（订正由 fixture 自动输对），其余答对
    scripted.script = ["wrong"] + ["correct"] * 20
    result = session.run_session(
        conn, sample_book, count=8, rng=random.Random(1), input_fn=scripted.input_fn
    )
    assert result.answered == 9  # 8 主题 + 1 会话末重练（Q1 的词）
    assert result.correct == 8  # 主题仅 Q1 错
    assert result.retries == 1
    logs = conn.execute(
        "SELECT correct FROM review_log ORDER BY id"
    ).fetchall()
    assert len(logs) == 9  # 订正输入不产生额外日志
    assert [r["correct"] for r in logs].count(0) == 1  # 只有首次作答记为错


# ---------------------------------------------------------------- 提示与全角输入


def test_ask_fullwidth_question_mark_shows_hint(capsys):
    """全角？触发提示而非判错；提示不包含完整答案。"""
    from duolinguo_cli.session import _ask

    q = _spelling_question()  # word01, 音标 /w1/
    inputs = iter(["？", "word01"])  # 全角问号 → 提示 → 答对
    correct, resp = _ask(q, lambda p: next(inputs))
    assert correct is True and resp == "word01"
    out = capsys.readouterr().out
    assert "/w1/" in out  # 第 1 级提示：音标
    assert "正确拼写" not in out  # 没有进入订正（未泄答案）
    assert "word01" not in out  # 提示本身不含完整答案


def test_ask_hint_progressive_without_answer(capsys):
    """连续 ?：① 音标 ② 首字母+长度；两级都不给完整答案。"""
    from duolinguo_cli.session import _ask

    q = _spelling_question()
    inputs = iter(["?", "?", "word01"])
    correct, _ = _ask(q, lambda p: next(inputs))
    out = capsys.readouterr().out
    assert correct is True
    assert "音标 /w1/" in out  # 第 1 级
    assert "首字母" in out and "共 6 个字母" in out  # 第 2 级
    assert "word01" not in out  # 任何一级都不亮答案
    assert "正确拼写" not in out


def test_ask_fullwidth_digit_answers_mcq():
    """全角数字１-４同样能选中选项。"""
    from duolinguo_cli import quiz
    from duolinguo_cli.session import _ask

    words = [
        {"id": i, "word": f"w{i}", "phonetic": "", "meaning": f"释义{i}", "unit": 1}
        for i in range(1, 9)
    ]
    q = quiz.build_question(words[0], words, quiz.MCQ_EN2ZH, rng=random.Random(5))
    assert q.options is not None
    fullwidth = chr(0xFF10 + (q.answer_index + 1))  # 半角数字 → 全角
    correct, resp = _ask(q, lambda p: fullwidth)
    assert correct is True
    assert resp == q.answer


def test_ask_mcq_accepts_option_text():
    """选择题直接输入选项原文（拼出单词）→ 等同选中该选项。"""
    from duolinguo_cli import quiz
    from duolinguo_cli.session import _ask

    words = [
        {"id": i, "word": f"w{i}", "phonetic": "", "meaning": f"释义{i}", "unit": 1}
        for i in range(1, 9)
    ]
    q = quiz.build_question(words[0], words, quiz.MCQ_ZH2EN, rng=random.Random(5))
    assert q.options is not None
    # 输入正确单词原文（全角字母也认）→ 判对
    fw = str.maketrans(
        "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
        "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ",
    )
    correct, resp = _ask(q, lambda p: q.answer.upper().translate(fw))
    assert correct is True and resp == q.answer
    # 输入错误选项的原文 → 判错（仍算作选中该项）
    wrong_opt = next(o for o in q.options if o != q.answer)
    correct2, resp2 = _ask(q, lambda p: wrong_opt)
    assert correct2 is False and resp2 == wrong_opt


def test_ask_mcq_rejects_unknown_text_then_accepts_number():
    """非选项内容 → 重问；再输数字正常作答。"""
    from duolinguo_cli import quiz
    from duolinguo_cli.session import _ask

    words = [
        {"id": i, "word": f"w{i}", "phonetic": "", "meaning": f"释义{i}", "unit": 1}
        for i in range(1, 9)
    ]
    q = quiz.build_question(words[0], words, quiz.MCQ_EN2ZH, rng=random.Random(3))
    inputs = iter(["zzz-not-an-option", str(q.answer_index + 1)])
    correct, resp = _ask(q, lambda p: next(inputs))
    assert correct is True and resp == q.answer


def test_session_spelling_wrong_no_duplicate_error_line(
    conn, sample_book, scripted, monkeypatch, capsys
):
    """拼写答错：订正流程收尾，不再追加“✗ 答错/稍后重练”重复反馈。"""
    monkeypatch.setattr(session.quiz, "pick_qtype", lambda *a, **k: session.quiz.SPELLING)
    scripted.script = ["wrong"] + ["correct"] * 20
    session.run_session(
        conn, sample_book, count=2, rng=random.Random(1), input_fn=scripted.input_fn
    )
    out = capsys.readouterr().out
    assert "正确拼写" in out  # 订正流程存在
    assert "✓ 正确" in out  # 订正完成确认
    assert "✗ 答错" not in out  # 不再追加答错行
    assert "稍后重练" not in out  # 不再提示重练（重练本身照常发生）
    # 重练环节本身仍在
    assert "订正 1/" in out
