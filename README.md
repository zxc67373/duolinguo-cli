# duolinguo-cli

多邻国风格的命令行背单词工具 —— 闯关 + 间隔重复，中文界面。

- 🎯 **闯关模式**：词书按 20 词/关切分，逐关推进，通关 +30 XP
- 🔁 **智能复习**：简化 SM-2 间隔重复算法，答对拉长间隔、答错明天重来
- 🔥 **游戏化**：每日目标、连胜 streak、经验值 XP、目标首达 +20
- ✍️ **两种题型**：选择题（英译中 / 中译英）+ 拼写题；错词会话末强制拼写重练
- 📚 **内置词书**：高中核心词 3364 词、大学英语四级 4539 词；支持导入 CSV/TXT

## 安装

```bash
pip install -e .
```

依赖仅 `click` + `rich` + 标准库（Python ≥ 3.10）。

## 快速开始

```bash
duolinguo                 # 开始今日学习（等同 learn）
duolinguo learn           # 新词 + 到期复习混合
duolinguo learn --count 10      # 本次 10 题
duolinguo learn --goal 30       # 设置每日目标为 30（并保存）
duolinguo review          # 只做到期复习
duolinguo stats           # 连胜 / XP / 每日进度 / 关卡进度
```

学习中：选择题输入 `1-4` 作答；拼写题直接输入单词（`?` 看音标提示、直接回车放弃）；随时输入 `q` 退出（进度实时保存）。

## 词书管理

```bash
duolinguo books list               # 查看所有词书
duolinguo books show cet4_core     # 各关卡进度
duolinguo books use cet4_core      # 切换当前词书
duolinguo books import 词汇表.csv   # 导入自定义词表
duolinguo books import 词汇表.txt --name "我的词表"
```

### 导入格式

CSV（`word,meaning` 或 `word,phonetic,meaning`，可选第 4 列例句；首行表头自动跳过）：

```csv
abandon,/əˈbændən/,v. 放弃；抛弃
ability,n. 能力
```

TXT（每行 `单词<Tab>释义`，或 `单词 /音标/ 释义`；`#` 开头为注释）：

```
abandon	v. 放弃；抛弃
ability	/əˈbɪləti/	n. 能力
```

坏行会跳过并报告行号，至少 1 条有效词条即可建词书。

## 设置

```bash
duolinguo config                       # 查看全部设置
duolinguo config daily_goal            # 查看每日目标（默认 20）
duolinguo config daily_goal 30         # 修改每日目标
duolinguo config current_book cet4_core
```

## 学习机制

| 机制 | 说明 |
|---|---|
| 复习调度 | 简化 SM-2：答对 reps 阶梯 1→3→×ease（封顶 90 天），ease 2.5±（1.3–3.0）；间隔 ≥7 天毕业为「已掌握」；答错回炉、明天重来 |
| 队列 | 每次会话：到期复习占一半名额（优先最早到期），新词顺关卡推进补足；一边不够另一边补 |
| 题型权重 | 新词 45% 英译中 / 30% 中译英 / 25% 拼写；复习 35/25/40（偏拼写）；词书太小自动全拼写 |
| 错词重练 | 答错的词会话末每词强制拼写订正一次 |
| XP | 选择题对 +5、拼写对 +10；每日目标首达 +20；关卡完成 +30（每关一次） |
| 连胜 | 连续达标天数；今天还没学不算断签（从昨天往回数） |
| 关卡完成 | 单元内 20 词全部学过一次即通关（不要求全部掌握） |

## 数据

- 学习进度：`~/.duolinguo/learning.db`（SQLite，删库即重置，无迁移）
- 内置词书：`duolinguo_cli/words_data/*.json`，首次运行自动入库（按 slug 幂等）

## 内置词书来源

词表数据整理自 [mahavivo/english-wordlists](https://github.com/mahavivo/english-wordlists)（已转换为项目 JSON 格式，非直接引用原文件）：

- `highschool_core` — 高中英语参考词汇表（3446 词），释义由 NPEE / CET4 / COCA 词典交叉匹配（覆盖 3364 词）
- `cet4_core` — 大学英语四级大纲词汇（4539 词，含音标与释义）

## 开发

```bash
pytest tests/ -q    # 79 个测试
ruff check .
```

技术栈：Python + click + rich + sqlite3，核心算法（SRS / 出题 / 判分 / 队列 / 游戏化）均为纯函数，便于单测。
