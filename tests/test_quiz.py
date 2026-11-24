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


def test_pick_qtype_balanced():
    """四类题均衡：每种占比在 18%-32% 之间（1000 次抽样）。"""
    rng = random.Random(7)
    for is_new in (True, False):
        counts = {
            t: 0 for t in (quiz.MCQ_EN2ZH, quiz.MCQ_ZH2EN, quiz.SPELLING, quiz.CLOZE)
        }
        for _ in range(1000):
            counts[quiz.pick_qtype(is_new, True, has_example=True, rng=rng)] += 1
        for t, c in counts.items():
            assert 180 <= c <= 320, f"is_new={is_new} {t} 占比 {c/10:.0f}% 不均衡"
        # 四类都必须出现
        assert all(c > 0 for c in counts.values())


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
    assert q.hint == "/w1/"  # 音标进提示阶梯
    assert quiz.hint_ladder(q)[0].startswith("释义")


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


def test_hint_ladder_progressive_and_no_leak():
    """渐进提示阶梯：逐级给、答案词不提前泄露。"""
    words = make_words(8)
    words[0]["example"] = "You should word01 carefully.  你应该仔细……"

    # 英译中：①英文例句 → ②句子翻译 → ③首字母（逐级）
    q1 = quiz.build_question(words[0], words, quiz.MCQ_EN2ZH, rng=RNG)
    ladder1 = quiz.hint_ladder(q1)
    assert ladder1[0] == "You should word01 carefully."  # L1 只有英文句
    assert ladder1[1].startswith("句子翻译")  # L2 才给翻译
    assert "word01" not in ladder1[2]  # L3 词形提示不含完整词

    # 中译英/拼写：①音标 → ②挖空句 → ③首字母，任何一级不含完整答案词
    for qt in (quiz.MCQ_ZH2EN, quiz.SPELLING):
        q = quiz.build_question(words[0], words, qt, rng=RNG)
        ladder = quiz.hint_ladder(q)
        assert ladder[0].startswith("音标")
        assert "______" in ladder[1]
        assert all("word01" not in step for step in ladder)

    # 填空：①释义 → ②音标 → ③首字母
    qc = quiz.build_question(words[0], words, quiz.CLOZE, rng=RNG)
    lc = quiz.hint_ladder(qc)
    assert lc[0].startswith("释义")
    assert lc[1].startswith("音标")
    assert "首字母" in lc[2]

    # 无例句 → 挖空句级别自动跳过；未挖空的句子绝不出现
    words[0]["example"] = "Nothing relevant here.  无关句。"
    qs = quiz.build_question(words[0], words, quiz.SPELLING, rng=RNG)
    ls = quiz.hint_ladder(qs)
    assert len(ls) == 2  # 音标 + 词形
    assert ls[0].startswith("音标") and "首字母" in ls[1]
    assert not any("无关句" in s for s in ls)


def test_grade_spelling_fullwidth():
    """全角字母/数字（中文输入法）判分为对。"""
    assert quiz.grade_spelling("ＳＴＲＡＴＥＧＹ", "strategy") is True
    assert quiz.grade_spelling("Ｗｏｒｄ０１", "word01") is True
    assert quiz.normalize("？") == "?"  # 全角问号 → 半角
    assert quiz.normalize("１") == "1"  # 全角数字 → 半角
    assert quiz.grade_spelling("strategy", "strategys") is False


def test_pick_qtype_allowed_subset():
    """allowed 限定本批题型：抽样只出允许的类型。"""
    rng = random.Random(5)
    allowed = [quiz.SPELLING, quiz.CLOZE]
    for is_new in (True, False):
        for _ in range(200):
            t = quiz.pick_qtype(is_new, True, has_example=True, allowed=allowed, rng=rng)
            assert t in allowed
    # 无例句时填空被剔除 → 只剩另一允许类型
    for _ in range(50):
        t = quiz.pick_qtype(True, True, has_example=False, allowed=allowed, rng=rng)
        assert t == quiz.SPELLING


