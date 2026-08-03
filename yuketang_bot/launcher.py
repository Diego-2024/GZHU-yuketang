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

import multiprocessing
import os
import shutil
import sys
import threading
import time
import traceback
import urllib.request
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


def get_log_path() -> Path:
    return get_app_dir() / "yuketang-bot.log"


def log(msg: str) -> None:
    try:
        path = get_log_path()
        with open(path, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + " " + msg + "\n")
    except Exception:
        pass


def show_error(title: str, message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, title, 0x10)
    except Exception:
        pass


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
        log("generated config from example: %s" % config_path)
    else:
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
        log("generated fallback config: %s" % config_path)

    return str(config_path)


def _create_tray_image():
    """用 Pillow 生成一个简单的天蓝色托盘图标"""
    from PIL import Image, ImageDraw

    size = 64
    img = Image.new("RGBA", (size, size), (135, 206, 250, 255))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle(
        [size // 5, size // 5, 4 * size // 5, 4 * size // 5],
        radius=8,
        fill=(255, 255, 255, 255),
        outline=(70, 130, 180, 255),
        width=3,
    )
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
            pystray.MenuItem("打开控制台", open_console, default=True),
            pystray.MenuItem("退出", exit_app),
        ),
    )
    icon.run()


def _run_server(config_path: str, port: int = DEFAULT_PORT):
    try:
        log("server thread starting on port %d" % port)
        from yuketang_bot.web.app import run_server

        run_server(
            host="127.0.0.1",
            port=port,
            config_path=config_path,
            open_browser=False,
        )
    except Exception:
        log("server thread crashed:\n" + traceback.format_exc())
        show_error(
            "雨课堂控制台启动失败",
            "本地服务启动失败，请查看日志：\n%s" % get_log_path(),
        )


def wait_server_ready(port: int, timeout: float = 20.0) -> bool:
    url = "http://127.0.0.1:%d/" % port
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.4)
    return False


def main(port: int = DEFAULT_PORT):
    """启动器入口"""
    multiprocessing.freeze_support()

    # windowed 模式下补齐 stdout/stderr，避免第三方库崩溃
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    app_dir = get_app_dir()
    os.chdir(app_dir)
    log("app_dir=%s frozen=%s" % (app_dir, getattr(sys, "frozen", False)))
    if getattr(sys, "frozen", False):
        log("meipass=%s" % getattr(sys, "_MEIPASS", ""))

    try:
        config_path = ensure_config()
    except Exception:
        log("ensure_config failed:\n" + traceback.format_exc())
        show_error("雨课堂控制台", "配置初始化失败，请查看日志：\n%s" % get_log_path())
        return

    url = f"http://127.0.0.1:{port}/"

    server_thread = threading.Thread(
        target=_run_server,
        args=(config_path, port),
        daemon=True,
    )
    server_thread.start()

    if wait_server_ready(port, timeout=25.0):
        log("server ready, opening browser")
        webbrowser.open(url)
    else:
        log("server not ready after timeout")
        show_error(
            "雨课堂控制台启动失败",
            "无法连接到 http://127.0.0.1:%d/\n\n"
            "请查看同目录日志文件：\n%s\n\n"
            "也可先结束任务管理器中的 yuketang-bot.exe 后重试。"
            % (port, get_log_path()),
        )
        return

    try:
        _run_tray(port)
    except Exception:
        log("tray failed:\n" + traceback.format_exc())
        # 托盘失败时保持进程，避免服务立刻退出
        while True:
            time.sleep(3600)


if __name__ == "__main__":
    main()
