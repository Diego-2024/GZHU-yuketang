# -*- coding: utf-8 -*-
"""
双击启动器：托盘图标 + 自动打开浏览器控制台

打包后由 PyInstaller 调用，运行效果：
1. 双击 exe，复制 config.example.yaml -> config.yaml（首次）
2. 在后台启动 FastAPI 服务
3. 自动打开浏览器访问 http://127.0.0.1:18765/
4. 在系统托盘显示图标，右键可「打开控制台」/「退出」
"""

from __future__ import annotations

import os
import shutil
import sys
import threading
import time
import webbrowser
from pathlib import Path

DEFAULT_PORT = 18765


def get_app_dir() -> Path:
    """可执行文件所在目录（即用户工作目录）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_resource_dir() -> Path:
    """PyInstaller 解压目录或源码目录"""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def ensure_config() -> str:
    """确保 config.yaml 存在，不存在则从 bundled 示例复制"""
    app_dir = get_app_dir()
    config_path = app_dir / "config.yaml"
    if config_path.exists():
        return str(config_path)

    example_path = app_dir / "config.example.yaml"
    if not example_path.exists():
        bundled = get_resource_dir() / "config.example.yaml"
        if bundled.exists():
            example_path = bundled

    if example_path.exists():
        shutil.copy(example_path, config_path)
        print(f"已生成默认配置: {config_path}")
    else:
        # 兜底：生成一个最小配置
        config_path.write_text(
            "# 雨课堂通用刷课工具配置\n"
            "base_url: https://www.yuketang.cn\n"
            "home_url: https://www.yuketang.cn/v2/web/index\n"
            "accounts:\n"
            "  - name: 账号1\n"
            "    profile: account_1\n"
            "loop:\n"
            "  heartbeat_count: 10\n"
            "  heartbeat_interval: 5\n"
            "  playback_rate: 1\n"
            "  batch_sleep: 2\n"
            "  target_rate: 0.95\n"
            "  max_batches: 200\n",
            encoding="utf-8",
        )
        print(f"已生成兜底配置: {config_path}")

    return str(config_path)


def _create_tray_image():
    """用 Pillow 生成一个简单的天蓝色托盘图标"""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (135, 206, 250, 255))
    draw = ImageDraw.Draw(img)
    # 白色书本/屏幕形状
    draw.rounded_rectangle(
        [size // 5, size // 5, 4 * size // 5, 4 * size // 5],
        radius=8,
        fill=(255, 255, 255, 255),
        outline=(70, 130, 180, 255),
        width=3,
    )
    # 蓝色横线模拟文字
    for i, y in enumerate([size // 2 - 6, size // 2, size // 2 + 6, size // 2 + 12]):
        width = 28 - i * 4
        draw.line(
            [(size - width) // 2, y, (size + width) // 2, y],
            fill=(70, 130, 180, 255),
            width=2,
        )
    return img


def _run_tray(port: int = DEFAULT_PORT):
    import pystray

    url = f"http://127.0.0.1:{port}/"

    def open_console(icon, item):
        webbrowser.open(url)

    def exit_app(icon, item):
        icon.stop()
        os._exit(0)

    icon = pystray.Icon(
        "yuketang-bot",
        _create_tray_image(),
        "雨课堂控制台",
        menu=pystray.Menu(
            pystray.MenuItem("打开控制台", open_console),
            pystray.MenuItem("退出", exit_app),
        ),
    )
    icon.run()


def _run_server(config_path: str, port: int = DEFAULT_PORT):
    from yuketang_bot.web.app import run_server

    run_server(
        host="127.0.0.1",
        port=port,
        config_path=config_path,
        open_browser=False,
    )


def main(port: int = DEFAULT_PORT):
    """启动器入口"""
    app_dir = get_app_dir()
    os.chdir(app_dir)

    config_path = ensure_config()
    url = f"http://127.0.0.1:{port}/"

    # 在后台线程启动 FastAPI 服务
    server_thread = threading.Thread(
        target=_run_server,
        args=(config_path, port),
        daemon=True,
    )
    server_thread.start()

    # 等待服务启动
    time.sleep(1.5)

    # 自动打开浏览器
    webbrowser.open(url)

    # 进入托盘循环
    _run_tray(port)


if __name__ == "__main__":
    main()
