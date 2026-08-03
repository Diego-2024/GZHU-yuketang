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


def run():
    try:
        import PyInstaller.__main__
    except ImportError as e:
        print("请先安装 PyInstaller: pip install pyinstaller")
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

    PyInstaller.__main__.run(args)

    # 打包完成后把示例配置也放到 dist 目录，方便用户
    dist_dir = ROOT / "dist"
    if dist_dir.exists() and example_config.exists():
        shutil.copy(example_config, dist_dir / "config.example.yaml")
        print(f"\n已复制示例配置到: {dist_dir / 'config.example.yaml'}")

    print(f"\n打包完成: {dist_dir / 'yuketang-bot.exe'}")


if __name__ == "__main__":
    run()
