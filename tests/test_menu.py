"""交互式主菜单测试。"""

from __future__ import annotations

from click.testing import CliRunner

from duolinguo_cli import config, db, display, menu
from duolinguo_cli.cli import cli


def scripted_input(script: list[str]):
    """按脚本应答；'correct' 用当前捕获的题目算出正确答案。"""
    state = {"q": None, "script": list(script)}

    def fake_print_question(idx, total, q):
        state["q"] = q

    def input_fn(prompt):
        if "重新输入" in prompt:  # 拼写订正循环：自动输入正确答案放行
            return state["q"].answer
        if not state["script"]:
            return "0"  # 脚本耗尽 → 退出，避免挂死
        s = state["script"].pop(0)
        if s not in ("correct", "wrong"):
            return s
        q = state["q"]
        if s == "wrong":
            if q.qtype == "spelling":
                return "zzz-wrong"
            return str(1 if q.answer_index != 0 else 2)
        if q.qtype == "spelling":
            return q.answer
        return str(q.answer_index + 1)

    return input_fn, fake_print_question


def run_menu(conn, script, monkeypatch):
    input_fn, fake_print_question = scripted_input(script)
    monkeypatch.setattr(display, "print_question", fake_print_question)
    menu.run_menu(conn=conn, input_fn=input_fn)


def test_menu_exit_immediately(conn, monkeypatch):
    run_menu(conn, ["0"], monkeypatch)  # 不抛异常即通过


def test_menu_quit_aliases(conn, monkeypatch):
    run_menu(conn, ["q"], monkeypatch)


def test_menu_invalid_choice_then_exit(conn, monkeypatch):
    run_menu(conn, ["9", "xyz", "", "0"], monkeypatch)  # 无效输入重问，不崩溃


def test_menu_eof_exits_cleanly(conn):
    def eof(prompt):
        raise EOFError

    menu.run_menu(conn=conn, input_fn=eof)  # 不抛异常即通过


def test_menu_switch_book_by_number(builtinless_conn, monkeypatch):
    db.insert_book(builtinless_conn, "书A", "book_a")
    db.insert_book(builtinless_conn, "书B", "book_b")
    builtinless_conn.commit()
    run_menu(builtinless_conn, ["3", "2", "0"], monkeypatch)
    assert db.get_setting(builtinless_conn, "current_book") == "book_b"


def test_menu_switch_book_by_slug_and_cancel(builtinless_conn, monkeypatch):
    db.insert_book(builtinless_conn, "书A", "book_a")
    db.insert_book(builtinless_conn, "书B", "book_b")
    builtinless_conn.commit()
    # 按 slug 切换
    run_menu(builtinless_conn, ["3", "book_b", "0"], monkeypatch)
    assert db.get_setting(builtinless_conn, "current_book") == "book_b"
    # 不存在的 slug：报错但不改设置
    run_menu(builtinless_conn, ["3", "no_such", "0"], monkeypatch)
    assert db.get_setting(builtinless_conn, "current_book") == "book_b"
    # 回车取消
    run_menu(builtinless_conn, ["3", "", "0"], monkeypatch)
    assert db.get_setting(builtinless_conn, "current_book") == "book_b"


def test_menu_settings(builtinless_conn, monkeypatch):
    run_menu(builtinless_conn, ["6", "daily_goal 25", "0"], monkeypatch)
    assert db.get_setting(builtinless_conn, "daily_goal") == "25"
    # 非法值被拒绝，保持 25
    run_menu(builtinless_conn, ["6", "daily_goal abc", "0"], monkeypatch)
    assert db.get_setting(builtinless_conn, "daily_goal") == "25"
    # 格式错误（没有值）
    run_menu(builtinless_conn, ["6", "daily_goal", "0"], monkeypatch)
    assert db.get_setting(builtinless_conn, "daily_goal") == "25"


def test_menu_stats_renders(conn, monkeypatch):
    run_menu(conn, ["4", "", "0"], monkeypatch)  # 统计 + 回车返回 + 退出


def test_menu_learn_session(builtinless_conn, sample_book, monkeypatch):
    """菜单选 1 → 完整答完 8 题 → 回到菜单 → 退出。"""
    today = db.today_str()
    script = ["1"] + ["correct"] * 8 + ["0"]
    run_menu(builtinless_conn, script, monkeypatch)
    row = db.get_daily(builtinless_conn, today)
    assert row is not None
    assert row["answered"] == 8
    assert row["correct"] == 8
    assert row["new_learned"] == 8


