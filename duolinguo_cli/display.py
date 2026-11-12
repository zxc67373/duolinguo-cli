"""rich 展示层：表格、面板、进度条、即时反馈。"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from . import config
from .quiz import MCQ_EN2ZH, MCQ_ZH2EN, Question

console = Console()

QTYPE_LABELS = {
    MCQ_EN2ZH: "英译中",
    MCQ_ZH2EN: "中译英",
    "spelling": "拼写",
}


def _bar(done: int, goal: int, width: int = 10) -> str:
    if goal <= 0:
        return "░" * width
    filled = min(width, max(0, round(width * done / goal)))
    return "█" * filled + "░" * (width - filled)


# ---------------------------------------------------------------- 词书表格


def print_books_table(rows: list[dict], current_slug: str | None) -> None:
    """词书列表：名称、词数、已学、来源、当前标记。"""
    table = Table(title="词书列表", show_lines=False)
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


def print_unit_table(book_name: str, units: list[dict]) -> None:
    """词书详情：各关卡进度。"""
    table = Table(title=f"{book_name} · 关卡进度")
    table.add_column("关卡", justify="right")
    table.add_column("词数", justify="right")
    table.add_column("已学", justify="right")
    table.add_column("已掌握", justify="right")
    table.add_column("进度")
    for u in units:
        learned = u["learned"] or 0
        bar = "█" * learned + "░" * (u["total"] - learned)
        table.add_row(str(u["unit"]), str(u["total"]), str(learned), str(u["mastered"] or 0), bar)
    console.print(table)


# ---------------------------------------------------------------- 学习会话


def print_header(
    book_name: str, unit: int, streak: int, xp_total: int, done: int, goal: int
) -> None:
    """会话顶部状态条。"""
    line1 = (
        f"[bold]{book_name}[/] · 关卡 {unit} · 连胜 [bold yellow]{streak}[/] 天"
        f" · 总 XP {xp_total}"
    )
    line2 = f"今日进度 [cyan]{_bar(done, goal)}[/] {done}/{goal}"
    console.print(Panel(f"{line1}\n{line2}", title="duolinguo", border_style="blue"))


def print_question(idx: int, total: int, q: Question) -> None:
    """逐题面板：题型标签、题干、选项。"""
    label = QTYPE_LABELS.get(q.qtype, q.qtype)
    lines = [f"[bold]{q.prompt}[/]"]
    if q.options:
        lines.append("")
        for i, opt in enumerate(q.options, start=1):
            lines.append(f"  [cyan]{i}[/]. {opt}")
    elif q.qtype == "spelling":
        lines.append("")
        lines.append("[dim]请拼写出对应的英文单词[/]")
    console.print(Panel("\n".join(lines), title=f"第 {idx}/{total} 题 · {label}"))


def print_spelling_hint(hint: str) -> None:
    console.print(f"[yellow]提示：[/]{hint or '（该词无音标）'}")


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
    """stats 总览面板。"""
    acc = f"{correct}/{answered}（{correct / answered:.0%}）" if answered else "0/0"
    line1 = f"连胜 [bold yellow]{streak}[/] 天 · 总 XP [bold]{xp_total}[/]"
    line2 = f"今日 [cyan]{_bar(done, goal)}[/] {done}/{goal} · 答题 {acc}"
    console.print(Panel(f"{line1}\n{line2}", title="学习概况", border_style="blue"))


def print_recent_table(rows: list[dict]) -> None:
    """近 N 天学习记录表（按日期升序）。"""
    if not rows:
        return
    table = Table(title="近期学习记录")
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


def print_summary(r) -> None:
    """会话总结面板（r 为 session.SessionResult）。"""
    lines = []
    total = r.answered
    acc = f"{r.correct}/{total}（{r.correct / total:.0%}）" if total else "0/0"
    lines.append(f"答题 [bold]{acc}[/] · 新学 {r.new_learned} 词 · 复习 {r.reviews_done} 词")
    if r.retries:
        lines.append(f"错词重练 {r.retries} 次")
    lines.append(f"本次获得 [bold yellow]+{r.xp} XP[/]")
    if r.quit_early:
        lines.append("[dim]（提前退出，进度已保存）[/]")

    remaining = max(0, r.goal - r.goal_done)
    if r.goal_met_now:
        lines.append(f"🎉 每日目标达成！{r.goal_done}/{r.goal}（+{config.XP_GOAL_BONUS} XP 奖励）")
    elif remaining:
        lines.append(f"每日目标还差 [yellow]{remaining}[/] 词：{r.goal_done}/{r.goal}")
    else:
        lines.append(f"每日目标已达成：{r.goal_done}/{r.goal}")

    lines.append(f"当前连胜 [bold yellow]{r.streak}[/] 天")

    if r.units_completed:
        for unit in r.units_completed:
            lines.append(f"[bold green]🏆 关卡 {unit} 完成！+{config.XP_UNIT_BONUS} XP[/]")
    else:
        lines.append(f"当前关卡：{r.unit}")

    style = "green" if r.goal_met_now or r.units_completed else "blue"
    console.print(Panel("\n".join(lines), title="本次学习完成", border_style=style))
