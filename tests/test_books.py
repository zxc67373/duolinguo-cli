"""词书管理测试：解析、导入、当前词书。"""

from __future__ import annotations

import json

import pytest

from duolinguo_cli import books, config, db

# ---------------------------------------------------------------- 解析


def test_parse_csv_two_columns():
    entries, errors = books.parse_csv("abandon,v. 放弃\nability,n. 能力\n")
    assert entries == [
        {"word": "abandon", "phonetic": "", "meaning": "v. 放弃"},
        {"word": "ability", "phonetic": "", "meaning": "n. 能力"},
    ]
    assert errors == []


def test_parse_csv_three_and_four_columns():
    entries, errors = books.parse_csv(
        "abandon,/əˈbændən/,v. 放弃\nability,/əˈbɪləti/,n. 能力,He has the ability.\n"
    )
    assert entries[0]["phonetic"] == "/əˈbændən/"
    assert entries[1]["example"] == "He has the ability."
    assert errors == []


def test_parse_csv_header_and_bad_rows():
    entries, errors = books.parse_csv(
        "word,phonetic,meaning\n"
        "abandon,/x/,v. 放弃\n"
        ",missing_word\n"
        "onlyoneword\n"
        "abandon,/x/,v. 放弃\n"
    )
    assert len(entries) == 2  # 表头跳过；重复词由导入去重处理，解析阶段保留
    assert len(errors) == 2
    assert "第 2 行" not in errors[0] and "第" in errors[0]


def test_parse_csv_bom(tmp_path):
    p = tmp_path / "w.csv"
    p.write_bytes("﻿word,meaning\nabandon,v. 放弃\n".encode())
    entries, _ = books.parse_csv(p.read_text(encoding="utf-8-sig"))
    assert entries[0]["word"] == "abandon"


def test_parse_txt_tab_and_spaces():
    text = "# 注释\nabandon\tv. 放弃\n\nability    n. 能力\n"
    entries, errors = books.parse_txt(text)
    assert [e["word"] for e in entries] == ["abandon", "ability"]
    assert entries[1]["meaning"] == "n. 能力"
    assert errors == []


def test_parse_txt_with_phonetic():
    entries, errors = books.parse_txt("abandon\t/əˈbændən/\tv. 放弃\n")
    assert entries == [
        {"word": "abandon", "phonetic": "/əˈbændən/", "meaning": "v. 放弃"}
    ]
    assert errors == []


def test_parse_txt_bad_line():
    entries, errors = books.parse_txt("justoneword\nok\tv. 正常\n")
    assert len(entries) == 1
    assert len(errors) == 1
    assert "第 1 行" in errors[0]


# ---------------------------------------------------------------- 导入


def test_import_from_csv_file(conn, tmp_path):
    p = tmp_path / "my words.csv"
    p.write_text("word,meaning\nabandon,v. 放弃\nability,n. 能力\nbadline\n", encoding="utf-8")
    book, added, errors = books.import_from_file(conn, p)
    assert book["slug"] == "custom_my_words"
    assert book["source"] == "imported"
    assert added == 2
    assert len(errors) == 1
    words = conn.execute("SELECT word FROM words ORDER BY id").fetchall()
    assert [w["word"] for w in words] == ["abandon", "ability"]