def test_menu_review_with_nothing_due(builtinless_conn, sample_book, monkeypatch):
    run_menu(builtinless_conn, ["2", "0"], monkeypatch)  # 无到期词 → 提示后回菜单
    assert (db.get_daily(builtinless_conn, db.today_str()) or {"answered": 0})["answered"] == 0


def test_menu_import(tmp_path, builtinless_conn, monkeypatch):
    p = tmp_path / "my.csv"
    p.write_text("abandon,v. 放弃\nability,n. 能力\n", encoding="utf-8")
    run_menu(builtinless_conn, ["5", str(p), "我的词表", "0"], monkeypatch)
    customs = [r for r in db.list_books(builtinless_conn) if r["source"] == "imported"]
    assert len(customs) == 1
    assert customs[0]["name"] == "我的词表"
    assert customs[0]["word_count"] == 2


def test_cli_bare_runs_menu(tmp_path, monkeypatch):
    """裸 duolinguo 直接进菜单（喂 0 退出）。"""
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "menu.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(config, "WORDS_DATA_DIR", tmp_path / "no_data")
    runner = CliRunner()
    result = runner.invoke(cli, [], input="0\n")
    assert result.exit_code == 0, result.output
    assert "duolinguo" in result.output
    assert "开始今日学习" in result.output


def test_menu_learn_loops_until_goal(builtinless_conn, monkeypatch):
    """进入学习后自动连批，直到达成每日目标才回菜单（不用手动多次进入）。"""
    # 8 词小词书 + 目标 10：第一批 count=min(20,10)=10 → 出题 8（全学完）
    # done=8 <10 → 第二批无题可出 → 自动结束回菜单
    conn2 = builtinless_conn
    db.insert_book(conn2, "循环书", "loop_book")
    db.insert_words(
        conn2,
        db.get_book(conn2, "loop_book")["id"],
        [{"word": f"w{i}", "meaning": f"释义{i}"} for i in range(1, 9)],
        unit_size=20,
    )
    conn2.commit()
    db.set_setting(conn2, "daily_goal", "10")
    conn2.commit()

    input_fn, fake_print = scripted_input(["1"] + ["correct"] * 8 + ["0"])
    monkeypatch.setattr(display, "print_question", fake_print)
    menu.run_menu(conn=conn2, input_fn=input_fn)

    row = db.get_daily(conn2, db.today_str())
    assert row is not None
    assert row["answered"] == 8  # 两批合计：8 题后词书学完自然停
    assert row["new_learned"] == 8


def test_menu_learn_stops_at_goal_in_one_batch(builtinless_conn, monkeypatch):
    """目标在一批内达成 → 达成即停，不进第二批。"""
    conn2 = builtinless_conn
    db.insert_book(conn2, "小词书", "small_book")
    db.insert_words(
        conn2,
        db.get_book(conn2, "small_book")["id"],
        [{"word": f"s{i}", "meaning": f"义{i}"} for i in range(1, 9)],
        unit_size=20,
    )
    conn2.commit()
    db.set_setting(conn2, "daily_goal", "3")
    conn2.commit()

    input_fn, fake_print = scripted_input(["1"] + ["correct"] * 3 + ["0"])
    monkeypatch.setattr(display, "print_question", fake_print)
    menu.run_menu(conn=conn2, input_fn=input_fn)

    row = db.get_daily(conn2, db.today_str())
    assert row["answered"] == 3  # 一批 3 题达标即停（count=min(20,3)）
    assert row["new_learned"] == 3


def test_menu_learn_quit_stops_loop(builtinless_conn, monkeypatch):
    """学习中途 q 退出 → 整个目标循环终止回菜单。"""
    conn2 = builtinless_conn
    db.insert_book(conn2, "退出书", "quit_book")
    db.insert_words(
        conn2,
        db.get_book(conn2, "quit_book")["id"],
        [{"word": f"q{i}", "meaning": f"释{i}"} for i in range(1, 9)],
        unit_size=20,
    )
    conn2.commit()
    db.set_setting(conn2, "daily_goal", "100")
    conn2.commit()

    input_fn, fake_print = scripted_input(["1", "q", "0"])
    monkeypatch.setattr(display, "print_question", fake_print)
    menu.run_menu(conn=conn2, input_fn=input_fn)

    row = db.get_daily(conn2, db.today_str())
    assert row is None or row["answered"] == 0  # 第一题即退
