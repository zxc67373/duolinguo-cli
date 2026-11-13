"""出题与判分测试。"""

from __future__ import annotations

import random

import pytest

from duolinguo_cli import quiz

RNG = random.Random(42)


def make_words(n=8, unit_size=4, same_meaning=False):
    """构造测试词表：word01..wordN，unit_size 决定单元划分。"""
    words = []
    for i in range(1, n + 1):
        meaning = "同一个释义" if same_meaning else f"释义{i}"
        words.append(
            {
                "id": i,
                "word": f"word{i:02d}",
                "phonetic": f"/w{i}/",
                "meaning": meaning,
                "example": "",
                "unit": (i - 1) // unit_size + 1,
            }
        )
    return words


# ---------------------------------------------------------------- 题型抽样


def test_pick_qtype_requires_distractors():
    assert quiz.pick_qtype(is_new=True, has_distractors=False, rng=RNG) == quiz.SPELLING
    assert quiz.pick_qtype(is_new=False, has_distractors=False, rng=RNG) == quiz.SPELLING


def test_pick_qtype_valid_types():
    for is_new in (True, False):
        for _ in range(100):
            t = quiz.pick_qtype(is_new, True, rng=RNG)
            assert t in (quiz.MCQ_EN2ZH, quiz.MCQ_ZH2EN, quiz.SPELLING)


def test_pick_qtype_weights_shift():
    """新词拼写题占比应明显低于复习词。"""
    rng = random.Random(7)
    new_spell = sum(
        quiz.pick_qtype(True, True, rng=rng) == quiz.SPELLING for _ in range(1000)
    )
    rev_spell = sum(
        quiz.pick_qtype(False, True, rng=rng) == quiz.SPELLING for _ in range(1000)
    )
    assert new_spell < rev_spell


# ---------------------------------------------------------------- 干扰项


def test_distractors_count_and_exclusion():
    words = make_words(8)
    target = words[0]
    ds = quiz.pick_distractors(target, words, rng=RNG)
    assert len(ds) == 3
    assert all(d["id"] != target["id"] for d in ds)
    assert len({d["id"] for d in ds}) == 3


def test_distractors_prefer_same_unit():
    words = make_words(8, unit_size=4)  # 词 1-4 单元1，5-8 单元2
    target = words[0]  # 单元1
    ds = quiz.pick_distractors(target, words, rng=RNG)
    assert all(d["unit"] == 1 for d in ds)  # 同单元有 3 个候选，正好够


def test_distractors_exclude_same_meaning():
    words = make_words(4, same_meaning=True)
    target = words[0]
    ds = quiz.pick_distractors(target, words, n=5, rng=RNG)
    assert ds == []  # 释义全相同 → 无可用干扰项


def test_distractors_fall_back_to_other_units():
    words = [
        {"id": 1, "word": "a", "meaning": "释义a", "unit": 1},
        {"id": 2, "word": "b", "meaning": "释义b", "unit": 1},
        {"id": 3, "word": "c", "meaning": "释义c", "unit": 2},
        {"id": 4, "word": "d", "meaning": "释义d", "unit": 2},
    ]
    ds = quiz.pick_distractors(words[0], words, n=3, rng=RNG)
    assert len(ds) == 3
    assert {d["unit"] for d in ds} == {1, 2}


# ---------------------------------------------------------------- 构造题目


def test_build_mcq_en2zh():
    words = make_words(8)
    q = quiz.build_question(words[0], words, quiz.MCQ_EN2ZH, rng=RNG)
    assert q.qtype == quiz.MCQ_EN2ZH
    assert q.prompt.startswith("word01")
    assert q.options is not None and len(q.options) == 4
    assert q.options[q.answer_index] == "释义1"
    assert q.answer == "释义1"


def test_build_mcq_zh2en():
    words = make_words(8)
    q = quiz.build_question(words[0], words, quiz.MCQ_ZH2EN, rng=RNG)
    assert q.qtype == quiz.MCQ_ZH2EN
    assert q.prompt == "释义1"
    assert len(q.options) == 4
    assert q.options[q.answer_index] == "word01"


def test_build_degrades_to_spelling_when_thin():
    words = make_words(3)  # 只有 2 个干扰项候选
    q = quiz.build_question(words[0], words, quiz.MCQ_EN2ZH, rng=RNG)
    assert q.qtype == quiz.SPELLING
    assert q.options is None
    assert q.answer == "word01"
    assert q.prompt == "释义1"
    assert q.hint == "/w1/"


def test_build_spelling_direct():
    words = make_words(8)
    q = quiz.build_question(words[2], words, quiz.SPELLING, rng=RNG)
    assert q.qtype == quiz.SPELLING
    assert q.answer == "word03"
    assert q.hint == "/w3/"


# ---------------------------------------------------------------- 判分


