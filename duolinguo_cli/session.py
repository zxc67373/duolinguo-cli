"""学习会话引擎：队列编排、答题交互循环、错词重练。"""

from __future__ import annotations

import random
import sqlite3
from dataclasses import dataclass, field

from . import config, db, display, gamify, quiz, srs


class QuitSession(Exception):
    """用户输入 q 主动退出会话。"""


@dataclass
class SessionResult:
    """一次会话的结果汇总。"""

    book_slug: str
    book_name: str
    mode: str
    goal: int = 0
    goal_done: int = 0
    answered: int = 0
    correct: int = 0
    new_learned: int = 0
    reviews_done: int = 0
    retries: int = 0
    xp: int = 0
    goal_met_now: bool = False
    streak: int = 0
    unit: int = 1
    units_completed: list[int] = field(default_factory=list)
    quit_early: bool = False
    queued: int = 0


def compose_queue(
    conn: sqlite3.Connection, book_id: int, today: str, count: int, mode: str = "learn"
) -> list[tuple[sqlite3.Row, bool]]:
    """编排学习队列，返回 [(词条行, 是否新词), ...]。

    - learn：到期复习优先占一半名额，新词补足；新词不够时用剩余到期词补；
    - review：只要到期复习词。
    """
    if mode == "review":
        due = db.fetch_due(conn, book_id, today, count)
        return [(row, False) for row in due]

    due = db.fetch_due(conn, book_id, today, count)
    due_part = due[: count // 2]
    need = count - len(due_part)
    new = db.fetch_new(conn, book_id, need)
    extra_due = due[len(due_part) : len(due_part) + (need - len(new))]
    return [(row, False) for row in due_part + extra_due] + [(row, True) for row in new]


def _all_words(conn: sqlite3.Connection, book_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM words WHERE book_id = ? ORDER BY unit, id", (book_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def _ask(q: quiz.Question, input_fn) -> tuple[bool, str]:
    """向用户提问，返回 (是否答对, 作答原文)。q 退出抛 QuitSession。

    拼写答错会当场进入订正循环：显示正确答案，必须重新输入正确才放行。
    提示为渐进式（? 请求，半/全角均可）：先音标、再首字母+长度，不直接给答案。
    """
    hint_level = 0
    while True:
        if q.qtype == quiz.SPELLING:
            raw = input_fn("拼写这个单词（? 看提示 / q 退出）: ")
        else:
            raw = input_fn("选择 1-4（q 退出）: ")
        text = raw.strip()
        key = quiz.normalize(text)  # 全角→半角等归一化，兼容中文输入法

        if key == "q":
            raise QuitSession

        if q.qtype == quiz.SPELLING:
            if key == "?":
                hint_level += 1
                display.print_spelling_hint(q, hint_level)
                continue
            ok = quiz.grade_spelling(text, q.answer)
            if not ok:
                _correct_spelling(q, input_fn)
            return ok, text

        if key not in ("1", "2", "3", "4") or q.options is None:
            display.console.print("[yellow]请输入 1-4 之间的数字[/]")
            continue
        idx = int(key) - 1
        return idx == q.answer_index, q.options[idx]


def _correct_spelling(q: quiz.Question, input_fn) -> None:
    """拼写订正：显示答案后反复要求输入，输入正确才返回。"""
    display.print_correction_begin(q)
    while True:
        raw = input_fn(f"重新输入 {q.answer}: ")
        text = raw.strip()
        if quiz.normalize(text) == "q":
            raise QuitSession
        if not text:
            continue  # 空输入不算，重新显示提示
        if quiz.grade_spelling(text, q.answer):
            display.print_correction_ok()
            return
        display.print_correction_retry()


def _apply_answer(
    conn: sqlite3.Connection,
    word_id: int,
    correct: bool,
    qtype: str,
    response: str,
    today: str,
) -> None:
    """推进 SRS 状态并落库（进度 + 答题日志）。"""
    prog = db.get_progress(conn, word_id)
    state = srs.WordState.from_row(prog) if prog else srs.WordState()
    state = srs.schedule(state, correct, today)
    db.upsert_progress(
        conn,
        word_id,
        status=state.status,
        ease=state.ease,
        interval_days=state.interval_days,
        reps=state.reps,
        lapses=state.lapses,
        due_at=state.due_at,
        last_reviewed_at=db.now_str(),
    )
    db.add_review_log(conn, word_id, db.now_str(), qtype, correct, response)


def run_session(
    conn: sqlite3.Connection,
    book: sqlite3.Row,
    *,
    count: int = config.DEFAULT_SESSION_COUNT,
    mode: str = "learn",
    goal: int | None = None,
    input_fn=input,
    rng: random.Random | None = None,
) -> SessionResult:
    """跑一次完整学习会话，返回 SessionResult（进度实时落库）。"""
    rng = rng or random.Random()
    today = db.today_str()

    if goal is not None:
        db.set_setting(conn, "daily_goal", str(goal))
        conn.commit()

    result = SessionResult(
        book_slug=book["slug"], book_name=book["name"], mode=mode, goal=gamify.get_goal(conn)
    )
    queue = compose_queue(conn, book["id"], today, count, mode)
    if not queue:
        display.print_no_content(mode)
        result.streak = gamify.calc_streak(conn, today)
        result.goal_done = gamify.words_done_today(conn, today)
        return result

    result.queued = len(queue)
    # 会话内打乱：复习词与新词混合出题，不按块状顺序
    rng.shuffle(queue)
    result.unit = gamify.current_unit(conn, book["id"])
    display.print_header(
        book_name=book["name"],
        unit=result.unit,
        streak=gamify.calc_streak(conn, today),
        xp_total=db.total_xp(conn),
        done=gamify.words_done_today(conn, today),
        goal=result.goal,
    )

    all_words = _all_words(conn, book["id"])
    has_distractors = len(all_words) >= 4
    wrong_words: list[dict] = []

    try:
        for idx, (row, is_new) in enumerate(queue, start=1):
            target = dict(row)
            qtype = quiz.pick_qtype(
                is_new, has_distractors, has_example=bool(target.get("example")), rng=rng
            )
            q = quiz.build_question(target, all_words, qtype, rng=rng)
            display.print_question(idx, len(queue), q)
            correct, response = _ask(q, input_fn)

            _apply_answer(conn, target["id"], correct, q.qtype, response, today)
            xp = gamify.xp_for(q.qtype, correct)
            gamify.record_answer(conn, today, is_new=is_new, correct=correct, xp=xp)

            will_retry = not correct
            if will_retry:
                wrong_words.append(target)

            # 关卡完成判定（该词是关卡最后一个未学词时触发）
            unit = target["unit"]
            unit_done = False
            if gamify.unit_completed(conn, book["id"], unit):
                if gamify.award_unit_bonus(conn, today, book["id"], unit):
                    xp += config.XP_UNIT_BONUS
                    result.units_completed.append(unit)
                    unit_done = True

            # 每日目标首达奖励
            if gamify.check_goal(conn, today, result.goal):
                xp += config.XP_GOAL_BONUS
                result.goal_met_now = True

            conn.commit()
            result.answered += 1
            if correct:
                result.correct += 1
            if is_new:
                result.new_learned += 1
            else:
                result.reviews_done += 1
            result.xp += xp
            display.print_feedback(correct, xp, q, will_retry=will_retry)
            if unit_done:
                display.console.print(
                    f"[bold green]🏆 关卡 {unit} 完成！+{config.XP_UNIT_BONUS} XP[/]"
                )
    except QuitSession:
        result.quit_early = True

    # 错词重练：每词一次，强制拼写题
    if not result.quit_early and wrong_words:
        seen: set[int] = set()
        retry_list: list[dict] = []
        for w in wrong_words:
            if w["id"] not in seen:
                seen.add(w["id"])
                retry_list.append(w)
        for n, target in enumerate(retry_list, start=1):
            q = quiz.build_question(target, all_words, quiz.SPELLING, rng=rng)
            display.console.print(f"\n[bold magenta]订正 {n}/{len(retry_list)}[/]")
            display.print_question(result.answered + 1, result.answered + len(retry_list), q)
            try:
                correct, response = _ask(q, input_fn)
            except QuitSession:
                result.quit_early = True
                break
            _apply_answer(conn, target["id"], correct, q.qtype, response, today)
            xp = gamify.xp_for(q.qtype, correct)
            gamify.record_retry(conn, today, correct=correct, xp=xp)
            conn.commit()
            result.answered += 1
            result.retries += 1
            if correct:
                result.correct += 1
            result.xp += xp
            display.print_feedback(correct, xp, q, will_retry=False)

    result.goal_done = gamify.words_done_today(conn, today)
    result.streak = gamify.calc_streak(conn, today)
    result.unit = gamify.current_unit(conn, book["id"])
    display.print_summary(result)
    return result
