"""展示层：纯命令行风格——无面板边框、无表格网格，只用颜色与对齐。

摸鱼场景：输出低调紧凑，像普通命令行程序的输出。
"""

from __future__ import annotations

from datetime import date

from rich.console import Console
from rich.table import Table

from . import books, config, db, gamify, srs
from .quiz import CLOZE, MCQ_EN2ZH, MCQ_ZH2EN, Question

console = Console()

QTYPE_LABELS = {
    MCQ_EN2ZH: "英译中",
    MCQ_ZH2EN: "中译英",
    "spelling": "拼写",
    CLOZE: "例句填空",
}


def _bar(done: int, goal: int, width: int = 10) -> str:
    if goal <= 0:
        return "░" * width
    filled = min(width, max(0, round(width * done / goal)))
    return "█" * filled + "░" * (width - filled)


def _table(title: str) -> Table:
    """无边框表格：只靠列对齐，像命令行的对齐输出。"""
    return Table(title=title, title_justify="left", box=None, header_style="bold", pad_edge=False)


# ---------------------------------------------------------------- 词书表格


def print_books_table(rows: list[dict], current_slug: str | None) -> None:
    """词书列表：名称、词数、已学、来源、当前标记。"""
    table = _table("词书列表")
    table.add_column("slug", style="dim")
    table.add_column("名称")
    table.add_column("词数", justify="right")
    table.add_column("已学", justify="right")
    table.add_column("来源")
    table.add_column("")
    for r in rows:
        mark = "[bold green]● 当前[/]" if r["slug"] == current_slug else ""
        table.add_row(
            r["slug"],
            r["name"],
            str(r["word_count"]),
            str(r["learned_count"] or 0),
            "内置" if r["source"] == "builtin" else "导入",
            mark,
        )
    console.print(table)


def print_unit_table(book_name: str, units: list[dict], full: bool = False) -> None:
    """词书关卡进度。默认只展示到当前进度附近（避免长词书刷屏），full=True 全量。"""
    if not units:
        return
    if full:
        shown, hidden = units, 0
    else:
        last_active = max(
            (u["unit"] for u in units if (u["learned"] or 0) > 0),
            default=1,
        )
        keep_until = last_active + 2
        shown = [u for u in units if u["unit"] <= keep_until or (u["learned"] or 0) > 0]
        hidden = len(units) - len(shown)

    table = _table(f"{book_name} · 关卡进度")
    table.add_column("关卡", justify="right")
    table.add_column("词数", justify="right")
    table.add_column("已学", justify="right")
    table.add_column("已掌握", justify="right")
    table.add_column("进度")
    for u in shown:
        learned = u["learned"] or 0
        bar = "█" * learned + "░" * (u["total"] - learned)
        table.add_row(str(u["unit"]), str(u["total"]), str(learned), str(u["mastered"] or 0), bar)
    console.print(table)
    if hidden > 0:
        console.print(f"[dim]… 其余 {hidden} 关省略（duolinguo books show <slug> 查看全部）[/]")


# ---------------------------------------------------------------- 学习会话


def print_header(
    book_name: str, unit: int, streak: int, xp_total: int, done: int, goal: int
) -> None:
    """会话顶部状态（单行）。"""
    console.print()
    console.print(
        f"[bold]{book_name}[/] · 关卡 {unit} · 连胜 [bold yellow]{streak}[/] 天"
        f" · 总 XP {xp_total} · 今日 [cyan]{_bar(done, goal)}[/] {done}/{goal}"
    )


def print_question(idx: int, total: int, q: Question) -> None:
    """一题：题型行 + 题干 + 选项，无边框（语境走 ? 渐进提示）。"""
    label = QTYPE_LABELS.get(q.qtype, q.qtype)
    console.print()
    console.print(f"[dim]第 {idx}/{total} 题[/] · [bold]{label}[/]")
    console.print(q.prompt)
    if q.options:
        for i, opt in enumerate(q.options, start=1):
            console.print(f"  [cyan]{i}[/]. {opt}")
    elif q.qtype == "spelling":
        console.print("[dim]请拼写出对应的英文单词[/]")


