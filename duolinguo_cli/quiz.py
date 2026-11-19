"""出题与判分：题型抽样、选择题干扰项、拼写判分（纯函数）。"""

from __future__ import annotations

import random
import re
import unicodedata
from dataclasses import dataclass

MCQ_EN2ZH = "mcq_en2zh"  # 看英文选中文
MCQ_ZH2EN = "mcq_zh2en"  # 看中文选英文
SPELLING = "spelling"  # 拼写
CLOZE = "cloze"  # 例句填空（句中挖空，选词）

# 题型权重：四类题均衡（各 25%）；例句填空仅在词有例句时参与，缺例句自动重分配
WEIGHTS = {MCQ_EN2ZH: 0.25, MCQ_ZH2EN: 0.25, SPELLING: 0.25, CLOZE: 0.25}

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
    hint: str = ""  # 目标词音标（提示阶梯用）


def pick_qtype(
    is_new: bool,
    has_distractors: bool,
    has_example: bool = False,
    allowed: list[str] | None = None,
    rng: random.Random | None = None,
) -> str:
    """按权重抽题型（四类均衡；allowed 限定本批允许的题型子集）。

    词书太小（凑不齐干扰项）降级拼写；无例句不抽填空、权重自动重分配。
    """
    if not has_distractors:
        return SPELLING
    rng = rng or random
    weights = {
        t: w for t, w in WEIGHTS.items() if allowed is None or t in allowed
    }
    if not has_example:
        weights.pop(CLOZE, None)
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


def example_lines(example: str) -> list[str]:
    """例句字段按行拆分（首行=主例句，其余=另例）。"""
    return [ln.strip() for ln in (example or "").split("\n") if ln.strip()]


def make_cloze(example: str, word: str) -> str | None:
    """把例句中的目标词挖空；句中无该词（屈折变化等）返回 None。

    多行例句时取第一句含目标词的行。
    """
    if not example or not word:
        return None
    lines = example_lines(example)
    pattern = re.compile(rf"\b{re.escape(word)}\b", re.IGNORECASE)
    target_line = next((ln for ln in lines if pattern.search(ln)), None)
    if target_line is None:
        return None
    return pattern.sub("______", target_line, count=1)


def hint_ladder(q: Question) -> list[str]:
    """渐进提示阶梯（按题型）：第 n 次按 ? 给第 n 级，用尽为止。

    - 英译中：①英文例句 → ②句子翻译 → ③其他例句 → ④首字母+长度
    - 中译英/拼写：①音标 → ②挖空句 → ③其他例句 → ④首字母+长度
    - 例句填空：①释义 → ②音标 → ③其他例句 → ④首字母+长度
    缺例句/音标/另例时自动跳过对应级别。
    """
    w = q.word
    word = w["word"]
    phon = w.get("phonetic") or q.hint or ""
    example = w.get("example") or ""
    meaning = w.get("meaning", "")
    form = f"首字母 {word[0]}，共 {len(word)} 个字母：{word[0]}_{'_' * (len(word) - 1)}"

    lines = example_lines(example)
    primary = lines[0] if lines else ""
    others = lines[1:]
    parts = re.split(r"\s{2,}", primary, maxsplit=1) if primary else []
    sent_en = parts[0].strip() if parts else ""
    sent_zh = parts[1].strip() if len(parts) > 1 else ""
    blanked = make_cloze(example, word) or ""
    more = "\n".join(f"另例：{ln}" for ln in others) if others else ""

    if q.qtype == MCQ_EN2ZH:
        ladder = []
        if sent_en:
            ladder.append(sent_en)
        if sent_zh:
            ladder.append(f"句子翻译：{sent_zh}")
        if more:
            ladder.append(more)
        ladder.append(form)
        return ladder
    if q.qtype in (MCQ_ZH2EN, SPELLING):
        ladder = []
        if phon:
            ladder.append(f"音标 {phon}")
        if blanked:
            ladder.append(blanked)
        if more:
            ladder.append(more)
        ladder.append(form)
        return ladder
    # CLOZE
    ladder = []
    if meaning:
        ladder.append(f"释义：{meaning}")
    if phon:
        ladder.append(f"音标 {phon}")
    if more:
        ladder.append(more)
    ladder.append(form)
    return ladder


