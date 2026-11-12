"""CLI 入口：click group 与子命令。"""

from __future__ import annotations

from pathlib import Path

import click

from . import __version__, books, db
from .display import console, print_books_table, print_unit_table


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="duolinguo")
@click.pass_context
def cli(ctx: click.Context) -> None:
    """duolinguo — 多邻国风格的命令行背单词工具。"""
    if ctx.invoked_subcommand is None:
        ctx.invoke(learn)


# ---------------------------------------------------------------- 学习


@cli.command()
@click.option("--count", default=None, type=int, help="本次题目数量")
@click.option("--book", "book_slug", default=None, help="指定词书 slug")
@click.option("--goal", default=None, type=int, help="覆盖每日目标")
def learn(count: int | None, book_slug: str | None, goal: int | None) -> None:
    """开始今日学习（新词 + 到期复习）。"""
    console.print("学习功能开发中……")


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