@pytest.mark.parametrize(
    ("user", "answer", "expected"),
    [
        ("abandon", "abandon", True),
        ("ABANDON", "abandon", True),
        ("Abandon ", "abandon", True),
        ("a band on", "abandon", True),  # 忽略空白
        ("abandonn", "abandon", False),
        ("", "abandon", False),
        ("   ", "abandon", False),
        ("well known", "well-known", False),  # 连字符敏感
        ("well-known", "well-known", True),
        ("don't", "dont", False),  # 撇号敏感
    ],
)
def test_grade_spelling(user, answer, expected):
    assert quiz.grade_spelling(user, answer) is expected


# ---------------------------------------------------------------- 例句与填空


def test_make_cloze():
    blanked = quiz.make_cloze("We had to abandon the car.  我们不得不弃车。", "abandon")
    assert blanked == "We had to ______ the car.  我们不得不弃车。"
    assert quiz.make_cloze("Nothing here.  无。", "abandon") is None  # 句中无该词
    assert quiz.make_cloze("", "abandon") is None
    # 大小写不敏感
    assert "______" in quiz.make_cloze("Abandon all hope.  放弃吧。", "abandon")


def test_pick_qtype_example_gates_cloze():
    rng = random.Random(3)
    with_ex = {
        quiz.pick_qtype(True, True, has_example=True, rng=rng) for _ in range(300)
    }
    assert quiz.CLOZE in with_ex
    without = {
        quiz.pick_qtype(True, True, has_example=False, rng=rng) for _ in range(300)
    }
    assert quiz.CLOZE not in without
    assert quiz.SPELLING in without


def test_build_cloze():
    words = make_words(8)
    words[0]["example"] = "This is word01 speaking.  这是示例句。"
    q = quiz.build_question(words[0], words, quiz.CLOZE, rng=RNG)
    assert q.qtype == quiz.CLOZE
    assert "______" in q.prompt
    assert "word01" not in q.prompt  # 目标词已挖去
    assert q.options is not None and len(q.options) == 4
    assert q.options[q.answer_index] == "word01"
    assert "释义" in q.note


def test_build_cloze_degrades_to_mcq():
    """句中无目标词（屈折变化）→ 降级英译中。"""
    words = make_words(8)
    words[0]["example"] = "A sentence without the target.  没有目标词。"
    q = quiz.build_question(words[0], words, quiz.CLOZE, rng=RNG)
    assert q.qtype == quiz.MCQ_EN2ZH


def test_build_cloze_degrades_to_spelling():
    """干扰项不足 → 最终降级拼写。"""
    words = make_words(3)
    words[0]["example"] = "word01 appears here.  出现。"
    q = quiz.build_question(words[0], words, quiz.CLOZE, rng=RNG)
    assert q.qtype == quiz.SPELLING


def test_notes_show_context_without_leaking():
    words = make_words(8)
    words[0]["example"] = "You should word01 carefully.  你应该……"
    # 英译中：题干本含目标词 → 原句展示
    q1 = quiz.build_question(words[0], words, quiz.MCQ_EN2ZH, rng=RNG)
    assert q1.note == words[0]["example"]
    # 中译英 / 拼写：挖空展示，答案词不可见
    for qt in (quiz.MCQ_ZH2EN, quiz.SPELLING):
        q = quiz.build_question(words[0], words, qt, rng=RNG)
        assert "______" in q.note
        assert "word01" not in q.note
    # 例句挖不出空 → 不展示（宁缺勿泄）
    words[0]["example"] = "Nothing relevant here.  无关句。"
    q3 = quiz.build_question(words[0], words, quiz.SPELLING, rng=RNG)
    assert q3.note == ""


def test_spelling_is_majority():
    """拼写为主：复习词拼写占比 >50%，新词拼写占比也最高。"""
    rng = random.Random(11)
    for is_new, floor in ((True, 0.40), (False, 0.55)):
        counts = {"spell": 0, "other": 0}
        for _ in range(1000):
            t = quiz.pick_qtype(is_new, True, has_example=True, rng=rng)
            counts["spell" if t == quiz.SPELLING else "other"] += 1
        share = counts["spell"] / 1000
        assert share > floor, f"is_new={is_new} 拼写占比 {share:.0%} 低于预期"


def test_grade_spelling_fullwidth():
    """全角字母/数字（中文输入法）判分为对。"""
    assert quiz.grade_spelling("ＳＴＲＡＴＥＧＹ", "strategy") is True
    assert quiz.grade_spelling("Ｗｏｒｄ０１", "word01") is True
    assert quiz.normalize("？") == "?"  # 全角问号 → 半角
    assert quiz.normalize("１") == "1"  # 全角数字 → 半角
    assert quiz.grade_spelling("strategy", "strategys") is False
