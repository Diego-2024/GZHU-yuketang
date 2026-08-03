# -*- coding: utf-8 -*-
"""DrissionPage 浏览器：扫码登录、抓包、播放触发"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .models import Account, AppConfig
from .utils import log

LISTEN_TARGET = "video-log/heartbeat"

# 多线程下激活窗口会抢焦点，串行执行「激活+空格播放」
_activate_lock = threading.Lock()


def cookies_dict(tab) -> Dict[str, str]:
    return {c["name"]: c["value"] for c in tab.cookies()}


def sync_account_profile(tab, account_name: str, cfg: AppConfig, store) -> Dict[str, str]:
    """从当前浏览器 tab 同步雨课堂用户名到本地数据库。"""
    from .api import fetch_user_profile

    cookies = cookies_dict(tab)
    if not cookies.get("sessionid"):
        store.save_account_profile(account_name, logged_in=False)
        return {}
    prof = fetch_user_profile(cookies, cfg.base_url)
    name = str(prof.get("name") or "").strip()
    user_id = str(prof.get("user_id") or "").strip()
    store.save_account_profile(
        account_name,
        yuketang_name=name,
        user_id=user_id,
        logged_in=True,
    )
    return {"name": name, "user_id": user_id}


def is_logged_in(tab) -> bool:
    return bool(cookies_dict(tab).get("sessionid"))


def listen_stop(tab) -> None:
    listen = getattr(tab, "listen", None)
    if not listen:
        return
    try:
        listen.stop()
    except Exception:
        pass


def listen_start(tab, target: str) -> None:
    listen = getattr(tab, "listen", None)
    if not listen:
        raise RuntimeError("listen not available, pip install -U DrissionPage")
    listen_stop(tab)
    listen.start(target)


def extract_post_data(packet) -> Dict[str, Any]:
    sources = [getattr(packet, "request", None), packet]
    for source in sources:
        if not source:
            continue
        for attr in ("postData", "post_data", "body"):
            val = getattr(source, attr, None)
            if not val:
                continue
            if isinstance(val, dict):
                return val
            if isinstance(val, str) and val.strip():
                return json.loads(val)
    raise ValueError("no POST body in packet")


def valid_heartbeat_data(data: Any) -> bool:
    if not isinstance(data, dict):
        return False
    heart_data = data.get("heart_data")
    if not isinstance(heart_data, list) or not heart_data:
        return False
    sample = heart_data[-1]
    return isinstance(sample, dict) and sample.get("v") and sample.get("u")


def wait_for_video(tab, timeout: int = 20) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if tab.ele("tag:video", timeout=1):
            return True
        time.sleep(0.5)
    return False


def activate_tab(tab, tag: str) -> None:
    try:
        tab.set.activate()
    except Exception as exc:
        log(tag, "CDP 激活标签失败: %s" % exc)
    try:
        tab.run_cdp("Page.bringToFront")
    except Exception:
        pass
    try:
        tab.run_js("window.focus(); if (document.body) document.body.focus();")
    except Exception:
        pass
    _focus_os_window(tab, tag)


def _focus_os_window(tab, tag: str) -> bool:
    try:
        import ctypes

        user32 = ctypes.windll.user32
        title = (tab.title or "").strip()
        if not title:
            return False

        found = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        def _enum_proc(hwnd, _):
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            wt = buf.value
            if title in wt or wt in title:
                found.append(hwnd)
                return False
            return True

        user32.EnumWindows(_enum_proc, 0)
        if not found:
            return False
        hwnd = found[0]
        user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)
        return True
    except Exception as exc:
        log(tag, "OS 窗口激活失败: %s" % exc)
        return False


def click_beside_video(tab, tag: str) -> bool:
    targets = (
        "text:完成度",
        "text:发表评论",
        "css:.leaf-title",
        "css:.section-title",
        "css:.video-title",
        "css:main",
        "tag:body",
    )
    for sel in targets:
        ele = tab.ele(sel, timeout=0.8)
        if not ele:
            continue
        try:
            tab.actions.move_to(ele, duration=0.1).click()
            log(tag, "已点击旁侧: %s" % sel)
            return True
        except Exception:
            try:
                ele.click(by_js=False)
                log(tag, "已元素点击: %s" % sel)
                return True
            except Exception:
                pass
    try:
        tab.actions.click((150, 220))
        log(tag, "已点击固定旁侧坐标")
        return True
    except Exception:
        return False


def press_space(tab, tag: str) -> bool:
    from DrissionPage._functions.keys import Keys

    try:
        tab.actions.type(Keys.SPACE)
        log(tag, "已发送空格键")
        return True
    except Exception as exc:
        log(tag, "空格键失败: %s" % exc)
        return False


def is_video_playing(tab) -> bool:
    try:
        return bool(tab.run_js(
            "return !!(document.querySelector('video') && !document.querySelector('video').paused);"
        ))
    except Exception:
        return False


def activate_and_space_play(tab, tag: str, reason: str = "") -> bool:
    if reason:
        log(tag, reason)
    with _activate_lock:
        activate_tab(tab, tag)
        time.sleep(0.5)
        click_beside_video(tab, tag)
        time.sleep(0.3)
        press_space(tab, tag)
        time.sleep(0.5)
    time.sleep(0.8)
    if is_video_playing(tab):
        log(tag, "视频已开始播放")
        return True
    return False


def wait_packet(tab, tag: str, listen_timeout: int = 60):
    deadline = time.time() + listen_timeout
    hinted = False
    empty_count = 0

    while time.time() < deadline:
        pkt = tab.listen.wait(
            timeout=max(1, int(deadline - time.time())), raise_err=False
        )
        if not pkt:
            activate_and_space_play(tab, tag, "等待 heartbeat，尝试空格播放...")
            if not hinted and time.time() > deadline - listen_timeout + 25:
                log(tag, "若仍无响应，请手动激活浏览器并按空格播放")
                hinted = True
            continue

        url = getattr(pkt, "url", "") or getattr(
            getattr(pkt, "request", None), "url", ""
        )
        method = (
            getattr(pkt, "method", "")
            or getattr(getattr(pkt, "request", None), "method", "")
            or ""
        ).upper()
        if LISTEN_TARGET not in url:
            continue
        if method and method != "POST":
            continue
        try:
            data = extract_post_data(pkt)
        except Exception:
            continue

        if not valid_heartbeat_data(data):
            empty_count += 1
            log(tag, "收到空 heartbeat 包(%d)，视频可能已暂停，自动空格播放..." % empty_count)
            for _ in range(3):
                activate_and_space_play(tab, tag)
                time.sleep(1.5)
                if is_video_playing(tab):
                    log(tag, "视频已开始播放，等待有效 heartbeat...")
                    break
            continue

        log(tag, "捕获有效 heartbeat 包")
        pkt._parsed_data = data
        return pkt

    raise TimeoutError("%ss 内未捕获有效 heartbeat，请确认视频已开始播放" % listen_timeout)


def create_browser(
    account: Account, index: int, cfg: AppConfig
) -> Tuple[Any, Any]:
    from DrissionPage import Chromium, ChromiumOptions

    profile_dir = Path(cfg.profiles_root) / account.profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    port = account.port if account.port else cfg.base_port + index

    co = ChromiumOptions()
    co.set_user_data_path(str(profile_dir))
    co.set_local_port(port)
    co.set_argument("--disable-blink-features=AutomationControlled")

    log(account.name, "browser port=%s profile=%s" % (port, profile_dir.name))
    browser = Chromium(co)
    tab = browser.latest_tab
    if tab is None:
        tab = browser.new_tab()
    if tab is None:
        raise RuntimeError("cannot get tab")
    return browser, tab


def wait_qr_login(
    tab,
    tag: str,
    base_url: str,
    interactive: bool = True,
    confirm_event: Optional[threading.Event] = None,
    cancel_event: Optional[threading.Event] = None,
) -> bool:
    """
    扫码登录：有 sessionid 则跳过，否则等待用户扫码。
    - confirm_event: Web 模式用，set 后视为用户确认已扫码
    - 无 confirm_event 时：CLI 用 input() 等待 Enter
    """
    tab.get(base_url)
    time.sleep(2)

    if is_logged_in(tab):
        log(tag, "已复用保存的登录态，无需扫码")
        return True

    if not interactive:
        log(tag, "未登录，请先运行 python main.py login 扫码")
        return False

    print("\n" + "=" * 50)
    log(tag, "请在浏览器窗口中 【扫码登录】")
    if confirm_event is not None:
        log(tag, "登录成功后在网页点击「我已扫码」...")
        print("=" * 50)
        while not confirm_event.is_set():
            if cancel_event is not None and cancel_event.is_set():
                log(tag, "登录已取消")
                return False
            # 扫码后 cookie 可能自动出现，主动轮询
            if is_logged_in(tab):
                log(tag, "登录成功！已保存到 profiles/")
                return True
            confirm_event.wait(timeout=1.0)
        # 用户点了确认，再检测一次
        time.sleep(1)
    else:
        log(tag, "登录成功后回到终端按 Enter ...")
        print("=" * 50)
        input()

    if is_logged_in(tab):
        log(tag, "登录成功！已保存到 profiles/")
        return True

    log(tag, "仍未检测到登录，请重试")
    return False


def capture_from_tab(
    tab, url: str, base: str, tag: str, listen_timeout: int = 60
) -> Dict[str, Any]:
    listen_start(tab, LISTEN_TARGET)
    tab.get(url)
    tab.wait.doc_loaded(timeout=30)
    time.sleep(2)

    if not wait_for_video(tab, timeout=20):
        log(tag, "未找到 video 元素，继续尝试...")
    time.sleep(1)

    activate_and_space_play(tab, tag, "进入视频页，尝试空格播放...")
    pkt = wait_packet(tab, tag, listen_timeout=listen_timeout)
    listen_stop(tab)
    headers = dict(getattr(getattr(pkt, "request", None), "headers", {}) or {})
    headers["referer"] = url
    headers.setdefault("origin", base)
    data = getattr(pkt, "_parsed_data", None) or extract_post_data(pkt)
    return {
        "headers": headers,
        "cookies": cookies_dict(tab),
        "data": data,
        "referer": url,
        "video_url": url,
    }


def quit_browser(browser) -> None:
    if not browser:
        return
    try:
        browser.quit()
    except Exception:
        pass
