# duolinguo-cli

多邻国风格的命令行背单词工具 —— 闯关 + 间隔重复，中文界面。

## 安装

```bash
pip install -e .
```

## 使用

```bash
duolinguo                # 开始今日学习（等同 learn）
duolinguo learn          # 新词 + 到期复习混合学习
duolinguo review         # 只做到期复习
duolinguo stats          # 学习统计：连胜、XP、关卡进度
duolinguo books list     # 查看词书
duolinguo books import 我的词表.csv   # 导入自定义词表
duolinguo config         # 查看/修改设置
```

（详细用法施工中……）

## 词表导入格式

CSV（每行 `单词,释义`，可选 `单词,音标,释义`）：

```csv
abandon,/əˈbændən/,v. 放弃；抛弃
```

TXT（每行 `单词<Tab>释义`）：

```
abandon	v. 放弃；抛弃
```

## 开发

```bash
pytest tests/ -q
ruff check .
```
