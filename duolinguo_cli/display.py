"""展示层：纯命令行风格——无面板边框、无表格网格，只用颜色与对齐。

摸鱼场景：输出低调紧凑，像普通命令行程序的输出。
"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from . import books, config, db, gamify
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
    """一题：题型行 + 题干 + 语境（例句/挖空句）+ 选项，无边框。"""
    label = QTYPE_LABELS.get(q.qtype, q.qtype)
    console.print()
    console.print(f"[dim]第 {idx}/{total} 题[/] · [bold]{label}[/]")
    console.print(q.prompt)
    if q.note:
        console.print(f"[dim]{q.note}[/]")
    if q.options:
        for i, opt in enumerate(q.options, start=1):
            console.print(f"  [cyan]{i}[/]. {opt}")
    elif q.qtype == "spelling":
        console.print("[dim]请拼写出对应的英文单词[/]")


def print_spelling_hint(hint: str) -> None:
    console.print(f"[yellow]提示：[/]{hint or '（该词无音标）'}")


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
    """近 N 天学习记录（按日期升序，无边框）。"""
    if not rows:
        return
    table = _table("近期学习记录")
    table.add_column("日期")
    table.add_column("新学", justify="right")
    table.add_column("复习", justify="right")
    table.add_column("答题", justify="right")
    table.add_column("正确率", justify="right")
    table.add_column("XP", justify="right")
    table.add_column("目标")
    for r in rows:
        acc = f"{r['correct'] / r['answered']:.0%}" if r["answered"] else "—"
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


# ---------------------------------------------------------------- 交互菜单


def show_stats(conn) -> None:
    """渲染完整统计视图（学习概况 + 近 7 天 + 当前词书关卡进度）。"""
    books.ensure_builtins(conn)
    today = db.today_str()
    goal = gamify.get_goal(conn)
    daily = db.get_daily(conn, today)
    print_stats_overview(
        streak=gamify.calc_streak(conn, today),
        xp_total=db.total_xp(conn),
        done=gamify.words_done_today(conn, today),
        goal=goal,
        answered=daily["answered"] if daily else 0,
        correct=daily["correct"] if daily else 0,
    )
    recent = conn.execute("SELECT * FROM daily_stats ORDER BY date DESC LIMIT 7").fetchall()
    print_recent_table([dict(r) for r in reversed(recent)])
    book = books.resolve_current_book(conn)
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
