"""rich 展示层：表格、面板、进度条、即时反馈。"""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

console = Console()


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
