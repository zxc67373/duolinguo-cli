"""FSRS-6 调度测试。"""

from __future__ import annotations

from duolinguo_cli import srs

TODAY = "2026-11-12"


def test_fsrs_constants():
    """官方默认参数：DECAY 与 90% 保持率下间隔≈稳定度。"""
    assert srs.FSRS_W[20] == 0.1542
    assert len(srs.FSRS_W) == 21
    # S=2.3065（Good 初值）→ 间隔约 2 天
    assert srs.next_interval(srs.initial_stability(srs.GOOD)) in (2, 3)
    assert srs.next_interval(7.0) == 7  # 90% 保持率下 interval ≈ S


def test_first_review_new_word():
    new = srs.WordState()
    # 答对（Good）：初值 S=w2≈2.31 → 间隔 2 天，尚未毕业
    ok = srs.schedule(new, True, TODAY)
    assert ok.interval_days == 2
    assert ok.status == "learning"
    assert ok.stability > 0 and 1 <= ok.difficulty <= 10
    assert ok.due_at == "2026-11-14"
    assert ok.reps == 1 and ok.lapses == 0

    # 答错（Again）：S=w0=0.212 → 间隔 1 天
    bad = srs.schedule(new, False, TODAY)
    assert bad.interval_days == 1
    assert bad.status == "learning"
    assert bad.lapses == 1
    assert bad.due_at == "2026-11-13"


def test_stability_grows_and_graduates():
    """连续答对（隔日复习）→ 稳定度增长 → 间隔≥7 毕业为已掌握。"""
    state = srs.WordState()
    # Good → interval 2（次日+2 天节奏复习）
    state = srs.schedule(state, True, "2026-11-12")
    assert state.interval_days == 2
    # 第二次：隔 2 天复习
    state = srs.schedule(state, True, "2026-11-14")
    assert state.stability > 2.3
    assert state.interval_days > 2
    # 继续复习直到毕业
    for _ in range(10):
        from datetime import date, timedelta

        d = date.fromisoformat("2026-11-14") + timedelta(days=state.interval_days)
        state = srs.schedule(state, True, d.isoformat())
    assert state.interval_days >= 7
    assert state.status == "mastered"


def test_forgetting_resets():
    """已掌握的词答错 → 稳定度回撤、间隔 1、回到 learning。"""
    state = srs.WordState(stability=30.0, difficulty=3.0, interval_days=30, reps=10,
                          last_reviewed_at="2026-10-13")  # 30 天没见
    bad = srs.schedule(state, False, TODAY)
    assert bad.interval_days == 1
    assert bad.status == "learning"
    assert bad.stability < 30.0
    assert bad.lapses == 1
    assert bad.due_at == "2026-11-13"


def test_same_day_revisit_uses_short_term():
    """同日再答（错词当场重练场景）→ 短期稳定度分支，不按长期遗忘回撤。"""
    state = srs.WordState(stability=5.0, difficulty=3.0, interval_days=5,
                          last_reviewed_at="2026-11-12 08:00:00")
    same_day = srs.schedule(state, True, TODAY)  # days_since=0
    assert same_day.stability >= 5.0  # 答对只增不减
    assert same_day.due_at >= TODAY


def test_legacy_sm2_data接入():
    """旧 SM-2 数据（stability=0，有 interval）→ 以 interval 为 S 平滑接入。"""
    legacy = srs.WordState(status="mastered", ease=2.7, interval_days=21, reps=8)
    ok = srs.schedule(legacy, True, TODAY)
    assert ok.stability >= 21.0  # 以旧间隔为稳定度起点
    assert ok.interval_days >= 7
    assert ok.status == "mastered"

    # 旧词答错：回撤但不归零
    bad = srs.schedule(legacy, False, TODAY)
    assert bad.interval_days == 1
    assert bad.stability < 21.0
    assert bad.stability > 0


def test_retrievability():
    """R(t,S)：刚复习=1，随时间衰减，S 越小衰减越快。"""
    assert srs.retrievability(0, 5.0) == 1.0
    r1 = srs.retrievability(5, 5.0)
    r2 = srs.retrievability(5, 20.0)
    assert 0 < r1 < 1
    assert r2 > r1  # 稳定度越高，遗忘越慢
    assert srs.retrievability(10, 0) == 0


def test_answer_wrong_interval_always_one():
    """答错必明天见（无论原间隔多大）。"""
    state = srs.WordState(stability=100.0, difficulty=2.0, interval_days=100,
                          last_reviewed_at="2026-11-11")
    bad = srs.schedule(state, False, TODAY)
    assert bad.interval_days == 1


def test_explicit_hard_rating_shortens_interval():
    """显式 Hard 评分（如用过提示）→ 稳定度/间隔小于 Good。"""
    base = srs.WordState(stability=5.0, difficulty=3.0, interval_days=5,
                         last_reviewed_at="2026-11-10")
    good = srs.schedule(base, True, TODAY, rating=srs.GOOD)
    hard = srs.schedule(base, True, TODAY, rating=srs.HARD)
    assert hard.stability < good.stability
    assert hard.interval_days <= good.interval_days
    # 传错值（如 None）回退 Good；答错强制 Again 忽略传入值
    none = srs.schedule(base, True, TODAY, rating=None)
    assert none.stability == good.stability
    wrong = srs.schedule(base, False, TODAY, rating=srs.GOOD)
    assert wrong.interval_days == 1
