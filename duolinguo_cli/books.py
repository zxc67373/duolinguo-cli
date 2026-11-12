"""词书管理：内置 JSON 加载、CSV/TXT 导入、当前词书选择。"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import sqlite3
from functools import lru_cache
from pathlib import Path

from . import config, db

VALID_SOURCES = ("builtin", "imported")


@lru_cache(maxsize=8)
def _load_json_file(path_str: str) -> dict:
    """解析单个词书 JSON（进程内缓存；调用方只读，勿修改返回值）。"""
    data = json.loads(Path(path_str).read_text(encoding="utf-8"))
    for key in ("slug", "name", "words"):
        if key not in data:
            raise ValueError(f"{Path(path_str).name}: 缺少字段 {key}")
    return data


def load_builtin_jsons() -> list[dict]:
    """读取 words_data/ 下所有内置词书 JSON（结构自检后返回）。"""
    if not config.WORDS_DATA_DIR.is_dir():
        return []
    books = []
    for path in sorted(config.WORDS_DATA_DIR.glob("*.json")):
        data = dict(_load_json_file(str(path)))  # 浅拷贝：可安全附加 _path
        data["_path"] = path.name
        books.append(data)
    return books


def _content_marker(words: list[dict]) -> str:
    """词序 + 例句指纹：JSON 内容变化时触发迁移（重排 unit / 同步例句）。"""
    h = hashlib.md5()
    for w in words:
        h.update(w["word"].lower().encode("utf-8"))
        h.update(b"\x00")
        h.update(w.get("example", "").encode("utf-8"))
        h.update(b"\x01")
    return h.hexdigest()


def ensure_builtins(conn: sqlite3.Connection) -> int:
    """确保内置词书入库（按 slug 幂等），返回新导入的词书数。

    若 JSON 词序/例句变化（如改为按词频排序、补充例句），自动同步到库——
    word 主键与 word_progress 不动，学习进度完整保留。
    """
    created = 0
    for data in load_builtin_jsons():
        unit_size = data.get("unit_size", config.UNIT_SIZE)
        marker = _content_marker(data["words"])
        marker_key = f"book_order:{data['slug']}"
        book = db.get_book(conn, data["slug"])
        if book is None:
            book_id = db.insert_book(
                conn,
                name=data["name"],
                slug=data["slug"],
                source="builtin",
                description=data.get("description", ""),
            )
            db.insert_words(conn, book_id, data["words"], unit_size)
            db.set_setting(conn, marker_key, marker)
            created += 1
            continue

        if db.get_setting(conn, marker_key) == marker:
            continue  # 内容未变，跳过

        # 内容变化 → 按新顺序重排单元、同步例句（进度按 word 保留）
        if book["description"] != data.get("description", ""):
            conn.execute(
                "UPDATE books SET description = ? WHERE id = ?",
                (data.get("description", ""), book["id"]),
            )
        existing = {
            r["word"]: (r["id"], r["unit"], r["example"])
            for r in conn.execute(
                "SELECT word, id, unit, example FROM words WHERE book_id = ?", (book["id"],)
            )
        }
        for i, entry in enumerate(data["words"]):
            unit = i // unit_size + 1
            example = entry.get("example", "")
            row = existing.get(entry["word"])
            if row is None:
                conn.execute(
                    "INSERT INTO words (book_id, word, phonetic, meaning, example, unit) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        book["id"],
                        entry["word"],
                        entry.get("phonetic", ""),
                        entry["meaning"],
                        example,
                        unit,
                    ),
                )
            elif row[1] != unit or row[2] != example:
                conn.execute(
                    "UPDATE words SET unit = ?, example = ? WHERE id = ?",
                    (unit, example, row[0]),
                )
        db.set_setting(conn, marker_key, marker)
    conn.commit()
    return created


# ---------------------------------------------------------------- 导入解析


def parse_csv(text: str) -> tuple[list[dict], list[str]]:
    """解析 CSV：`word,meaning` 或 `word,phonetic,meaning`（第 4 列为可选例句）。

    返回 (词条列表, 错误信息列表)。首行为表头（首列 word，不区分大小写）时跳过。
    """
    entries: list[dict] = []
    errors: list[str] = []
    reader = csv.reader(io.StringIO(text))
    for i, row in enumerate(reader, start=1):
        if not row or all(not c.strip() for c in row):
            continue
        cells = [c.strip() for c in row]
        if i == 1 and cells[0].lower() == "word":
            continue
        if len(cells) < 2 or not cells[0] or not cells[-1]:
            errors.append(f"第 {i} 行：缺少单词或释义")
            continue
        if len(cells) == 2:
            entries.append({"word": cells[0], "phonetic": "", "meaning": cells[1]})
        elif len(cells) == 3:
            entries.append({"word": cells[0], "phonetic": cells[1], "meaning": cells[2]})
        else:
            entries.append(
                {
                    "word": cells[0],
                    "phonetic": cells[1],
                    "meaning": cells[2],
                    "example": cells[3],
                }
            )
    return entries, errors


def parse_txt(text: str) -> tuple[list[dict], list[str]]:
    """解析 TXT：每行 `单词<Tab>释义` 或 `单词  音标  释义` 或 `单词 /音标/ 释义`。"""
    entries: list[dict] = []
    errors: list[str] = []
    phonetic_re = re.compile(r"^(/\S.*?/)$")
    for i, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "\t" in line:
            parts = [p.strip() for p in line.split("\t") if p.strip()]
        else:
            parts = [p.strip() for p in re.split(r"\s{2,}", line.strip()) if p.strip()]
        if len(parts) < 2:
            errors.append(f"第 {i} 行：未找到分隔（Tab 或两个以上空格）")
            continue
        word, rest = parts[0], parts[1:]
        phonetic = ""
        m = phonetic_re.match(rest[0]) if rest else None
        if m and len(rest) >= 2:
            phonetic = m.group(1)
            meaning = rest[1]
        else:
            meaning = rest[0]
        if not word or not meaning:
            errors.append(f"第 {i} 行：缺少单词或释义")
            continue
        entries.append({"word": word, "phonetic": phonetic, "meaning": meaning})
    return entries, errors


def _make_slug(conn: sqlite3.Connection, name: str, path: Path) -> str:
    """根据词书名/文件名生成唯一 slug（custom_ 前缀）。"""
    base = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or re.sub(
        r"[^a-z0-9]+", "_", path.stem.lower()
    ).strip("_")
    if not base:
        base = "custom"
    slug = f"custom_{base}"
    n = 2
    while db.get_book(conn, slug):
        slug = f"custom_{base}_{n}"
        n += 1
    return slug


def import_from_file(
    conn: sqlite3.Connection, path: Path, name: str | None = None
) -> tuple[sqlite3.Row, int, list[str]]:
    """导入 CSV/TXT 词表为新词书。

    返回 (词书行, 新增词数, 错误信息)。无有效词条时抛 ValueError。
    """
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"文件不存在：{path}")
    text = path.read_text(encoding="utf-8-sig")
    if path.suffix.lower() in (".csv", ".txt"):
        if path.suffix.lower() == ".csv":
            entries, errors = parse_csv(text)
        else:
            entries, errors = parse_txt(text)
    else:
        # 未知后缀：先按 CSV 试，失败再按 TXT
        entries, errors = parse_csv(text)
        if not entries:
            entries, errors = parse_txt(text)

    # 去重（保留首个）
    seen: set[str] = set()
    unique: list[dict] = []
    for e in entries:
        key = e["word"].lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)

    if not unique:
        raise ValueError("没有可用词条（有效行 ≥ 1 才能建词书）")

    display = name or path.stem
    slug = _make_slug(conn, display, path)
    book_id = db.insert_book(conn, name=display, slug=slug, source="imported")
    added = db.insert_words(conn, book_id, unique)
    conn.commit()
    return db.get_book(conn, slug), added, errors


# ---------------------------------------------------------------- 当前词书


def resolve_current_book(
    conn: sqlite3.Connection, slug: str | None = None
) -> sqlite3.Row | None:
    """取当前词书：显式 slug > settings.current_book > 词书列表第一本。"""
    ensure_builtins(conn)
    if slug:
        return db.get_book(conn, slug)
    current = db.get_setting(conn, "current_book")
    if current:
        book = db.get_book(conn, current)
        if book:
            return book
    books = db.list_books(conn)
    return books[0] if books else None


def use_book(conn: sqlite3.Connection, slug: str) -> None:
    """切换当前词书（词书必须存在）。"""
    if not db.get_book(conn, slug):
        raise ValueError(f"词书不存在：{slug}")
    db.set_setting(conn, "current_book", slug)
    conn.commit()


def unit_progress(conn: sqlite3.Connection, book_id: int) -> list[dict]:
    """按单元统计：词数、已学数（status != new）、已掌握数（mastered）。"""
    rows = conn.execute(
        """
        SELECT w.unit,
               COUNT(*) AS total,
               SUM(CASE WHEN p.status IS NOT NULL AND p.status != 'new' THEN 1 ELSE 0 END)
                   AS learned,
               SUM(CASE WHEN p.status = 'mastered' THEN 1 ELSE 0 END) AS mastered
        FROM words w
        LEFT JOIN word_progress p ON p.word_id = w.id
        WHERE w.book_id = ?
        GROUP BY w.unit
        ORDER BY w.unit
        """,
        (book_id,),
    ).fetchall()
    return [dict(r) for r in rows]
