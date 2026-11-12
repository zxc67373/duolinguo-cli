"""pytest 公共 fixture：临时数据库与测试词书。"""

from __future__ import annotations

import pytest

from duolinguo_cli import books as books_mod
from duolinguo_cli import config, db


@pytest.fixture
def conn(tmp_path, monkeypatch):
    """指向临时目录的数据库连接。"""
    monkeypatch.setattr(config, "DB_FILE", tmp_path / "learning.db")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    connection = db.get_conn()
    yield connection
    connection.close()


@pytest.fixture
def sample_book(conn):
    """8 个词的测试词书（每单元 4 词 → 2 个单元）。"""
    db.insert_book(conn, "测试词书", "test_book", source="builtin", description="测试用")
    entries = [{"word": f"word{i:02d}", "phonetic": "", "meaning": f"释义{i}"} for i in range(1, 9)]
    db.insert_words(conn, db.get_book(conn, "test_book")["id"], entries, unit_size=4)
    conn.commit()
    return db.get_book(conn, "test_book")


@pytest.fixture
def builtinless_conn(conn, tmp_path, monkeypatch):
    """屏蔽内置词书目录的连接（避免测试依赖 words_data 内容）。"""
    monkeypatch.setattr(config, "WORDS_DATA_DIR", tmp_path / "no_words_data")
    return conn


@pytest.fixture
def resolve_book():
    return books_mod.resolve_current_book
