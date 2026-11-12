"""简化 SM-2 间隔重复算法：纯函数，无 I/O。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta

from . import config


@dataclass
class WordState:
    """单词记忆状态（对应 word_progress 行）。"""

    status: str = "new"  # new | learning | mastered
    ease: float = config.EASE_INIT
    interval_days: int = 0
    reps: int = 0
    lapses: int = 0
    due_at: str = ""

    @classmethod
    def from_row(cls, row) -> WordState:
        """从数据库行构造。"""
        return cls(
            status=row["status"],
            ease=row["ease"],
            interval_days=row["interval_days"],
            reps=row["reps"],
            lapses=row["lapses"],
            due_at=row["due_at"],
        )


def _due(today: str, interval_days: int) -> str:
    d = date.fromisoformat(today) + timedelta(days=interval_days)
    return d.isoformat()


def schedule(state: WordState, correct: bool, today: str) -> WordState:
    """根据作答结果推进记忆状态，返回新状态（不修改入参）。

    答错：连错计数清零、ease -0.2（不低于 1.3）、回到 learning、明天重来。
    答对：按 reps 阶梯推进间隔（1 → 3 → interval*ease，封顶 90）、
    ease +0.05（不超过 3.0）、间隔 ≥ 7 天毕业为 mastered。
    """
    if not correct:
        return replace(
            state,
            status="learning",
            ease=max(config.EASE_MIN, state.ease - 0.2),
            interval_days=1,
            reps=0,
            lapses=state.lapses + 1,
            due_at=_due(today, 1),
        )

    reps = state.reps + 1
    if reps == 1:
        interval = 1
    elif reps == 2:
        interval = 3
    else:
        interval = min(config.INTERVAL_CAP, max(1, round(state.interval_days * state.ease)))
    status = "mastered" if interval >= config.GRADUATE_INTERVAL else "learning"
    return replace(
        state,
        status=status,
        ease=min(config.EASE_MAX, state.ease + 0.05),
        interval_days=interval,
        reps=reps,
        due_at=_due(today, interval),
    )
