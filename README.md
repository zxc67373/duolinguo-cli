# duolinguo-cli

多邻国风格的命令行背单词工具 —— 闯关 + 间隔重复，中文界面。

- 🎯 **闯关模式**：词书按 20 词/关切分，逐关推进，通关 +30 XP
- 🔁 **智能复习**：简化 SM-2 间隔重复算法，答对拉长间隔、答错明天重来
- 🔥 **游戏化**：每日目标、连胜 streak、经验值 XP、目标首达 +20
- ✍️ **四种题型**：英译中、中译英、拼写、**例句填空**（剑桥词典双语例句挖空选词）；错词会话末强制拼写重练
- 📖 **语境结合**：题面自动带例句——英译中看原句，中译英/拼写显示挖空句（不泄题）
- 📚 **内置词书 8 本共 57247 词**：高中 / 四级 / 六级 / 考研 / 托福 / GRE / COCA 频表 / 牛津高阶进阶；**均按 COCA 词频排序**；支持导入 CSV/TXT

## 安装

```bash
pip install -e .
```

依赖仅 `click` + `rich` + 标准库（Python ≥ 3.10）。

## 快速开始

```bash
duolinguo
```

直接进入**交互式菜单**，之后所有操作都在菜单里选数字完成，无需再记命令（输出为纯命令行风格，无边框，摸鱼友好）：

```
duolinguo  高中核心词 · 关卡 1 · 连胜 3 天 · XP 120 · 今日 ████░░░░░░ 8/20
  1. 开始今日学习（新词 + 复习）
  2. 只复习到期单词
  3. 切换词书
  4. 学习统计
  5. 导入词表（CSV/TXT）
  6. 设置（每日目标等）
  0. 退出
请选择:
```

- 学习结束后自动回到菜单，可连续操作（学完 → 看统计 → 切词书 → 再学）
- 答题：选择题输 `1-4`（全角１-４也认），**或直接输入选项内容**（拼出目标单词同样算选中）；拼写题直接打单词（`?` 渐进提示：先音标、再首字母+长度，**不直接给答案**，半/全角均可）；**拼写答错会当场显示答案、重新输入正确才进入下一题**；随时 `q` 退出当次学习（进度实时保存）

### 子命令（可选，便于脚本/别名）

```bash
duolinguo learn --count 10      # 直接开学，跳过菜单
duolinguo learn --book cet6_core
duolinguo review                # 只复习
duolinguo stats                 # 统计
duolinguo books list            # 词书列表
duolinguo config daily_goal 30  # 改设置
```

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
| 队列 | 每次会话：到期复习占一半名额（优先最早到期），新词顺关卡推进补足，**出题前整体打乱**；一边不够另一边补 |
| 学习顺序 | 所有内置词书按 **COCA 词频**排序：先学 the/be/and 等高频词，关卡 = 词频段（由常用到生僻） |
| 题型权重 | **四类均衡**：英译中 / 中译英 / 拼写 / 例句填空 各 25%（词有例句时；无例句则在其余三类间均分） |
| 语境例句 | 剑桥 CALD 双语例句（覆盖约 70%）：英译中展示原句；中译英/拼写展示**挖空句**防泄题；填空题展示释义 |
| 例句填空 | 句中挖空选词（四选一）；句中无该词（如屈折变化）自动降级英译中，干扰项不足降级拼写 |
| 拼写订正 | 拼写答错当场显示答案+音标，**必须重新输入正确才放行**（空/错输入继续重试）；判分按首次作答记错，订正不重复计日志；**订正完成即该题收尾，不再追加“答错”行** |
| 错词重练 | 答错的词会话末每词再拼写考一次 |
| XP | 选择题对 +5、拼写对 +10；每日目标首达 +20；关卡完成 +30（每关一次） |
| 连胜 | 连续达标天数；今天还没学不算断签（从昨天往回数） |
| 关卡完成 | 单元内 20 词全部学过一次即通关（不要求全部掌握） |

## 数据

- 学习进度：`~/.duolinguo/learning.db`（SQLite，删库即重置，无迁移）
- 内置词书：`duolinguo_cli/words_data/*.json`，首次运行自动入库（按 slug 幂等）

## 内置词书来源

词表数据整理自 [mahavivo/english-wordlists](https://github.com/mahavivo/english-wordlists)，已转换为项目 JSON 格式（`duolinguo_cli/words_data/`，非直接引用原文件）：

| slug | 词书 | 词数 | 源文件 |
|---|---|---|---|
| `highschool_core` | 高中核心词 | 3364 | Highschool_edited（原表仅单词，释义由 NPEE/CET4/COCA 交叉匹配） |
| `cet4_core` | 大学英语四级 | 4539 | CET4_edited |
| `cet6_core` | 六级核心词 | 2219 | CET6_edited（精编版，含义项编号） |
| `kaoyan_core` | 考研英语 | 5391 | NPEE_Wordlist |
| `toefl_core` | 托福词汇 | 4510 | TOEFL |
| `gre_core` | GRE 词汇 | 7724 | GRE_8000_Words |
| `coca_core` | COCA 高频词 | 15851 | COCA_with_translation（按词频排序；86% 单词回填音标） |
| `oald8_core` | 牛津高阶进阶词 | 13649 | OALD8_abridged_edited（繁体释义） |

未收录：`CET_4+6_edited`（纯单词无释义）、`SUM_*`（四六级+托福+GRE 简单合并）、`GRE_abridged`/`GRE_delete_*`（与 GRE_8000 高度重叠）、`COCA_20000`（纯单词版，释义版已收录）。

**例句**来自 [mahavivo/english-dictionary](https://github.com/mahavivo/english-dictionary) 的剑桥高阶学习词典（CALD.txt，英汉双语），按词取首条完整句子合并进词书：四六级/考研/高中覆盖 92–96%，全书约 70%（39665 词有例句）。词序变化/例句补充会自动迁移同步，已有学习进度不受影响。

## 开发

```bash
pytest tests/ -q    # 79 个测试
ruff check .
```

技术栈：Python + click + rich + sqlite3，核心算法（SRS / 出题 / 判分 / 队列 / 游戏化）均为纯函数，便于单测。