_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"


def print_hint(q: Question, level: int) -> None:
    """按题型的渐进提示阶梯给出第 level 级提示；用尽后提示没有更多。"""
    from .quiz import hint_ladder

    ladder = hint_ladder(q)
    if 1 <= level <= len(ladder):
        mark = _CIRCLED[level - 1] if level <= len(_CIRCLED) else str(level)
        console.print(f"[yellow]提示{mark}[/]：{ladder[level - 1]}")
    else:
        console.print("[dim]没有更多提示了，试着作答吧[/]")


def print_correction_begin(q: Question) -> None:
    """拼写答错：给出正确答案，要求重新输入。"""
    phonetic = q.word.get("phonetic", "")
    extra = f"  {phonetic}" if phonetic else ""
    console.print(f"[red]正确拼写：[/][bold]{q.answer}[/]{extra}")
    console.print("[dim]请重新输入以继续[/]")


def print_correction_retry() -> None:
    console.print("[red]不对，再输入一次[/]")


def print_correction_ok() -> None:
    console.print("[green]✓ 正确[/]  继续下一题")


def print_feedback(correct: bool, xp: int, q: Question, will_retry: bool) -> None:
    """即时反馈：答对绿色、答错红色并展示正确答案。"""
    if correct:
        console.print(f"[bold green]✓ 答对了[/]  +{xp} XP")
    else:
        phonetic = q.word.get("phonetic", "")
        extra = f"  {phonetic}" if phonetic else ""
        line = f"[bold red]✗ 答错[/]  正确答案：[bold]{q.answer}[/]{extra}"
        if will_retry:
            line += "  [dim]稍后重练[/]"
        console.print(line)


def print_no_content(mode: str = "learn") -> None:
    if mode == "review":
        console.print("[yellow]当前没有到期需要复习的单词[/]")
    elif mode == "wrong":
        console.print("[yellow]暂无错题记录，继续加油[/]")
    else:
        console.print("[yellow]今天没有可学/可复习的内容了，休息一下吧[/]")


def print_stats_overview(
    streak: int, xp_total: int, done: int, goal: int, answered: int, correct: int
) -> None:
    """stats 总览（两行）。"""
    acc = f"{correct}/{answered}（{correct / answered:.0%}）" if answered else "0/0"
    console.print("[bold]学习概况[/]")
    console.print(
        f"连胜 [bold yellow]{streak}[/] 天 · 总 XP [bold]{xp_total}[/]"
        f" · 今日 [cyan]{_bar(done, goal)}[/] {done}/{goal} · 答题 {acc}"
    )


def print_recent_table(rows: list[dict]) -> None:
    """近 N 天学习记录（按日期升序，无边框；正确率带条形图）。"""
    if not rows:
        return
    table = _table("近期学习记录")
    table.add_column("日期")
    table.add_column("新学", justify="right")
    table.add_column("复习", justify="right")
    table.add_column("答题", justify="right")
    table.add_column("正确率")
    table.add_column("XP", justify="right")
    table.add_column("目标")
    for r in rows:
        if r["answered"]:
            rate = r["correct"] / r["answered"]
            bar = "█" * round(rate * 10) + "░" * (10 - round(rate * 10))
            acc = f"{bar} {rate:.0%}（{r['correct']}/{r['answered']}）"
        else:
            acc = "—"
        table.add_row(
            r["date"],
            str(r["new_learned"]),
            str(r["reviews_done"]),
            str(r["answered"]),
            acc,
            str(r["xp_earned"]),
            "✓" if r["goal_met"] else "",
        )
    console.print(table)


