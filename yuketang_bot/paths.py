# -*- coding: utf-8 -*-
"""运行路径：安装目录 vs 可写数据目录"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def get_install_dir() -> Path:
    """可执行文件 / 源码项目所在目录"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_resource_dir() -> Path:
    """打包资源目录（_MEIPASS）或源码根目录"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def _is_writable(directory: Path) -> bool:
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".ykt_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def get_data_dir() -> Path:
    """
    可写数据目录（config / db / profiles / log）。

    - 源码运行：项目根目录
    - 打包后：优先 exe 同目录（便携版）；若不可写（如 Program Files），
      则使用 %LOCALAPPDATA%\\yuketang-bot
    """
    if not getattr(sys, "frozen", False):
        return get_install_dir()

    install_dir = get_install_dir()
    if _is_writable(install_dir):
        return install_dir

    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    data_dir = Path(base) / "yuketang-bot"
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir
