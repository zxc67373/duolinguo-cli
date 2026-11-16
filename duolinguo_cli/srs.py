"""间隔重复调度：FSRS-6（日级简化版）。

公式与默认参数移植自官方实现 open-spaced-repetition/py-fsrs（MIT），
适配为本工具的日级调度（省略分钟级 learning steps / 区间抖动）：
- 状态：stability S（稳定天数）、difficulty D（1-10）
- 评分映射：答错 → Again(1)，答对 → Good(3)
- 期望保持率 0.9；间隔 = S 对应的 90% 记忆概率天数
旧 SM-2 数据（ease/interval）平滑接入：stability=0 时以现有 interval 作为 S 初值。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, timedelta

from . import config

# FSRS-6 默认参数（py-fsrs DEFAULT_PARAMETERS，21 项，w[20]=DECAY）
FSRS_W = (
    0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001,
    1.8722, 0.1666, 0.796, 1.4835, 0.0614, 0.2629, 1.6483, 0.6014,
    1.8729, 0.5425, 0.0912, 0.0658, 0.1542,
)
_DECAY = -FSRS_W[20]          # 0.1542
_FACTOR = 0.9 ** (1 / _DECAY) - 1
_DESIRED_RETENTION = 0.9
_MAX_INTERVAL = 36500          # 天（FSRS 默认）
_STABILITY_MIN = 0.001
_DIFFICULTY_MIN, _DIFFICULTY_MAX = 1.0, 10.0

# 评分（py-fsrs Rating）
AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4

# 间隔达到该天数视为「已掌握」（沿用展示语义）
GRADUATE_INTERVAL = 7


@dataclass
class WordState:
    """单词记忆状态（对应 word_progress 行）。"""

    status: str = "new"  # new | learning | mastered
    ease: float = config.EASE_INIT  # 旧 SM-2 遗留列，FSRS 不再使用但保持读写
    interval_days: int = 0
    reps: int = 0
    lapses: int = 0
    due_at: str = ""
    stability: float = 0.0   # FSRS：稳定天数（0=尚未初始化）
    difficulty: float = 0.0  # FSRS：难度 1-10（0=尚未初始化）
    last_reviewed_at: str = ""

    @classmethod
    def from_row(cls, row) -> WordState:
        keys = row.keys()
        return cls(
            status=row["status"],
            ease=row["ease"],
            interval_days=row["interval_days"],
            reps=row["reps"],
            lapses=row["lapses"],
            due_at=row["due_at"],
            stability=row["stability"] if "stability" in keys else 0.0,
            difficulty=row["difficulty"] if "difficulty" in keys else 0.0,
            last_reviewed_at=row["last_reviewed_at"] if "last_reviewed_at" in keys else "",
        )


def _clamp_stability(s: float) -> float:
    return max(s, _STABILITY_MIN)


def _clamp_difficulty(d: float) -> float:
    return min(max(d, _DIFFICULTY_MIN), _DIFFICULTY_MAX)


def initial_stability(rating: int) -> float:
    return _clamp_stability(FSRS_W[rating - 1])


def initial_difficulty(rating: int) -> float:
    return _clamp_difficulty(FSRS_W[4] - math.e ** (FSRS_W[5] * (rating - 1)) + 1)


def retrievability(elapsed_days: float, stability: float) -> float:
    """当前记忆概率 R(t, S)。stability≤0 视为完全遗忘风险（返回 0）。"""
    if stability <= 0:
        return 0.0
    return (1 + _FACTOR * max(0.0, elapsed_days) / stability) ** _DECAY


def next_interval(stability: float) -> int:
    """90% 保持率下的下次复习间隔（天）。"""
    raw = (stability / _FACTOR) * ((_DESIRED_RETENTION ** (1 / _DECAY)) - 1)
    return max(1, min(round(raw), _MAX_INTERVAL))


def _next_difficulty(difficulty: float, rating: int) -> float:
    delta = -FSRS_W[6] * (rating - 3)
    damped = (10.0 - difficulty) * delta / 9.0
    arg2 = difficulty + damped
    arg1 = FSRS_W[4] - math.e ** (FSRS_W[5] * (EASY - 1)) + 1  # D0(Easy)
    return _clamp_difficulty(FSRS_W[7] * arg1 + (1 - FSRS_W[7]) * arg2)


def _short_term_stability(stability: float, rating: int) -> float:
    increase = math.e ** (FSRS_W[17] * (rating - 3 + FSRS_W[18])) * (
        stability ** -FSRS_W[19]
    )
    if rating in (HARD, GOOD, EASY):
        increase = max(increase, 1.0)
    return _clamp_stability(stability * increase)


def _forget_stability(difficulty: float, stability: float, r: float) -> float:
    long_term = (
        FSRS_W[11]
        * (difficulty ** -FSRS_W[12])
        * (((stability + 1) ** FSRS_W[13]) - 1)
        * (math.e ** ((1 - r) * FSRS_W[14]))
    )
    short_term = stability / (math.e ** (FSRS_W[17] * FSRS_W[18]))
    return _clamp_stability(min(long_term, short_term))


def _recall_stability(difficulty: float, stability: float, r: float, rating: int) -> float:
    hard_penalty = FSRS_W[15] if rating == HARD else 1.0
    easy_bonus = FSRS_W[16] if rating == EASY else 1.0
    return _clamp_stability(
        stability
        * (
            1
            + (math.e ** FSRS_W[8])
            * (11 - difficulty)
            * (stability ** -FSRS_W[9])
            * ((math.e ** ((1 - r) * FSRS_W[10])) - 1)
            * hard_penalty
            * easy_bonus
        )
    )


def schedule(state: WordState, correct: bool, today: str) -> WordState:
    """按 FSRS-6 推进记忆状态，返回新状态（不修改入参）。

    - 答错 → Again(1)：稳定度按遗忘公式回撤，明天再来
    - 答对 → Good(3)：稳定度按召回公式增长，间隔拉长
    - 同日重复复习（如错词当场重练）走短期稳定度分支
    - 旧数据：stability=0 时以 interval_days 作为初始 S 平滑接入
    """
    rating = GOOD if correct else AGAIN
    last_date = state.last_reviewed_at[:10] if state.last_reviewed_at else ""
    days_since = None
    if last_date:
        days_since = (date.fromisoformat(today) - date.fromisoformat(last_date)).days

    stability, difficulty = state.stability, state.difficulty

    if stability <= 0:
        # 首次 / 旧 SM-2 数据接入
        if state.interval_days > 0:
            stability = float(state.interval_days)
            difficulty = initial_difficulty(GOOD)
        else:
            stability = initial_stability(rating)
            difficulty = initial_difficulty(rating)
        if correct:
            stability = _short_term_stability(stability, rating) if days_since == 0 else stability
        else:
            # 旧词首次以 FSRS 判错：按遗忘公式回撤（无 R 信息时按 0 记忆概率处理）
            r = retrievability(days_since or 0, stability) if days_since else 1.0
            stability = _forget_stability(difficulty, stability, r)
            stability = _clamp_stability(stability)
    elif days_since is not None and days_since < 1:
        # 同日复习
        stability = _short_term_stability(stability, rating)
        difficulty = _next_difficulty(difficulty, rating)
    else:
        r = retrievability(days_since or 0, stability)
        if correct:
            stability = _recall_stability(difficulty, stability, r, rating)
        else:
            stability = _forget_stability(difficulty, stability, r)
        difficulty = _next_difficulty(difficulty, rating)

    interval = next_interval(stability)
    if not correct:
        interval = 1  # 答错明天必见

    lapses = state.lapses + (0 if correct else 1)
    reps = state.reps + (1 if correct else 0)
    status = "mastered" if (correct and interval >= GRADUATE_INTERVAL) else "learning"
    if not correct:
        status = "learning"

    return replace(
        state,
        status=status,
        interval_days=interval,
        reps=reps,
        lapses=lapses,
        due_at=_due(today, interval),
        stability=round(stability, 4),
        difficulty=round(difficulty, 4),
        last_reviewed_at=today,  # 会话落库时再写完整时间戳
    )


def _due(today: str, interval_days: int) -> str:
    d = date.fromisoformat(today) + timedelta(days=interval_days)
    return d.isoformat()
