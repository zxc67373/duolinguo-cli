"""CLI 入口：click group 与子命令。"""

from __future__ import annotations

from pathlib import Path

import click

from . import __version__, books, config, db, gamify, session
from .display import (
    console,
    print_books_table,
    print_recent_table,
    print_stats_overview,
    print_unit_table,
)

CONFIG_KEYS = ("daily_goal", "current_book")


def _resolve_book(conn, book_slug: str | None):
    """取当前/指定词书，给出友好报错。"""
    if book_slug:
        books.ensure_builtins(conn)
        book = db.get_book(conn, book_slug)
        if not book:
            raise click.ClickException(f"词书不存在：{book_slug}（duolinguo books list 查看）")
        return book
    book = books.resolve_current_book(conn)
    if not book:
        raise click.ClickException("还没有词书，先执行 duolinguo books import 导入词表")
    return book


def _run(conn, book, *, mode: str, count: int | None, goal: int | None) -> None:
    if count is not None and count < 1:
        raise click.ClickException("--count 必须 ≥ 1")
    if goal is not None and goal < 1:
        raise click.ClickException("--goal 必须 ≥ 1")
    session.run_session(
        conn,
        book,
        count=count or config.DEFAULT_SESSION_COUNT,
        mode=mode,
        goal=goal,
    )


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="duolinguo")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """duolinguo — 多邻国风格的命令行背单词工具。"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(learn)


# ---------------------------------------------------------------- 学习


@cli.command()
@click.option("--count", default=None, type=int, help="本次题目数量（默认 20）")
@click.option("--book", "book_slug", default=None, help="指定词书 slug（默认当前词书）")
@click.option("--goal", default=None, type=int, help="设置每日目标并保存")
def learn(count: int | None, book_slug: str | None, goal: int | None) -> None:
    """开始今日学习（新词 + 到期复习）。"""
    conn = db.get_conn()
    try:
        book = _resolve_book(conn, book_slug)
        _run(conn, book, mode="learn", count=count, goal=goal)
    finally:
        conn.close()


@cli.command()
@click.option("--count", default=None, type=int, help="本次题目数量（默认 20）")
@click.option("--book", "book_slug", default=None, help="指定词书 slug（默认当前词书）")
def review(count: int | None, book_slug: str | None) -> None:
    """只做到期复习（不学新词）。"""
    conn = db.get_conn()
    try:
        book = _resolve_book(conn, book_slug)
        _run(conn, book, mode="review", count=count, goal=None)
    finally:
        conn.close()


# ---------------------------------------------------------------- 统计


@cli.command()
def stats() -> None:
    """学习统计：连胜、XP、每日进度、关卡进度。"""
    conn = db.get_conn()
    try:
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
        recent = conn.execute(
            "SELECT * FROM daily_stats ORDER BY date DESC LIMIT 7"
        ).fetchall()
        print_recent_table([dict(r) for r in reversed(recent)])
        book = books.resolve_current_book(conn)
        if book:
            console.print()
            print_unit_table(book["name"], books.unit_progress(conn, book["id"]))
    finally:
        conn.close()


# ---------------------------------------------------------------- 设置


@cli.command(name="config")
@click.argument("key", required=False)
@click.argument("value", required=False)
def config_cmd(key: str | None, value: str | None) -> None:
    """查看或修改设置（如 duolinguo config daily_goal 30）。"""
    conn = db.get_conn()
    try:
        if key is None:
            rows = conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
            settings = {r["key"]: r["value"] for r in rows}
            settings.setdefault("daily_goal", str(gamify.get_goal(conn)))
            if not settings:
                console.print("[dim]暂无设置[/]")
                return
            for k, v in settings.items():
                console.print(f"[cyan]{k}[/] = {v}")
            return

        if key not in CONFIG_KEYS:
            raise click.ClickException(f"未知配置项：{key}（可选：{', '.join(CONFIG_KEYS)}）")

        if value is None:
            current = db.get_setting(conn, key)
            if current is None and key == "daily_goal":
                current = str(gamify.get_goal(conn))
            console.print(f"[cyan]{key}[/] = {current or '（未设置）'}")
            return

        if key == "daily_goal":
            if not value.isdigit() or int(value) < 1:
                raise click.ClickException("daily_goal 必须是正整数")
        else:  # current_book
            books.ensure_builtins(conn)
            if not db.get_book(conn, value):
                raise click.ClickException(f"词书不存在：{value}")
        db.set_setting(conn, key, value)
        conn.commit()
        console.print(f"[green]已设置[/] {key} = {value}")
    finally:
        conn.close()


# ---------------------------------------------------------------- 词书管理


@cli.group(name="books")
def books_group() -> None:
    """词书管理：查看、切换、导入。"""


@books_group.command("list")
def books_list() -> None:
    """查看所有词书。"""
    conn = db.get_conn()
    try:
        books.ensure_builtins(conn)
        current = books.resolve_current_book(conn)
        rows = [dict(r) for r in db.list_books(conn)]
        if not rows:
            console.print("[yellow]还没有词书[/]")
            return
        print_books_table(rows, current["slug"] if current else None)
    finally:
        conn.close()


@books_group.command("show")
@click.argument("slug")
def books_show(slug: str) -> None:
    """查看词书详情与各关卡进度。"""
    conn = db.get_conn()
    try:
        books.ensure_builtins(conn)
        book = db.get_book(conn, slug)
        if not book:
            raise click.ClickException(f"词书不存在：{slug}")
        print_unit_table(book["name"], books.unit_progress(conn, book["id"]))
    finally:
        conn.close()


@books_group.command("use")
@click.argument("slug")
def books_use(slug: str) -> None:
    """切换当前词书。"""
    conn = db.get_conn()
    try:
        books.use_book(conn, slug)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    finally:
        conn.close()
    console.print(f"[green]已切换到词书[/] {slug}")


@books_group.command("import")
@click.argument("path", type=click.Path(path_type=str))
@click.option("--name", default=None, help="词书展示名（默认用文件名）")
def books_import(path: str, name: str | None) -> None:
    """导入 CSV/TXT 词表为新词书。"""
    conn = db.get_conn()
    try:
        book, added, errors = books.import_from_file(conn, Path(path), name)
    except ValueError as e:
        raise click.ClickException(str(e)) from e
    finally:
        conn.close()
    console.print(f"[green]导入成功[/]：{book['name']}（{book['slug']}），新增 {added} 词")
    if errors:
        console.print(f"[yellow]跳过 {len(errors)} 行[/]：")
        for err in errors[:10]:
            console.print(f"  - {err}")
        if len(errors) > 10:
            console.print(f"  …… 其余 {len(errors) - 10} 行略")