def test_import_dedup_case_insensitive(conn, tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text("abandon,v. 放弃\nABANDON,v. 抛弃\n", encoding="utf-8")
    _, added, _ = books.import_from_file(conn, p)
    assert added == 1


def test_import_slug_collision(conn, tmp_path):
    p1 = tmp_path / "same.csv"
    p1.write_text("abandon,v. 放弃\n", encoding="utf-8")
    books.import_from_file(conn, p1, name="same")
    p2 = tmp_path / "same2.csv"
    p2.write_text("ability,n. 能力\n", encoding="utf-8")
    book2, _, _ = books.import_from_file(conn, p2, name="same")
    assert book2["slug"] == "custom_same_2"


def test_import_empty_file_raises(conn, tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("badline_only\n", encoding="utf-8")
    with pytest.raises(ValueError, match="没有可用词条"):
        books.import_from_file(conn, p)


def test_import_missing_file_raises(conn, tmp_path):
    with pytest.raises(ValueError, match="文件不存在"):
        books.import_from_file(conn, tmp_path / "nope.csv")


# ---------------------------------------------------------------- 内置词书


def test_builtin_json_structure():
    """内置词书结构自检：无词书时跳过，有则校验字段与去重。"""
    data_files = books.load_builtin_jsons()
    if not data_files:
        pytest.skip("words_data 尚无内置词书")
    for data in data_files:
        assert data["slug"] and data["name"]
        words = data["words"]
        assert words, f"{data['slug']} 词表为空"
        seen = set()
        for w in words:
            assert w.get("word"), f"{data['slug']} 存在缺 word 的词条"
            assert w.get("meaning"), f"{data['slug']}:{w['word']} 缺释义"
            assert w["word"].lower() not in seen, f"{data['slug']} 重复词 {w['word']}"
            seen.add(w["word"].lower())


def test_ensure_builtins_idempotent(builtinless_conn, tmp_path, monkeypatch):
    data_dir = tmp_path / "words_data"
    data_dir.mkdir()
    (data_dir / "mini.json").write_text(
        json.dumps(
            {
                "slug": "mini",
                "name": "迷你词书",
                "words": [{"word": "hello", "meaning": "int. 你好"}],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "WORDS_DATA_DIR", data_dir)
    assert books.ensure_builtins(builtinless_conn) == 1
    assert books.ensure_builtins(builtinless_conn) == 0  # 幂等
    book = db.get_book(builtinless_conn, "mini")
    assert book["source"] == "builtin"
    assert db.get_word(builtinless_conn, db.fetch_new(builtinless_conn, book["id"], 1)[0]["id"])[
        "word"
    ] == "hello"


# ---------------------------------------------------------------- 当前词书


def test_resolve_current_book_order(builtinless_conn, sample_book):
    # 无设置时取第一本
    assert books.resolve_current_book(builtinless_conn)["slug"] == "test_book"
    # 显式 slug 优先
    db.insert_book(builtinless_conn, "另一本", "other_book")
    assert books.resolve_current_book(builtinless_conn, "other_book")["slug"] == "other_book"
    # settings 次之
    books.use_book(builtinless_conn, "other_book")
    assert books.resolve_current_book(builtinless_conn)["slug"] == "other_book"
    # settings 指向不存在的词书时回退
    db.set_setting(builtinless_conn, "current_book", "ghost")
    assert books.resolve_current_book(builtinless_conn)["slug"] == "test_book"


def test_use_book_rejects_unknown(builtinless_conn):
    with pytest.raises(ValueError, match="词书不存在"):
        books.use_book(builtinless_conn, "nope")


def test_unit_progress(conn, sample_book):
    progress = books.unit_progress(conn, sample_book["id"])
    assert [p["unit"] for p in progress] == [1, 2]
    assert all(p["total"] == 4 for p in progress)
    w = db.fetch_new(conn, sample_book["id"], 4)[0]
    db.upsert_progress(conn, w["id"], "learning", 2.5, 1, 1, 0, "2026-11-13", "2026-11-12")
    conn.commit()
    progress = books.unit_progress(conn, sample_book["id"])
    assert progress[0]["learned"] == 1
    assert progress[1]["learned"] == 0


# ---------------------------------------------------------------- 词序迁移


def test_ensure_builtins_unit_migration(tmp_path, monkeypatch, conn):
    """JSON 词序变化 → 自动重排单元，学习进度（word_progress）保留。"""
    data_dir = tmp_path / "wd_mig"
    data_dir.mkdir()
    path = data_dir / "mig.json"

    def write(words):
        path.write_text(
            json.dumps(
                {"slug": "mig", "name": "迁移词书", "unit_size": 3, "words": words},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def units_of():
        rows = conn.execute(
            "SELECT w.word, w.unit FROM words w JOIN books b ON b.id = w.book_id "
            "WHERE b.slug = 'mig' ORDER BY w.id"
        ).fetchall()
        return {r["word"]: r["unit"] for r in rows}

    words_v1 = [{"word": f"w{i}", "meaning": f"释义{i}"} for i in range(6)]
    write(words_v1)
    monkeypatch.setattr(config, "WORDS_DATA_DIR", data_dir)
    assert books.ensure_builtins(conn) == 1  # 首次导入
    assert units_of() == {"w0": 1, "w1": 1, "w2": 1, "w3": 2, "w4": 2, "w5": 2}

    # 给 w0 记一条学习进度
    wid = conn.execute("SELECT id FROM words WHERE word = 'w0'").fetchone()["id"]
    db.upsert_progress(conn, wid, "learning", 2.5, 1, 1, 0, "2999-01-01", "2026-01-01")
    conn.commit()

    # 模拟"改为词频顺序"：词序倒置
    write(list(reversed(words_v1)))
    books._load_json_file.cache_clear()  # 同路径改写需清进程缓存
    assert books.ensure_builtins(conn) == 0  # 书已存在，不新建
    assert units_of() == {"w5": 1, "w4": 1, "w3": 1, "w2": 2, "w1": 2, "w0": 2}

    # 进度跟着 word 主键走，完好无损
    progress = db.get_progress(conn, wid)
    assert progress is not None
    assert progress["status"] == "learning"

    # marker 已更新：再跑一次是无操作
    assert books.ensure_builtins(conn) == 0
    assert units_of() == {"w5": 1, "w4": 1, "w3": 1, "w2": 2, "w1": 2, "w0": 2}