# ---------------------------------------------------------------- 义项级出题


def test_senses_of_numbered():
    s = quiz.senses_of("n. 1. 战略(学)，策略 2. 兵法 3. 谋略")
    assert len(s) >= 2
    assert s[0].startswith("n.")  # 词性前缀并入首义项
    assert any("兵法" in x for x in s)


def test_senses_of_semicolon():
    s = quiz.senses_of("vt.离弃,丢弃;遗弃,抛弃;放弃")
    assert len(s) == 3
    assert s[0].startswith("vt.")


def test_senses_of_single():
    assert quiz.senses_of("释义1") == ["释义1"]
    assert quiz.senses_of("") == []


def test_build_mcq_en2zh_full_meaning():
    """英译中：正确项=完整释义（一次性给出该词所有意思），干扰项同样为全义。"""
    words = make_words(8)
    words[0]["meaning"] = "n. 1. 概念，观念 2. 想法，见解"
    q = quiz.build_question(words[0], words, quiz.MCQ_EN2ZH, rng=random.Random(9))
    assert q.answer == words[0]["meaning"]  # 选项即全义
    assert len(q.options) == 4
    assert len({quiz.normalize(o) for o in q.options}) == 4  # 无撞车
    assert q.options[q.answer_index] == q.answer
    # 干扰项也是各自词的完整释义
    for i, opt in enumerate(q.options):
        if i != q.answer_index:
            meanings = {w["meaning"] for w in words}
            assert opt in meanings


def test_build_zh2en_prompt_is_sense():
    words = make_words(8)
    words[0]["meaning"] = "vt. 1. 打，击 2. 碰撞"
    q = quiz.build_question(words[0], words, quiz.MCQ_ZH2EN, rng=random.Random(4))
    assert q.prompt in quiz.senses_of(words[0]["meaning"])
    assert q.answer == "word01"


def test_senses_of_multi_pos_no_fragments():
    """多词性结构（v. 1.… n. 1.…）不得切出「分配 n.」类残片。"""
    m = ("v. 1. (报刊等)发行，发布，颁布 2. 排出，(使)流出 3. 分配 "
         "n. 1. 发行物，(报刊)期号 2. 问题，议题，争论点 3. 河口，出口")
    senses = quiz.senses_of(m)
    assert "分配" in senses
    assert not any(s.endswith("n.") or s.endswith("v.") for s in senses)  # 无残片
    assert any(s.startswith("n.") for s in senses)  # 第二词性段保留
    assert all("1." not in s and "2." not in s for s in senses)  # 编号已消费


def test_multi_line_example_cloze_and_hints():
    """多行例句：挖空取含目标词的行；提示阶梯含「另例」级。"""
    words = make_words(8)
    words[0]["example"] = (
        "You should word01 carefully.  你应该仔细。\n"
        "He will word01 the plan tomorrow.  他明天会执行计划。\n"
        "They word01 the issue yesterday.  他们昨天处理了该问题。"
    )
    qz = quiz.build_question(words[0], words, quiz.CLOZE, rng=RNG)
    assert "word01" not in qz.prompt  # 主例句挖空
    assert "He will" not in qz.prompt  # 只挖第一句，不拼接

    ladder = quiz.hint_ladder(qz)
    more_idx = next(i for i, s in enumerate(ladder) if s.startswith("另例："))
    assert "He will word01" in ladder[more_idx]  # 另例完整给出（含词）
    assert "word01" not in ladder[-1]  # 词形仍在最后且不泄答案

    # 英译中同样有另例级
    q1 = quiz.build_question(words[0], words, quiz.MCQ_EN2ZH, rng=RNG)
    l1 = quiz.hint_ladder(q1)
    assert any(s.startswith("另例：") for s in l1)
    # 无另例的词 → 阶梯不含「另例」
    words[1]["example"] = "Only one sentence here.  只有一句。"
    q2 = quiz.build_question(words[1], words, quiz.MCQ_ZH2EN, rng=RNG)
    assert not any(s.startswith("另例：") for s in quiz.hint_ladder(q2))


