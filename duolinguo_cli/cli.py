"""CLI 入口：click group 与子命令。"""

from __future__ import annotations

from pathlib import Path

import click

from . import __version__, books, config, db, gamify, menu, session
from .display import (
    console,
    print_books_table,
    print_import_result,
    print_unit_table,
    show_stats,
)


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
    """duolinguo — 多邻国风格的命令行背单词工具。

    不带子命令直接运行时，进入交互式菜单。
    """
    if ctx.invoked_subcommand is None:
        menu.run_menu()


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
        show_stats(conn)
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

        if key not in db.CONFIG_KEYS:
            raise click.ClickException(
                f"未知配置项：{key}（可选：{', '.join(db.CONFIG_KEYS)}）"
            )

        if value is None:
            current = db.get_setting(conn, key)
            if current is None and key == "daily_goal":
                current = str(gamify.get_goal(conn))
            console.print(f"[cyan]{key}[/] = {current or '（未设置）'}")
            return

        books.ensure_builtins(conn)  # current_book 校验前确保内置词书已入库
        try:
            db.apply_setting(conn, key, value)
        except ValueError as e:
            raise click.ClickException(str(e)) from e
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
        print_unit_table(book["name"], books.unit_progress(conn, book["id"]), full=True)
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
    print_import_result(book, added, errors)
