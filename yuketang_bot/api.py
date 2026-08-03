# -*- coding: utf-8 -*-
"""雨课堂 heartbeat / 进度 API 客户端"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Callable, Dict, Optional, Tuple

import requests

from .models import LoopConfig
from .utils import hget, log, parse_pg_suffix, parse_video_url

# 多线程共享：同一 video_id 的课程参数只解析一次
_shared_video_cache: Dict[str, Dict[str, Any]] = {}
_cache_lock = threading.Lock()


def sample_event(heart_data):
    if not heart_data:
        raise ValueError("heart_data is empty")
    for item in heart_data:
        if item.get("d", 0) > 0:
            return item
    return heart_data[-1]


def build_config(
    capture: Dict[str, Any], loop_defaults: Optional[LoopConfig] = None
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    headers = capture["headers"]
    cookies = capture["cookies"]
    heart_data = capture["data"]["heart_data"]
    if not heart_data:
        raise ValueError("heart_data is empty")
    sample = sample_event(heart_data)
    referer = hget(headers, "referer") or capture.get("referer", "")
    if referer:
        try:
            url_info = parse_video_url(referer)
        except ValueError:
            url_info = parse_video_url(capture.get("video_url", "") or referer)
    else:
        url_info = parse_video_url(capture.get("video_url", ""))

    video_id = str(sample.get("v", url_info["video_id"]))
    origin = hget(headers, "origin") or ""
    if not origin and referer:
        from .utils import origin_from_url
        origin = origin_from_url(referer)

    auth = {
        "sessionid": cookies["sessionid"],
        "csrftoken": cookies.get("csrftoken") or hget(headers, "x-csrftoken"),
        "base_url": origin or "https://www.yuketang.cn",
        "uv_id": cookies.get("university_id", "0"),
        "user_id": str(sample["u"]),
    }
    video = {
        "video_id": video_id,
        "classroom_id": str(sample.get("classroomid", url_info["classroom_id"])),
        "lms_path": url_info["lms_path"],
        "cid": str(sample["c"]),
        "skuid": str(sample["skuid"]),
        "course_code": sample["cc"],
        "video_duration": float(sample["d"]) if sample.get("d") else 0,
        "pg_suffix": parse_pg_suffix(sample.get("pg", ""), video_id),
    }
    if video["video_duration"] <= 0:
        for item in heart_data:
            if item.get("d", 0) > 0:
                video["video_duration"] = float(item["d"])
                break

    if loop_defaults:
        loop = loop_defaults.to_dict()
    else:
        loop = LoopConfig().to_dict()
    loop["heartbeat_interval"] = heart_data[0].get("i", loop.get("heartbeat_interval", 5))
    loop["playback_rate"] = sample.get("sp", loop.get("playback_rate", 1))
    loop["start_sq"] = max(item.get("sq", 0) for item in heart_data) + 1
    return auth, video, loop


def apply_shared_video(auth, video, loop, video_id):
    """同视频共用课程参数，仅保留本账号 auth / start_sq"""
    with _cache_lock:
        if video_id in _shared_video_cache:
            video = dict(_shared_video_cache[video_id])
        else:
            _shared_video_cache[video_id] = dict(video)
    return auth, video, loop


def get_shared_cache_keys():
    return list(_shared_video_cache.keys())


def fetch_user_profile(
    cookies: Dict[str, str],
    base_url: str = "https://www.yuketang.cn",
) -> Dict[str, Any]:
    """用 cookie 拉取雨课堂用户信息，返回 name / user_id 等。"""
    origin = (base_url or "https://www.yuketang.cn").rstrip("/")
    sessionid = cookies.get("sessionid", "")
    csrftoken = cookies.get("csrftoken", "")
    if not sessionid:
        return {}

    sess = requests.Session()
    cookie_jar = {
        "sessionid": sessionid,
        "csrftoken": csrftoken,
        "university_id": cookies.get("university_id", "0"),
        "platform_id": cookies.get("platform_id", "3"),
        "xtbz": cookies.get("xtbz", "ykt"),
    }
    headers = {
        "accept": "application/json, text/plain, */*",
        "university-id": str(cookies.get("university_id", "0")),
        "xtbz": "ykt",
        "x-requested-with": "XMLHttpRequest",
        "x-csrftoken": csrftoken,
        "referer": origin + "/",
        "origin": origin,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    for path in (
        "/v2/api/web/userinfo",
        "/api/v3/user/basic-info",
        "/v/course_meta/user_info",
    ):
        try:
            resp = sess.get(
                origin + path,
                headers=headers,
                cookies=cookie_jar,
                timeout=15,
            )
            ui = resp.json()
            data = ui.get("data") if isinstance(ui.get("data"), dict) else ui
            if not isinstance(data, dict):
                continue
            user_id = (
                data.get("user_id")
                or data.get("id")
                or data.get("userId")
            )
            name = (
                data.get("name")
                or data.get("nickname")
                or data.get("real_name")
                or data.get("user_name")
                or data.get("username")
                or data.get("full_name")
                or data.get("school_number")
            )
            if name or user_id:
                return {
                    "name": str(name or "").strip(),
                    "user_id": str(user_id or "").strip(),
                    "raw": data,
                }
        except Exception:
            continue
    return {}


def probe_watch_progress(
    cookies: Dict[str, str],
    video_url: str,
    base_url: str = "",
    uv_id: str = "",
) -> Dict[str, Any]:
    """
    不打开视频播放器：用 leaf_info + get_video_watch_progress 查询进度。
    返回 progress dict；失败返回 {}。
    """
    from .utils import origin_from_url, parse_video_url

    try:
        info = parse_video_url(video_url)
    except ValueError:
        return {}

    origin = (base_url or origin_from_url(video_url) or "https://www.yuketang.cn").rstrip("/")
    classroom_id = info["classroom_id"]
    video_id = info["video_id"]
    uv = str(uv_id or cookies.get("university_id") or "0")
    sessionid = cookies.get("sessionid", "")
    csrftoken = cookies.get("csrftoken", "")
    if not sessionid:
        return {}

    sess = requests.Session()
    cookie_jar = {
        "sessionid": sessionid,
        "csrftoken": csrftoken,
        "university_id": uv,
        "platform_id": cookies.get("platform_id", "3"),
        "xtbz": cookies.get("xtbz", "ykt"),
    }
    headers = {
        "accept": "application/json, text/plain, */*",
        "university-id": uv,
        "classroom-id": str(classroom_id),
        "xtbz": "ykt",
        "x-requested-with": "XMLHttpRequest",
        "x-csrftoken": csrftoken,
        "referer": video_url,
        "origin": origin,
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    }

    leaf = {}
    for try_origin in (origin, "https://www.yuketang.cn"):
        leaf_url = "%s/mooc-api/v1/lms/learn/leaf_info/%s/%s/" % (
            try_origin, classroom_id, video_id,
        )
        try:
            leaf_resp = sess.get(
                leaf_url, headers=headers, cookies=cookie_jar, timeout=20
            )
            leaf = leaf_resp.json().get("data") or {}
            if leaf:
                origin = try_origin
                break
        except Exception:
            leaf = {}

    def _dig(obj, *keys):
        cur = obj
        for k in keys:
            if not isinstance(cur, dict):
                return None
            cur = cur.get(k)
        return cur

    cid = (
        leaf.get("course_id")
        or leaf.get("cid")
        or _dig(leaf, "content_info", "course_id")
    )
    user_id = leaf.get("user_id") or leaf.get("uid")
    if not user_id:
        for path in (
            ("/v2/api/web/userinfo",),
            ("/api/v3/user/basic-info",),
            ("/v/course_meta/user_info",),
        ):
            try:
                ui = sess.get(
                    origin + path[0],
                    headers=headers,
                    cookies=cookie_jar,
                    timeout=15,
                ).json()
                data = ui.get("data") if isinstance(ui.get("data"), dict) else ui
                user_id = (
                    (data or {}).get("user_id")
                    or (data or {}).get("id")
                    or (data or {}).get("userId")
                )
                if user_id:
                    break
            except Exception:
                continue

    if not cid or not user_id:
        return {}

    try:
        prog_resp = sess.get(
            origin + "/video-log/get_video_watch_progress/",
            headers=headers,
            cookies=cookie_jar,
            params={
                "cid": cid,
                "user_id": user_id,
                "classroom_id": classroom_id,
                "video_type": "video",
                "vtype": "rate",
                "video_id": video_id,
                "snapshot": "1",
                "term": "latest",
                "uv_id": uv,
            },
            timeout=20,
        )
        return prog_resp.json().get("data", {}).get(str(video_id), {}) or {}
    except Exception:
        return {}


class YuketangClient:
    def __init__(self, auth, loop, tag: str = ""):
        self.auth = auth
        self.loop = loop
        self.tag = tag
        self.session = requests.Session()

    def referer(self, video):
        a = self.auth
        return "{}/pro/lms/{}/{}/video/{}".format(
            a["base_url"], video["lms_path"], video["classroom_id"], video["video_id"]
        )

    def _headers(self, referer):
        a = self.auth
        return {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": a["base_url"],
            "referer": referer,
            "platform-id": "3",
            "terminal-type": "web",
            "university-id": a["uv_id"],
            "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "x-client": "web",
            "x-csrftoken": a["csrftoken"],
            "x-requested-with": "XMLHttpRequest",
            "xtbz": "cloud",
        }

    def _cookies(self):
        a = self.auth
        return {
            "university_id": a["uv_id"],
            "platform_id": "3",
            "xtbz": "cloud",
            "platform_type": "1",
            "csrftoken": a["csrftoken"],
            "sessionid": a["sessionid"],
        }

    def get_progress(self, video):
        a = self.auth
        resp = self.session.get(
            a["base_url"] + "/video-log/get_video_watch_progress/",
            headers=self._headers(self.referer(video)),
            cookies=self._cookies(),
            params={
                "cid": video["cid"],
                "user_id": a["user_id"],
                "classroom_id": video["classroom_id"],
                "video_type": "video",
                "vtype": "rate",
                "video_id": video["video_id"],
                "snapshot": "1",
                "term": "latest",
                "uv_id": a["uv_id"],
            },
            timeout=30,
        )
        return resp.json().get("data", {}).get(video["video_id"], {})

    def print_progress(self, label, info):
        log(self.tag, "[%s] %.1f/%.0fs | %.2f%% | done=%s" % (
            label,
            info.get("last_point", 0),
            info.get("video_length", 0),
            info.get("rate", 0) * 100,
            info.get("completed", 0),
        ))

    @staticmethod
    def is_done(info, target_rate, dur=0):
        """已完成 / 进度达到目标（含 100%）则视为 done"""
        if not info:
            return False
        completed = info.get("completed")
        if completed in (1, True, "1", "true", "True"):
            return True
        rate = float(info.get("rate", 0) or 0)
        # 服务端偶发 rate=0.999...，按 100% 或配置阈值跳过
        if rate >= min(float(target_rate), 1.0) or rate >= 0.999:
            return True
        total = float(info.get("video_length", 0) or dur or 0)
        last = float(info.get("last_point", 0) or 0)
        return total > 0 and last >= total * float(target_rate)

    def _make_event(self, video, et, cp, sq, ts_ms, sp=None):
        l, vid = self.loop, video["video_id"]
        return {
            "i": l["heartbeat_interval"],
            "et": et,
            "p": "web",
            "n": "ali-cdn.xuetangx.com",
            "lob": "cloud4",
            "cp": round(cp, 1),
            "fp": 0,
            "tp": 0,
            "sp": sp if sp is not None else l["playback_rate"],
            "ts": str(ts_ms),
            "u": int(self.auth["user_id"]),
            "uip": "",
            "c": int(video["cid"]),
            "v": int(vid),
            "skuid": int(video["skuid"]),
            "classroomid": video["classroom_id"],
            "cc": video["course_code"],
            "d": video["video_duration"],
            "pg": "%s_%s" % (vid, video["pg_suffix"]),
            "sq": sq,
            "t": "video",
            "cards_id": 0,
            "slide": 0,
            "v_url": "",
        }

    def build_heart_data(self, video, start_cp, start_sq, is_first=False):
        l = self.loop
        events, sq, cp = [], start_sq, start_cp
        now_ms = int(time.time() * 1000)
        dur = video["video_duration"]
        if is_first and start_cp <= 0:
            events.append(self._make_event(video, "loadstart", 0, sq, now_ms))
            sq += 1
            now_ms += 300
            events.append(self._make_event(video, "loadeddata", 0, sq, now_ms, sp=1))
            sq += 1
            now_ms += 500
        events.append(self._make_event(video, "play", cp, sq, now_ms))
        sq += 1
        now_ms += 2
        events.append(self._make_event(video, "playing", cp, sq, now_ms))
        sq += 1
        step = l["heartbeat_interval"] * l["playback_rate"]
        for _ in range(l["heartbeat_count"]):
            now_ms += l["heartbeat_interval"] * 1000
            cp = min(cp + step, dur)
            events.append(self._make_event(video, "heartbeat", cp, sq, now_ms))
            sq += 1
            if cp >= dur:
                break
        return events, sq

    def send_heartbeat(self, video, start_cp, start_sq, is_first=False):
        heart_data, sq = self.build_heart_data(video, start_cp, start_sq, is_first)
        payload = json.dumps({"heart_data": heart_data}, separators=(",", ":"))
        resp = self.session.post(
            self.auth["base_url"] + "/video-log/heartbeat/",
            headers=self._headers(self.referer(video)),
            cookies=self._cookies(),
            data=payload,
            timeout=30,
        )
        return resp, heart_data, sq

    def run(
        self,
        video,
        on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> bool:
        l, sq, batch = self.loop, self.loop["start_sq"], 0
        log(self.tag, "video=%s duration=%ss sq=%s user=%s" % (
            video["video_id"], video["video_duration"], sq, self.auth["user_id"],
        ))
        progress = self.get_progress(video)
        self.print_progress("initial", progress)
        if on_progress:
            on_progress(progress)
        if self.is_done(progress, l["target_rate"], video["video_duration"]):
            log(self.tag, "skip: already done")
            return True
        is_first = progress.get("last_point", 0) <= 0
        while batch < l["max_batches"]:
            batch += 1
            start_cp = progress.get("last_point", 0)
            total = progress.get("video_length", 0) or video["video_duration"]
            if start_cp >= total * l["target_rate"]:
                break
            log(self.tag, "batch %d from %.1fs sq=%d" % (batch, start_cp, sq))
            resp, heart_data, sq = self.send_heartbeat(video, start_cp, sq, is_first)
            is_first = False
            if resp.status_code != 200:
                log(self.tag, "HTTP %d %s" % (resp.status_code, resp.text))
                return False
            log(self.tag, "sent %d cp %s->%s" % (
                len(heart_data), heart_data[0]["cp"], heart_data[-1]["cp"],
            ))
            time.sleep(l["batch_sleep"])
            progress = self.get_progress(video)
            self.print_progress("batch %d" % batch, progress)
            if on_progress:
                on_progress(progress)
            if self.is_done(progress, l["target_rate"], video["video_duration"]):
                log(self.tag, "OK done!")
                return True
            time.sleep(l["batch_sleep"])
        self.print_progress("final", progress)
        return self.is_done(progress, l["target_rate"], video["video_duration"])