def test_senses_of_double_bar_phrase():
    """「||」短语边界切分：容纳 || admit of … 各自成义项。"""
    m = "vt. (指在一范围内)可容纳(某人或某事) || admit of …容纳得下，有…的余地"
    senses = quiz.senses_of(m)
    assert len(senses) == 2
    assert "可容纳" in senses[0]
    assert "admit of" in senses[1]
    assert "||" not in "".join(senses)


def test_zh2en_prompt_blanks_answer_word_in_phrase():
    """义项含目标词短语（admit of）时，题干挖空防泄题。"""
    words = make_words(8)
    words[0]["word"] = "admit"
    words[0]["meaning"] = "vt. 承认 || admit of …容纳得下"
    q = quiz.build_question(words[0], words, quiz.MCQ_ZH2EN, rng=random.Random(6))
    assert q.answer == "admit"
    assert "admit" not in q.prompt.lower().replace("______", "")  # 题干不露答案


def test_import_enrichment_source_index():
    """_enrichment_index 从内置词书提供音标/例句回填数据。"""
    from duolinguo_cli import books

    idx = books._enrichment_index()
    if not idx:
        pytest.skip("无内置词书")
    # abandon 在 CET4 内且有音标
    if "abandon" in idx:
        assert idx["abandon"]["phonetic"]


def test_hint_ladder_includes_all_meanings():
    """中译英题干单义 → 提示给「全部意思」；英译中选项本身就是全义不再重复给。"""
    words = make_words(8)
    words[0]["meaning"] = "n. 1. 资产，财产 2. 有价值的特性(技能)"

    # 英译中：选项=完整释义 → 阶梯无需「全部意思」级
    q1 = quiz.build_question(words[0], words, quiz.MCQ_EN2ZH, rng=RNG)
    assert q1.answer == words[0]["meaning"]
    assert not any(s.startswith("全部意思：") for s in quiz.hint_ladder(q1))

    # 中译英：题干单义 → 补全义
    q2 = quiz.build_question(words[0], words, quiz.MCQ_ZH2EN, rng=RNG)
    assert any(s.startswith("全部意思：") for s in quiz.hint_ladder(q2))

    # 单义词英译中：全义==答案 → 不给（避免直接送答案）
    words[1]["meaning"] = "唯一释义"
    q3 = quiz.build_question(words[1], words, quiz.MCQ_EN2ZH, rng=RNG)
    assert not any(s.startswith("全部意思：") for s in quiz.hint_ladder(q3))

    # 拼写题：题面本就是完整释义 → 不重复
    q4 = quiz.build_question(words[0], words, quiz.SPELLING, rng=RNG)
    assert not any(s.startswith("全部意思：") for s in quiz.hint_ladder(q4))


def test_senses_single_number_not_reverted():
    """单编号义项不得回退成带编号原文（partition 案例）。"""
    m = "v. 1. 分裂，分割 2. 分隔，隔开 n. 1. 分割，隔开"
    senses = quiz.senses_of(m)
    assert "n. 分割，隔开" in senses
    assert not any("1." in s or "2." in s for s in senses)
    # 纯编号开头（belladonna 案例）也要去编号
    assert quiz.senses_of("1. 2.顛茄製劑") == ["顛茄製劑"]


def test_senses_no_space_pos_boundary():
    """无空格词性粘连可切（endure「容忍a.」、use「耗费 n.」案例）。"""
    s1 = quiz.senses_of("vt.用；耗费 n.用")
    assert "vt.用" in s1 and "n.用" in s1
    s2 = quiz.senses_of(
        "vt.   (耐心地) 忍受,容忍a.  忍耐b.  对<做…事>忍耐,忍受<做…事> vi."
    )
    assert len(s2) == 2
    assert s2[0].startswith("vt.")
    assert s2[1].startswith("a.")
    assert not any(s.strip() == "vi." for s in s2)  # 孤词性残片被丢弃
