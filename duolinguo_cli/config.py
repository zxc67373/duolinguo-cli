"""路径常量与全局参数。"""

from __future__ import annotations

from pathlib import Path

# 数据目录（学习进度数据库存放处）
DATA_DIR = Path.home() / ".duolinguo"
DB_FILE = DATA_DIR / "learning.db"

# 内置词书数据
WORDS_DATA_DIR = Path(__file__).parent / "words_data"

# 简化 SM-2 参数
EASE_INIT = 2.5
EASE_MIN = 1.3
EASE_MAX = 3.0
INTERVAL_CAP = 90  # 复习间隔封顶（天）
GRADUATE_INTERVAL = 7  # 间隔达到该天数即视为"已掌握"

# 游戏化参数
DEFAULT_DAILY_GOAL = 20  # 每日目标：新学 + 复习的单词数
UNIT_SIZE = 20  # 每个关卡（单元）的词数
XP_MCQ_CORRECT = 5  # 选择题答对
XP_SPELLING_CORRECT = 10  # 拼写题答对
XP_GOAL_BONUS = 20  # 当日首次达成目标
XP_UNIT_BONUS = 30  # 关卡完成

# 学习会话
DEFAULT_SESSION_COUNT = 20  # 默认一次会话的题目数