# 「新词性 + 编号」边界（如 "…分配 n. 1. 发行物…"），按此先分段再拆义项
_POS_NUM_SPLIT = re.compile(
    r"\s+(?=(?:n|v|vt|vi|adj|ad|adv|prep|conj|pron|num|int|aux|art|abbr)\.\s*\d+\.)"
)


def senses_of(meaning: str) -> list[str]:
    """把合并释义拆成义项列表。

    多词性结构（「v. 1.… n. 1.…」）先按新词性+编号边界分段，
    段内再按编号/分号切——避免在「3. 分配 n. 1.」中间切出残片。
    """
    if not meaning:
        return []
    out: list[str] = []
    for section in _POS_NUM_SPLIT.split(meaning):
        section = section.strip()
        if not section:
            continue
        parts = [p.strip() for p in re.split(r"\s*\d+\.\s*", section) if p.strip()]
        # 孤立词性前缀（"n." / "vt."）并入其后第一段
        if len(parts) >= 2 and re.fullmatch(r"[a-zA-Z]{1,4}\.?", parts[0]):
            parts[1] = f"{parts[0]} {parts[1]}"
            parts = parts[1:]
        if len(parts) < 2:
            parts = [p.strip() for p in re.split(r"[;；]", section) if len(p.strip()) >= 2]
        out.extend(parts if parts else [section])
    # 段内完全拆不出编号/分号时，退化为整体
    if not out:
        return [meaning]
    # 合并后仍含未拆开的多词性粘连（如 "分配 n." 残留）时不再细分（保持简单）
    return out


def _pick_sense(meaning: str, rng: random.Random) -> str:
    """随机取一个义项（单词义时即整串）。"""
    senses = senses_of(meaning)
    return rng.choice(senses) if len(senses) > 1 else senses[0]


def build_question(
    target: dict,
    candidates: list[dict],
    qtype: str,
    rng: random.Random | None = None,
) -> Question:
    """构造一道题。例句填空造不出/干扰项不足 3 个时自动降级。"""
    rng = rng or random
    word_text = target["word"]
    phonetic = target.get("phonetic", "")
    meaning = target["meaning"]
    example = target.get("example", "")

    if qtype == CLOZE:
        blanked = make_cloze(example, word_text)
        if blanked:
            distractors = pick_distractors(target, candidates, rng=rng)
            if len(distractors) >= DISTRACTOR_COUNT:
                options = [d["word"] for d in distractors] + [word_text]
                rng.shuffle(options)
                return Question(
                    qtype=CLOZE,
                    word=dict(target),
                    prompt=blanked,
                    answer=word_text,
                    options=options,
                    answer_index=options.index(word_text),
                    hint=phonetic,
                )
        qtype = MCQ_EN2ZH  # 造不出填空 → 降级英译中（再判断干扰项）

    if qtype in (MCQ_EN2ZH, MCQ_ZH2EN):
        distractors = pick_distractors(target, candidates, rng=rng)
        if len(distractors) >= DISTRACTOR_COUNT:
            if qtype == MCQ_EN2ZH:
                prompt = f"{word_text}  {phonetic}".strip()
                # 义项级出题：正确项随机取目标词的一个义项，干扰项各取其一个义项
                answer = _pick_sense(meaning, rng)
                options = [_pick_sense(d["meaning"], rng) for d in distractors] + [answer]
                if len({normalize(o) for o in options}) < DISTRACTOR_COUNT + 1:
                    # 义项撞车 → 回退整义出题
                    answer = meaning
                    options = [d["meaning"] for d in distractors] + [meaning]
            else:
                # 提示用单个义项（更精细），选项仍是单词
                prompt = _pick_sense(meaning, rng)
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
                hint=phonetic,
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
    """判分/输入归一化：全角→半角（NFKC，兼容中文输入法）、转小写、去全部空白。

    连字符/撇号保持敏感（well-known ≠ wellknown）。
    """
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text).lower())


def grade_spelling(user_input: str, answer: str) -> bool:
    """拼写判分：忽略大小写、全半角与空白；空输入视为放弃（判错）。"""
    if not user_input.strip():
        return False
    return normalize(user_input) == normalize(answer)
