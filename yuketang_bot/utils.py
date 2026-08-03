# -*- coding: utf-8 -*-
"""通用工具：日志、URL 解析、cookie 提取"""

from __future__ import annotations

import re
import threading
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

# 可选日志钩子（Web SSE 等），线程安全
_log_hooks: List[Callable[[str, str], None]] = []
_hooks_lock = threading.Lock()


def add_log_hook(hook: Callable[[str, str], None]) -> None:
    with _hooks_lock:
        if hook not in _log_hooks:
            _log_hooks.append(hook)


def remove_log_hook(hook: Callable[[str, str], None]) -> None:
    with _hooks_lock:
        if hook in _log_hooks:
            _log_hooks.remove(hook)


def clear_log_hooks() -> None:
    with _hooks_lock:
        _log_hooks.clear()


def log(tag: str, msg: str) -> None:
    line = "[%s] %s" % (tag, msg)
    print(line)
    with _hooks_lock:
        hooks = list(_log_hooks)
    for hook in hooks:
        try:
            hook(tag, msg)
        except Exception:
            pass


def parse_video_url(url: str) -> Dict[str, str]:
    """解析 /pro/lms/{path}/{classroom}/video/{id} 或 /v/lms/..."""
    m = re.search(r"/(?:pro|v)/lms/([^/]+)/([^/]+)/video/([^/?#]+)", url)
    if not m:
        raise ValueError("video url invalid: " + url)
    return {
        "lms_path": m.group(1),
        "classroom_id": m.group(2),
        "video_id": m.group(3),
    }


def parse_course_url(url: str) -> Optional[Dict[str, str]]:
    """解析课程主页 URL: /pro/lms/{path}/{classroom} 或带后续路径"""
    m = re.search(r"/(?:pro|v)/lms/([^/]+)/([^/?#]+)", url)
    if not m:
        return None
    return {"lms_path": m.group(1), "classroom_id": m.group(2)}


def is_video_url(url: str) -> bool:
    return bool(re.search(r"/(?:pro|v)/lms/[^/]+/[^/]+/video/[^/?#]+", url or ""))


def is_course_url(url: str) -> bool:
    if not url:
        return False
    if is_video_url(url):
        return False
    return bool(re.search(r"/(?:pro|v)/lms/[^/]+/[^/?#]+", url))


def normalize_url(url: str, base: str = "") -> str:
    """相对路径转绝对 URL，去掉 fragment"""
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/") and base:
        url = urljoin(base.rstrip("/") + "/", url.lstrip("/"))
    elif not url.startswith("http") and base:
        url = urljoin(base.rstrip("/") + "/", url)
    # 去掉 hash
    if "#" in url:
        url = url.split("#", 1)[0]
    return url


def course_key_from_url(url: str) -> str:
    """课程去重键：lms_path + classroom_id，或 studentLog classroom_id"""
    info = parse_course_url(url)
    if info:
        return "%s/%s" % (info["lms_path"], info["classroom_id"])
    m = re.search(r"/v2/web/studentLog/(\d+)", url or "")
    if m:
        return "studentLog/%s" % m.group(1)
    return url or ""


def origin_from_url(url: str) -> str:
    p = urlparse(url)
    if p.scheme and p.netloc:
        return "%s://%s" % (p.scheme, p.netloc)
    return ""


def hget(headers: Optional[Dict[str, Any]], key: str, default: str = "") -> str:
    kl = key.lower()
    for k, v in (headers or {}).items():
        if str(k).lower() == kl:
            return v
    return default


def parse_pg_suffix(pg: str, video_id: str) -> str:
    prefix = video_id + "_"
    if pg.startswith(prefix):
        return pg[len(prefix):]
    if "_" in pg:
        return pg.split("_", 1)[-1]
    return pg


def parse_selection(text: str, total: int) -> list:
    """
    解析用户多选输入：
      all / * / 回车 -> 全部
      1,3,5 / 1-3 / 1 2 3
    返回 0-based index 列表
    """
    text = (text or "").strip().lower()
    if not text or text in ("all", "*", "a"):
        return list(range(total))

    indices = set()
    parts = re.split(r"[,，\s]+", text)
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            try:
                start, end = int(a), int(b)
            except ValueError:
                continue
            for i in range(min(start, end), max(start, end) + 1):
                if 1 <= i <= total:
                    indices.add(i - 1)
        else:
            try:
                i = int(part)
            except ValueError:
                continue
            if 1 <= i <= total:
                indices.add(i - 1)
    return sorted(indices)
