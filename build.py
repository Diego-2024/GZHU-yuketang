# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本

运行：
    python build.py

输出：
    dist/yuketang-bot.exe
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent

HIDDEN_IMPORTS = [
    "uvicorn",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
    "fastapi",
    "starlette",
    "starlette.responses",
    "starlette.staticfiles",
    "pydantic",
    "yaml",
    "pystray",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "yuketang_bot",
    "yuketang_bot.web",
    "yuketang_bot.web.app",
    "yuketang_bot.web.jobs",
    "yuketang_bot.web.schemas",
    "yuketang_bot.config",
    "yuketang_bot.store",
    "yuketang_bot.browser",
    "yuketang_bot.discover",
    "yuketang_bot.runner",
    "yuketang_bot.api",
    "yuketang_bot.models",
    "yuketang_bot.utils",
    "DrissionPage",
]


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
        "--collect-all",
        "uvicorn",
        "--collect-all",
        "fastapi",
        "--collect-all",
        "starlette",
        "--collect-submodules",
        "yuketang_bot",
    ]

    for item in add_data:
        args.extend(["--add-data", item])

    for mod in HIDDEN_IMPORTS:
        args.extend(["--hidden-import", mod])

    if icon_path.exists():
        args.extend(["--icon", str(icon_path)])

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    PyInstaller.__main__.run(args)

    dist_dir = ROOT / "dist"
    if dist_dir.exists() and example_config.exists():
        shutil.copy(example_config, dist_dir / "config.example.yaml")
        _safe_print(f"\nCopied example config to: {dist_dir / 'config.example.yaml'}")

    _safe_print(f"\nBuild done: {dist_dir / 'yuketang-bot.exe'}")


if __name__ == "__main__":
    run()
