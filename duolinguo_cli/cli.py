"""CLI 入口：click group 与子命令。"""

from __future__ import annotations

import click

from . import __version__


@click.group(invoke_without_command=True)
@click.version_option(version=__version__, prog_name="duolinguo")
def cli() -> None:
    """duolinguo — 多邻国风格的命令行背单词工具。"""