def print_forgetting_risk(items: list[dict]) -> None:
    """临近遗忘 TOP：当前记忆概率最低的已学词（越靠前越危险）。"""
    if not items:
        return
    console.print("[bold]📉 临近遗忘（记忆概率最低的已学词）[/]")
    for it in items:
        r_pct = f"{it['retrievability']:.0%}"
        if it["overdue_days"] > 0:
            note = f"[red]逾期 {it['overdue_days']} 天[/]"
        elif it["due_today"]:
            note = "[yellow]今日到期[/]"
        else:
            note = ""
        console.print(
            f"  {it['word']}  [yellow]{r_pct}[/]  {it['meaning'][:18]}  {note}"
        )


# ---------------------------------------------------------------- 交互菜单


def _forgetting_risk(conn, book_id: int, today: str, limit: int = 10) -> list[dict]:
    """当前词书已学词按记忆概率升序取 TOP N（FSRS R(t,S) 估算）。"""
    rows = conn.execute(
        """
        SELECT w.word, w.meaning, p.last_reviewed_at, p.due_at,
               p.stability, p.interval_days
        FROM word_progress p JOIN words w ON w.id = p.word_id
        WHERE w.book_id = ? AND p.status != 'new'
        """,
        (book_id,),
    ).fetchall()
    today_d = date.fromisoformat(today)
    items = []
    for r in rows:
        last = (r["last_reviewed_at"] or "")[:10]
        elapsed = (today_d - date.fromisoformat(last)).days if last else 10**6
        stability = r["stability"] or float(r["interval_days"] or 1)
        R = srs.retrievability(elapsed, stability)
        due = r["due_at"] or ""
        items.append(
            {
                "word": r["word"],
                "meaning": r["meaning"],
                "retrievability": R,
                "overdue_days": max(0, (today_d - date.fromisoformat(due)).days)
                if due and due <= today
                else 0,
                "due_today": due == today,
            }
        )
    items.sort(key=lambda x: x["retrievability"])
    return items[:limit]


def _due_forecast(conn, book_id: int, today: str) -> dict:
    """未来 7 天到期分布 + 逾期/今日到期统计（Anki 式预报）。"""
    from datetime import timedelta

    today_d = date.fromisoformat(today)
    rows = conn.execute(
        """
        SELECT p.due_at FROM word_progress p
        JOIN words w ON w.id = p.word_id
        WHERE w.book_id = ? AND p.status != 'new' AND p.due_at != ''
        """,
        (book_id,),
    ).fetchall()
    days = {(today_d + timedelta(days=i)).isoformat(): 0 for i in range(1, 8)}
    overdue = today_due = 0
    for r in rows:
        d = r["due_at"]
        if d < today:
            overdue += 1
        elif d == today:
            today_due += 1
        elif d in days:
            days[d] += 1
    return {
        "overdue": overdue,
        "today": today_due,
        "days": [(k, v) for k, v in days.items() if v > 0],
    }


def print_due_forecast(fc: dict) -> None:
    """渲染到期预报。"""
    head = (
        f"📅 到期预报：[red]已逾期 {fc['overdue']}[/] · "
        f"[yellow]今日到期 {fc['today']}[/]"
    )
    console.print(head)
    if not fc["days"]:
        console.print("  [dim]未来 7 天暂无到期词[/]")
        return
    for day, n in fc["days"]:
        bar = "█" * min(20, max(1, round(n / 2)))
        console.print(f"  {day} {bar} {n} 词")


