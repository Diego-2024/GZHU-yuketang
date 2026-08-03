# -*- coding: utf-8 -*-
"""后台任务管理 + SSE 日志总线"""

from __future__ import annotations

import queue
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..browser import (
    create_browser,
    is_logged_in,
    quit_browser,
    sync_account_profile,
    wait_qr_login,
)
from ..config import load_config
from ..discover import (
    course_from_dict,
    course_to_dict,
    crawl_videos_for_courses,
    discover_courses,
    save_videos_to_store,
)
from ..runner import run_auto
from ..store import Store
from ..utils import add_log_hook, log, remove_log_hook


@dataclass
class Job:
    id: int
    action: str
    state: str = "running"  # running / success / failed / cancelled
    message: str = ""
    account: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None


class JobManager:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path
        self._lock = threading.Lock()
        self._job: Optional[Job] = None
        self._next_id = 1
        self._thread: Optional[threading.Thread] = None
        self.cancel_event = threading.Event()
        self.confirm_event = threading.Event()

        # 登录会话：保持浏览器打开直到确认
        self._login_browser = None
        self._login_tab = None
        self._login_account = None

        # discover 会话：发现课程后保持浏览器，供 crawl 使用
        self._discover_browser = None
        self._discover_tab = None
        self._discover_account = None
        self._courses: List[Dict[str, Any]] = []
        self._profile_probe_lock = threading.Lock()
        self._profile_probing: set = set()

        # SSE
        self._subscribers: List[queue.Queue] = []
        self._sub_lock = threading.Lock()
        self._log_buffer: List[Dict[str, Any]] = []
        self._log_hook = self._on_log
        add_log_hook(self._log_hook)

    # ---------- SSE ----------

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=500)
        with self._sub_lock:
            self._subscribers.append(q)
        # 回放最近日志
        for item in self._log_buffer[-80:]:
            try:
                q.put_nowait(item)
            except queue.Full:
                break
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._sub_lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def _emit(self, event: str, data: Dict[str, Any]) -> None:
        payload = {"event": event, "data": data, "ts": time.time()}
        if event == "log":
            self._log_buffer.append(payload)
            if len(self._log_buffer) > 300:
                self._log_buffer = self._log_buffer[-200:]
        with self._sub_lock:
            dead = []
            for q in self._subscribers:
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    dead.append(q)
            for q in dead:
                self._subscribers.remove(q)

    def _on_log(self, tag: str, msg: str) -> None:
        self._emit("log", {"tag": tag, "msg": msg, "line": "[%s] %s" % (tag, msg)})

    # ---------- Job 状态 ----------

    def current(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._job:
                return None
            j = self._job
            return {
                "id": j.id,
                "action": j.action,
                "state": j.state,
                "message": j.message,
                "account": j.account,
                "started_at": j.started_at,
                "finished_at": j.finished_at,
                "result": j.result,
            }

    def _start_job(self, action: str, account: Optional[str], target) -> Dict[str, Any]:
        with self._lock:
            if self._job and self._job.state == "running":
                raise RuntimeError("已有任务运行中: %s" % self._job.action)
            job = Job(id=self._next_id, action=action, account=account)
            self._next_id += 1
            self._job = job
            self.cancel_event.clear()
            if action != "login":
                self.confirm_event.clear()

        def runner():
            try:
                result = target()
                with self._lock:
                    if self.cancel_event.is_set() and job.state == "running":
                        job.state = "cancelled"
                        job.message = "已取消"
                    elif job.state == "running":
                        job.state = "success"
                        job.message = job.message or "完成"
                    job.result = result
                    job.finished_at = time.time()
            except Exception as e:
                traceback.print_exc()
                with self._lock:
                    job.state = "failed"
                    job.message = str(e)
                    job.finished_at = time.time()
            self._emit("job", self.current() or {})

        self._thread = threading.Thread(target=runner, name="job-%s" % action, daemon=True)
        self._thread.start()
        self._emit("job", self.current() or {})
        return self.current()

    def cancel(self) -> Dict[str, Any]:
        self.cancel_event.set()
        self.confirm_event.set()  # 解除可能的 wait
        with self._lock:
            if self._job and self._job.state == "running":
                self._job.message = "正在取消..."
        log("web", "收到取消请求")
        self._cleanup_login_browser()
        self._cleanup_discover_browser()
        return self.current() or {"state": "idle"}

    def confirm_login(self) -> Dict[str, Any]:
        self.confirm_event.set()
        log("web", "用户确认已扫码")
        return {"ok": True}

    # ---------- 业务 ----------

    def get_cfg(self):
        return load_config(self.config_path)

    def get_store(self) -> Store:
        return Store(self.get_cfg().db_path)

    def login_status(self, account_name: Optional[str] = None) -> Dict[str, Any]:
        """账号状态 + 缓存的雨课堂昵称"""
        cfg = self.get_cfg()
        store = self.get_store()
        results = []
        for i, acc in enumerate(cfg.accounts):
            if account_name and acc.name != account_name:
                continue
            logged_in = False
            tab = None
            if self._login_tab is not None and self._login_account == acc.name:
                tab = self._login_tab
            elif self._discover_tab is not None and self._discover_account == acc.name:
                tab = self._discover_tab
            if tab is not None:
                try:
                    logged_in = is_logged_in(tab)
                    if logged_in:
                        prof = sync_account_profile(tab, acc.name, cfg, store)
                    else:
                        store.save_account_profile(acc.name, logged_in=False)
                except Exception:
                    logged_in = False

            cached = store.get_account_profile(acc.name)
            yuketang_name = cached.get("yuketang_name") or ""
            if not logged_in and cached.get("logged_in"):
                # 无活跃 tab 时以缓存为准（上次探测/登录结果）
                logged_in = True
            results.append({
                "name": acc.name,
                "profile": acc.profile,
                "logged_in": logged_in,
                "login_session_active": (
                    self._login_tab is not None and self._login_account == acc.name
                ),
                "yuketang_name": yuketang_name,
                "display_name": yuketang_name or acc.name,
                "user_id": cached.get("user_id") or "",
            })
        return {"accounts": results}

    def refresh_account_profiles(
        self, account_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """后台探测 profile 登录态并拉取雨课堂昵称"""
        cfg = self.get_cfg()
        accounts = cfg.accounts
        if account_name:
            accounts = [a for a in cfg.accounts if a.name == account_name]
            if not accounts:
                raise ValueError("未找到账号: %s" % account_name)

        def worker():
            store = self.get_store()
            for acc in accounts:
                with self._profile_probe_lock:
                    if acc.name in self._profile_probing:
                        continue
                    self._profile_probing.add(acc.name)
                browser = None
                try:
                    if (
                        self._login_tab is not None
                        and self._login_account == acc.name
                    ) or (
                        self._discover_tab is not None
                        and self._discover_account == acc.name
                    ):
                        continue
                    idx = cfg.accounts.index(acc)
                    browser, tab = create_browser(acc, idx, cfg)
                    tab.get(cfg.home_url)
                    time.sleep(1.5)
                    if is_logged_in(tab):
                        sync_account_profile(tab, acc.name, cfg, store)
                    else:
                        store.save_account_profile(acc.name, logged_in=False)
                except Exception as e:
                    log("web", "探测账号 %s 失败: %s" % (acc.name, e))
                finally:
                    quit_browser(browser)
                    with self._profile_probe_lock:
                        self._profile_probing.discard(acc.name)

        threading.Thread(
            target=worker, name="profile-probe", daemon=True
        ).start()
        return {"ok": True, "queued": [a.name for a in accounts]}

    def start_login(self, account_name: Optional[str] = None) -> Dict[str, Any]:
        self.confirm_event.clear()

        def task():
            cfg = self.get_cfg()
            accounts = cfg.accounts
            if account_name:
                accounts = [a for a in cfg.accounts if a.name == account_name]
                if not accounts:
                    raise ValueError("未找到账号: %s" % account_name)

            ok = 0
            for acc in accounts:
                if self.cancel_event.is_set():
                    break
                index = cfg.accounts.index(acc)
                self._cleanup_login_browser()
                self.confirm_event.clear()
                browser, tab = create_browser(acc, index, cfg)
                self._login_browser = browser
                self._login_tab = tab
                self._login_account = acc.name
                with self._lock:
                    if self._job:
                        self._job.account = acc.name
                        self._job.message = "等待扫码: %s" % acc.name
                self._emit("job", self.current() or {})
                success = wait_qr_login(
                    tab, acc.name, cfg.home_url,
                    confirm_event=self.confirm_event,
                    cancel_event=self.cancel_event,
                )
                if success:
                    sync_account_profile(tab, acc.name, cfg, self.get_store())
                    ok += 1
                # 登录完成后关闭该账号浏览器，释放端口
                self._cleanup_login_browser()
                time.sleep(0.5)

            msg = "登录完成 %d/%d" % (ok, len(accounts))
            with self._lock:
                if self._job:
                    self._job.message = msg
            return {"ok": ok, "total": len(accounts)}

        return self._start_job("login", account_name, task)

    def start_discover(self, account_name: Optional[str] = None) -> Dict[str, Any]:
        def task():
            cfg = self.get_cfg()
            if account_name:
                matched = [a for a in cfg.accounts if a.name == account_name]
                if not matched:
                    raise ValueError("未找到账号: %s" % account_name)
                acc = matched[0]
            else:
                acc = cfg.accounts[0]

            self._cleanup_discover_browser()
            index = cfg.accounts.index(acc)
            browser, tab = create_browser(acc, index, cfg)
            self._discover_browser = browser
            self._discover_tab = tab
            self._discover_account = acc.name

            with self._lock:
                if self._job:
                    self._job.account = acc.name
                    self._job.message = "发现课程中..."

            store = self.get_store()

            # discover 需要已登录；交互确认以便未登录时可扫码
            if not wait_qr_login(
                tab, acc.name, cfg.home_url,
                confirm_event=self.confirm_event,
                cancel_event=self.cancel_event,
            ):
                self._cleanup_discover_browser()
                raise RuntimeError("未登录，无法发现课程")

            sync_account_profile(tab, acc.name, cfg, store)

            courses = discover_courses(tab, cfg, acc.name)
            self._courses = [course_to_dict(c) for c in courses]
            store.save_discovered_courses(acc.name, self._courses)
            msg = "发现 %d 门课程，请在网页勾选后点击爬取" % len(self._courses)
            with self._lock:
                if self._job:
                    self._job.message = msg
            # 保持浏览器打开供 crawl
            return {"courses": self._courses, "account": acc.name, "count": len(self._courses)}

        return self._start_job("discover", account_name, task)

    def get_courses(self, account_name: Optional[str] = None) -> Dict[str, Any]:
        cfg = self.get_cfg()
        store = self.get_store()
        acc = account_name or self._discover_account
        if not acc and cfg.accounts:
            acc = cfg.accounts[0].name

        session_active = (
            self._discover_tab is not None
            and acc == self._discover_account
        )
        if session_active and self._courses:
            courses = list(self._courses)
        elif acc:
            courses = store.list_discovered_courses(acc)
        else:
            courses = []

        stats = store.get_course_video_stats(acc) if acc else {}
        crawl_meta = store.get_course_crawl_meta_map(acc) if acc else {}
        by_cid = stats.get("by_classroom_id") or {}
        by_url = stats.get("by_course_url") or {}
        meta_by_url = crawl_meta.get("by_url") or {}
        meta_by_cid = crawl_meta.get("by_cid") or {}
        enriched = []
        for c in courses:
            item = dict(c)
            cid = (item.get("classroom_id") or "").strip()
            url_key = (item.get("url") or "").split("?")[0].strip()
            st = by_cid.get(cid) if cid else None
            if not st and url_key:
                st = by_url.get(url_key)
            st = st or {"total": 0, "done": 0, "pending": 0, "failed": 0}
            total = int(st.get("total") or 0)
            done = int(st.get("done") or 0)
            pending = int(st.get("pending") or 0)
            failed = int(st.get("failed") or 0)

            meta = meta_by_url.get(url_key) or (meta_by_cid.get(cid) if cid else None) or {}
            crawl_status = meta.get("crawl_status") or "pending"
            no_videos = crawl_status == "empty"

            item["video_total"] = total
            item["video_done"] = done
            item["video_pending"] = pending
            item["video_failed"] = failed
            item["crawl_status"] = crawl_status
            item["crawl_note"] = meta.get("crawl_note") or ""
            item["no_videos"] = no_videos
            item["completed"] = no_videos or (
                total > 0 and pending == 0 and failed == 0
            )
            enriched.append(item)

        return {
            "courses": enriched,
            "account": acc,
            "session_active": session_active,
            "persisted": bool(enriched),
        }

    def start_crawl(
        self,
        courses_data: List[Dict[str, Any]],
        account_name: Optional[str] = None,
        sync_all: bool = False,
    ) -> Dict[str, Any]:
        def task():
            cfg = self.get_cfg()
            store = self.get_store()
            acc_name = account_name or self._discover_account or cfg.accounts[0].name
            courses = [course_from_dict(c) for c in courses_data]
            if not courses:
                raise ValueError("未选择课程")

            self._ensure_discover_session(acc_name)

            with self._lock:
                if self._job:
                    self._job.account = acc_name
                    self._job.message = "爬取视频链接中..."

            videos = crawl_videos_for_courses(
                self._discover_tab, courses, acc_name, cfg, acc_name,
                store=store, sync_all=sync_all,
            )
            n = save_videos_to_store(store, videos, cfg, sync_all=sync_all)
            log(acc_name, "已写入 %d 条视频" % n)
            empty_n = sum(
                1 for c in courses
                if store.get_course_crawl_meta_map(acc_name)["by_url"].get(
                    (c.url or "").split("?")[0], {}
                ).get("crawl_status") == "empty"
            )
            if empty_n:
                log(acc_name, "%d 门课程无视频，已标记为「无视频」" % empty_n)
            self._cleanup_discover_browser()
            with self._lock:
                if self._job:
                    self._job.message = "已写入 %d 条视频" % n
            return {"saved": n, "videos": len(videos)}

        return self._start_job("crawl", account_name, task)

    def start_run(self, account_name: Optional[str] = None) -> Dict[str, Any]:
        cfg = self.get_cfg()
        store = self.get_store()
        accounts = cfg.accounts
        if account_name:
            accounts = [a for a in cfg.accounts if a.name == account_name]
            if not accounts:
                raise ValueError("未找到账号: %s" % account_name)
        if not any(store.list_pending(a.name) for a in accounts):
            raise ValueError("没有 pending 视频，请先在「课程发现」中爬取")

        def task():
            with self._lock:
                if self._job:
                    self._job.message = "刷课进行中..."
            results = run_auto(
                self.get_cfg(), self.get_store(),
                account_name=account_name,
                cancel_event=self.cancel_event,
            )
            with self._lock:
                if self._job:
                    self._job.message = "刷课结束"
            return {"results": results}

        return self._start_job("run", account_name, task)

    def _cleanup_login_browser(self) -> None:
        quit_browser(self._login_browser)
        self._login_browser = None
        self._login_tab = None
        self._login_account = None

    def _cleanup_discover_browser(self) -> None:
        quit_browser(self._discover_browser)
        self._discover_browser = None
        self._discover_tab = None
        # 保留 courses 列表供前端展示

    def _ensure_discover_session(self, account_name: str) -> None:
        """爬取前确保浏览器已打开且已登录（历史课程列表也可直接爬取）"""
        cfg = self.get_cfg()
        if (
            self._discover_tab is not None
            and self._discover_account == account_name
        ):
            return

        matched = [a for a in cfg.accounts if a.name == account_name]
        if not matched:
            raise ValueError("未找到账号: %s" % account_name)
        acc = matched[0]
        index = cfg.accounts.index(acc)

        self._cleanup_discover_browser()
        browser, tab = create_browser(acc, index, cfg)
        self._discover_browser = browser
        self._discover_tab = tab
        self._discover_account = acc.name

        with self._lock:
            if self._job:
                self._job.message = "正在打开浏览器并检查登录..."

        store = self.get_store()
        if not wait_qr_login(
            tab, acc.name, cfg.home_url,
            confirm_event=self.confirm_event,
            cancel_event=self.cancel_event,
        ):
            self._cleanup_discover_browser()
            raise RuntimeError("未登录，无法爬取")

        sync_account_profile(tab, acc.name, cfg, store)
