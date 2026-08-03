# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本

运行：
    python build.py

输出：
    dist/yuketang-bot.exe

首次运行前请确保依赖已安装：
    pip install -r requirements.txt
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", "replace").decode("ascii"))


def run():
    try:
        import PyInstaller.__main__
    except ImportError as e:
        _safe_print("Please install PyInstaller: pip install pyinstaller")
        raise e

    static_dir = ROOT / "yuketang_bot" / "web" / "static"
    example_config = ROOT / "config.example.yaml"
    icon_path = ROOT / "assets" / "icon.ico"

    sep = os.pathsep

    add_data = [
        f"{static_dir}{sep}yuketang_bot/web/static",
        f"{example_config}{sep}.",
    ]

    args = [
        str(ROOT / "yuketang_bot" / "launcher.py"),
        "--name",
        "yuketang-bot",
        "--onefile",
        "--windowed",
        "--clean",
        "--noconfirm",
    ]

    for item in add_data:
        args.extend(["--add-data", item])

    if icon_path.exists():
        args.extend(["--icon", str(icon_path)])

    # Avoid UnicodeEncodeError on CI consoles (cp1252)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    PyInstaller.__main__.run(args)

    # 打包完成后把示例配置也放到 dist 目录，方便用户
    dist_dir = ROOT / "dist"
    if dist_dir.exists() and example_config.exists():
        shutil.copy(example_config, dist_dir / "config.example.yaml")
        _safe_print(f"\nCopied example config to: {dist_dir / 'config.example.yaml'}")

    _safe_print(f"\nBuild done: {dist_dir / 'yuketang-bot.exe'}")


if __name__ == "__main__":
    run()