def show_stats(conn) -> None:
    """渲染完整统计视图（概况 + 临近遗忘 + 近 14 天 + 关卡进度）。"""
    books.ensure_builtins(conn)
    today = db.today_str()
    goal = gamify.get_goal(conn)
    db.reevaluate_today_goal(conn, today, goal)  # 目标改动自愈，避免陈旧 ✓
    daily = db.get_daily(conn, today)
    print_stats_overview(
        streak=gamify.calc_streak(conn, today),
        xp_total=db.total_xp(conn),
        done=gamify.words_done_today(conn, today),
        goal=goal,
        answered=daily["answered"] if daily else 0,
        correct=daily["correct"] if daily else 0,
    )
    book = books.resolve_current_book(conn)
    if book:
        risk = _forgetting_risk(conn, book["id"], today)
        if risk:
            console.print()
            print_forgetting_risk(risk)
        fc = _due_forecast(conn, book["id"], today)
        console.print()
        print_due_forecast(fc)
    recent = conn.execute(
        "SELECT * FROM daily_stats ORDER BY date DESC LIMIT 14"
    ).fetchall()
    print_recent_table([dict(r) for r in reversed(recent)])
    if book:
        console.print()
        print_unit_table(book["name"], books.unit_progress(conn, book["id"]))


def print_main_menu(
    book_name: str | None,
    unit: int,
    streak: int,
    xp_total: int,
    done: int,
    goal: int,
    items: list[tuple[str, str]],
) -> None:
    """交互主菜单：状态行 + 编号选项，无边框。"""
    if book_name:
        status = (
            f"[bold dim]duolinguo[/]  {book_name} · 关卡 {unit}"
            f" · 连胜 [bold yellow]{streak}[/] 天 · XP {xp_total}"
            f" · 今日 [cyan]{_bar(done, goal)}[/] {done}/{goal}"
        )
    else:
        status = "[bold dim]duolinguo[/]  [yellow]还没有词书，先按 5 导入词表[/]"
    console.print(status)
    for key, label in items:
        console.print(f"  [cyan]{key}[/]. {label}")


def print_numbered_books(rows: list[dict], current_slug: str | None) -> None:
    """切换词书用：带编号的词书列表。"""
    for i, r in enumerate(rows, start=1):
        mark = " [green]● 当前[/]" if r["slug"] == current_slug else ""
        console.print(
            f"  [cyan]{i}[/]. {r['name']}[dim]（{r['slug']} · {r['word_count']} 词）[/]{mark}"
        )


def print_import_result(book, added: int, errors: list[str]) -> None:
    """导入结果（成功词数 + 跳过的坏行）。"""
    console.print(f"[green]导入成功[/]：{book['name']}（{book['slug']}），新增 {added} 词")
    if errors:
        console.print(f"[yellow]跳过 {len(errors)} 行[/]：")
        for err in errors[:10]:
            console.print(f"  - {err}")
        if len(errors) > 10:
            console.print(f"  …… 其余 {len(errors) - 10} 行略")


def print_summary(r) -> None:
    """会话总结（r 为 session.SessionResult），无边框。"""
    console.print()
    console.print("[bold]本次学习完成[/]")
    total = r.answered
    acc = f"{r.correct}/{total}（{r.correct / total:.0%}）" if total else "0/0"
    console.print(f"答题 [bold]{acc}[/] · 新学 {r.new_learned} 词 · 复习 {r.reviews_done} 词")
    if r.retries:
        console.print(f"错词重练 {r.retries} 次")
    console.print(f"本次获得 [bold yellow]+{r.xp} XP[/]")
    if r.quit_early:
        console.print("[dim]（提前退出，进度已保存）[/]")

    remaining = max(0, r.goal - r.goal_done)
    if r.goal_met_now:
        console.print(f"🎉 每日目标达成！{r.goal_done}/{r.goal}（+{config.XP_GOAL_BONUS} XP 奖励）")
    elif remaining:
        console.print(f"每日目标还差 [yellow]{remaining}[/] 词：{r.goal_done}/{r.goal}")
    else:
        console.print(f"每日目标已达成：{r.goal_done}/{r.goal}")

    console.print(f"当前连胜 [bold yellow]{r.streak}[/] 天")

    if r.units_completed:
        for unit in r.units_completed:
            console.print(f"[bold green]🏆 关卡 {unit} 完成！+{config.XP_UNIT_BONUS} XP[/]")
    else:
        console.print(f"当前关卡：{r.unit}")
