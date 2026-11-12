"""SRS（简化 SM-2）状态机测试。"""

from __future__ import annotations

import pytest

from duolinguo_cli import config, srs

TODAY = "2026-11-12"


def test_new_word_correct():
    state = srs.WordState()
    new = srs.schedule(state, True, TODAY)
    assert new.status == "learning"
    assert new.reps == 1
    assert new.interval_days == 1
    assert new.due_at == "2026-11-13"
    assert new.lapses == 0
    # 入参不被修改
    assert state.reps == 0 and state.status == "new"


def test_new_word_wrong():
    state = srs.WordState()
    new = srs.schedule(state, False, TODAY)
    assert new.status == "learning"
    assert new.reps == 0
    assert new.lapses == 1
    assert new.interval_days == 1
    assert new.ease == pytest.approx(2.3)
    assert new.due_at == "2026-11-13"


def test_interval_ladder_and_graduation():
    state = srs.WordState()
    state = srs.schedule(state, True, TODAY)  # reps=1 → 1 天
    assert (state.interval_days, state.status) == (1, "learning")
    state = srs.schedule(state, True, TODAY)  # reps=2 → 3 天
    assert (state.interval_days, state.status) == (3, "learning")
    state = srs.schedule(state, True, TODAY)  # reps=3 → round(3*2.6)=8 天 ≥ 7 → 毕业
    assert state.interval_days == 8
    assert state.status == "mastered"
    assert state.ease == pytest.approx(2.65)
    assert state.due_at == "2026-11-20"


def test_ease_bounds():
    # 答错封底 1.3
    state = srs.WordState()
    for _ in range(10):
        state = srs.schedule(state, False, TODAY)
    assert state.ease == pytest.approx(config.EASE_MIN)
    # 答对封顶 3.0
    state = srs.WordState()
    for _ in range(20):
        state = srs.schedule(state, True, TODAY)
    assert state.ease == pytest.approx(config.EASE_MAX)


def test_interval_cap():
    state = srs.WordState(status="mastered", ease=3.0, interval_days=90, reps=10)
    new = srs.schedule(state, True, TODAY)
    assert new.interval_days == config.INTERVAL_CAP
    assert new.status == "mastered"


def test_mastered_wrong_resets():
    state = srs.WordState(status="mastered", ease=2.7, interval_days=15, reps=6, lapses=0)
    new = srs.schedule(state, False, TODAY)
    assert new.status == "learning"
    assert new.reps == 0
    assert new.interval_days == 1
    assert new.lapses == 1
    assert new.ease == pytest.approx(2.5)
    assert new.due_at == "2026-11-13"


def test_graduate_boundary():
    # 间隔恰好 7 → 毕业；6 → 未毕业
    s7 = srs.schedule(srs.WordState(reps=2, interval_days=3, ease=2.4), True, TODAY)
    assert s7.interval_days == 7  # round(3*2.4) = 7
    assert s7.status == "mastered"
    s6 = srs.schedule(srs.WordState(reps=2, interval_days=3, ease=2.0), True, TODAY)
    assert s6.interval_days == 6  # round(3*2.0) = 6
    assert s6.status == "learning"


def test_from_row():
    row = {
        "status": "learning",
        "ease": 2.4,
        "interval_days": 3,
        "reps": 2,
        "lapses": 1,
        "due_at": "2026-11-15",
    }

    class FakeRow(dict):
        def __getitem__(self, k):
            return dict.__getitem__(self, k)

    state = srs.WordState.from_row(FakeRow(row))
    assert state.status == "learning"
    assert state.ease == 2.4
    assert state.lapses == 1
