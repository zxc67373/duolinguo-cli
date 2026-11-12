"""交互式主菜单：`duolinguo` 直接进入，所有操作在菜单内选择。

子命令（learn/review/stats/books/config）仍然保留，方便脚本化；
菜单与子命令共享同一套逻辑（session/display/books/gamify）。
"""

from __future__ import annotations

from pathlib import Path

from . import books, db, display, gamify, session

MENU_ITEMS: list[tuple[str, str]] = [
    ("1", "开始今日学习（新词 + 复习）"),
    ("2", "只复习到期单词"),
    ("3", "切换词书"),
    ("4", "学习统计"),
    ("5", "导入词表（CSV/TXT）"),
    ("6", "设置（每日目标等）"),
    ("0", "退出"),
]


def _current_book(conn):
    """当前词书（不触发内置词书加载，渲染菜单时高频调用）。"""
    slug = db.get_setting(conn, "current_book")
    if slug:
        book = db.get_book(conn, slug)
        if book:
            return book
    rows = db.list_books(conn)
    return rows[0] if rows else None


def _render_menu(conn) -> None:
    today = db.today_str()
    goal = gamify.get_goal(conn)
    book = _current_book(conn)
    display.print_main_menu(
        book_name=book["name"] if book else None,
        unit=gamify.current_unit(conn, book["id"]) if book else 1,
        streak=gamify.calc_streak(conn, today),
        xp_total=db.total_xp(conn),
        done=gamify.words_done_today(conn, today),
        goal=goal,
        items=MENU_ITEMS,
    )


def _learn(conn, mode: str, input_fn) -> None:
    book = _current_book(conn)
    if not book:
        display.console.print("[yellow]还没有词书，先按 5 导入词表[/]")
        return
    session.run_session(conn, book, mode=mode, input_fn=input_fn)


def _switch_book(conn, input_fn) -> None:
    rows = db.list_books(conn)
    if not rows:
        display.console.print("[yellow]还没有词书[/]")
        return
    current = _current_book(conn)
    display.print_numbered_books(rows, current["slug"] if current else None)
    raw = input_fn("输入编号或 slug 切换（回车取消）: ").strip()
    if not raw:
        return
    if raw.isdigit() and 1 <= int(raw) <= len(rows):
        slug = rows[int(raw) - 1]["slug"]
    else:
        slug = raw
    if current and slug == current["slug"]:
        display.console.print(f"[green]已经在当前词书[/] {current['name']}")
        return
    try:
        books.use_book(conn, slug)
    except ValueError as e:
        display.console.print(f"[red]{e}[/]")
        return
    display.console.print(f"[green]已切换到词书[/] {slug}")


def _import_book(conn, input_fn) -> None:
    path = input_fn("词表文件路径（回车取消）: ").strip()
    if not path:
        return
    name = input_fn("词书名称（回车用文件名）: ").strip() or None
    try:
        book, added, errors = books.import_from_file(conn, Path(path), name)
    except ValueError as e:
        display.console.print(f"[red]{e}[/]")
        return
    display.print_import_result(book, added, errors)


def _settings(conn, input_fn) -> None:
    settings = {
        r["key"]: r["value"]
        for r in conn.execute("SELECT key, value FROM settings ORDER BY key").fetchall()
    }
    settings.setdefault("daily_goal", str(gamify.get_goal(conn)))
    current = _current_book(conn)
    if current:
        settings.setdefault("current_book", current["slug"])
    display.console.print("[bold]当前设置[/]：")
    for k, v in settings.items():
        display.console.print(f"  [cyan]{k}[/] = {v}")
    line = input_fn("修改输入如 daily_goal 30（回车返回）: ").strip()
    if not line:
        return
    parts = line.split(None, 1)
    if len(parts) != 2:
        display.console.print("[yellow]格式：设置项 新值（如 daily_goal 30）[/]")
        return
    try:
        db.apply_setting(conn, parts[0], parts[1])
    except ValueError as e:
        display.console.print(f"[red]{e}[/]")
        return
    display.console.print(f"[green]已设置[/] {parts[0]} = {parts[1]}")


def run_menu(conn=None, input_fn=input) -> None:
    """进入交互主菜单，直到用户退出（0/q/Ctrl+C/EOF）。"""
    own_conn = conn is None
    if own_conn:
        conn = db.get_conn()
    try:
        books.ensure_builtins(conn)
        while True:
            _render_menu(conn)
            try:
                choice = input_fn("请选择: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                display.console.print("\n[yellow]已退出[/]")
                return
            if choice in ("0", "q", "quit", "exit"):
                display.console.print("[dim]下次见，保持连胜！[/]")
                return
            try:
                if choice == "1":
                    _learn(conn, "learn", input_fn)
                elif choice == "2":
                    _learn(conn, "review", input_fn)
                elif choice == "3":
                    _switch_book(conn, input_fn)
                elif choice == "4":
                    display.show_stats(conn)
                    input_fn("按回车返回菜单: ")
                elif choice == "5":
                    _import_book(conn, input_fn)
                elif choice == "6":
                    _settings(conn, input_fn)
                else:
                    display.console.print("[yellow]无效选择，请输入 0-6[/]")
            except (KeyboardInterrupt, EOFError):
                display.console.print("\n[yellow]已退出[/]")
                return
    finally:
        if own_conn:
            conn.close()
