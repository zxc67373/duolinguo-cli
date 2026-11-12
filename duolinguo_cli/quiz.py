"""出题与判分：题型抽样、选择题干扰项、拼写判分（纯函数）。"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

MCQ_EN2ZH = "mcq_en2zh"  # 看英文选中文
MCQ_ZH2EN = "mcq_zh2en"  # 看中文选英文
SPELLING = "spelling"  # 拼写

# 题型权重：新词偏易、复习偏拼写
NEW_WEIGHTS = {MCQ_EN2ZH: 0.45, MCQ_ZH2EN: 0.30, SPELLING: 0.25}
REVIEW_WEIGHTS = {MCQ_EN2ZH: 0.35, MCQ_ZH2EN: 0.25, SPELLING: 0.40}

DISTRACTOR_COUNT = 3  # 选择题干扰项数量


@dataclass
class Question:
    """一道题的完整描述。"""

    qtype: str
    word: dict  # 目标词条 {id, word, phonetic, meaning, example, unit}
    prompt: str  # 题干
    answer: str  # 正确答案文本
    options: list[str] | None = None  # 选项（选择题）
    answer_index: int | None = None  # 正确选项下标（选择题）
    hint: str = ""  # 拼写题提示（音标）


def pick_qtype(is_new: bool, has_distractors: bool, rng: random.Random | None = None) -> str:
    """按权重抽题型；词书太小（凑不齐干扰项）时降级为拼写。"""
    if not has_distractors:
        return SPELLING
    rng = rng or random
    weights = NEW_WEIGHTS if is_new else REVIEW_WEIGHTS
    types = list(weights)
    return rng.choices(types, weights=[weights[t] for t in types], k=1)[0]


def pick_distractors(
    target: dict,
    candidates: list[dict],
    n: int = DISTRACTOR_COUNT,
    rng: random.Random | None = None,
) -> list[dict]:
    """从同词书选 n 个干扰项：排除自身与同释义项，优先同单元（关卡邻近）。"""
    rng = rng or random
    others = [c for c in candidates if c["id"] != target["id"]]
    distinct = [c for c in others if c["meaning"] != target["meaning"]]
    same_unit = [c for c in distinct if c["unit"] == target["unit"]]
    rest = [c for c in distinct if c["unit"] != target["unit"]]
    rng.shuffle(same_unit)
    rng.shuffle(rest)
    return (same_unit + rest)[:n]


def build_question(
    target: dict,
    candidates: list[dict],
    qtype: str,
    rng: random.Random | None = None,
) -> Question:
    """构造一道题。干扰项不足 3 个时自动降级为拼写题。"""
    rng = rng or random
    word_text = target["word"]
    phonetic = target.get("phonetic", "")
    meaning = target["meaning"]

    if qtype in (MCQ_EN2ZH, MCQ_ZH2EN):
        distractors = pick_distractors(target, candidates, rng=rng)
        if len(distractors) >= DISTRACTOR_COUNT:
            if qtype == MCQ_EN2ZH:
                prompt = f"{word_text}  {phonetic}".strip()
                answer = meaning
                options = [d["meaning"] for d in distractors] + [meaning]
            else:
                prompt = meaning
                answer = word_text
                options = [d["word"] for d in distractors] + [word_text]
            rng.shuffle(options)
            return Question(
                qtype=qtype,
                word=dict(target),
                prompt=prompt,
                answer=answer,
                options=options,
                answer_index=options.index(answer),
            )
        qtype = SPELLING  # 凑不齐干扰项，降级

    return Question(
        qtype=SPELLING,
        word=dict(target),
        prompt=meaning,
        answer=word_text,
        options=None,
        answer_index=None,
        hint=phonetic,
    )


def normalize(text: str) -> str:
    """判分归一化：转小写并去掉全部空白（连字符/撇号保持敏感）。"""
    return re.sub(r"\s+", "", text.strip().lower())


def grade_spelling(user_input: str, answer: str) -> bool:
    """拼写判分：忽略大小写与空白；空输入视为放弃（判错）。"""
    if not user_input.strip():
        return False
    return normalize(user_input) == normalize(answer)
