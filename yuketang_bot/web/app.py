# -*- coding: utf-8 -*-
"""FastAPI 本地控制台"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .. import __version__
from ..config import (
    get_config_path,
    load_config,
    load_raw_config,
    save_raw_config,
    suggest_next_account,
)
from ..store import Store
from .jobs import JobManager
from .schemas import (
    AccountCreateRequest,
    AccountDeleteRequest,
    DiscoverCrawlRequest,
    LoginStartRequest,
    ResetRequest,
    RunRequest,
    SettingsUpdate,
)

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _resolve_static_dir() -> Path:
    """PyInstaller 打包后静态资源在 _MEIPASS 下"""
    if getattr(sys, "frozen", False):
        meipass = Path(getattr(sys, "_MEIPASS", ""))
        candidates = [
            meipass / "yuketang_bot" / "web" / "static",
            meipass / "static",
            Path(__file__).resolve().parent / "static",
        ]
        for c in candidates:
            if c.exists():
                return c
    return STATIC_DIR


def create_app(config_path: Optional[str] = None, bind_port: int = 18765) -> FastAPI:
    app = FastAPI(title="雨课堂本地控制台", version=__version__)
    jm = JobManager(config_path=config_path)
    app.state.jm = jm
    app.state.config_path = config_path
    app.state.bind_port = bind_port
    static_dir = _resolve_static_dir()

    # ---------- pages ----------

    @app.get("/")
    def index():
        return FileResponse(static_dir / "index.html")

    # ---------- runtime / summary ----------

    @app.get("/api/runtime")
    def api_runtime():
        cfg = load_config(config_path)
        return {
            "version": __version__,
            "bind_host": "127.0.0.1",
            "bind_port": bind_port,
            "db_path": cfg.db_path,
            "profiles_root": cfg.profiles_root,
            "config_path": str(get_config_path() or ""),
            "base_url": cfg.base_url,
            "home_url": cfg.home_url,
            "project_root": cfg.project_root,
        }

    @app.get("/api/summary")
    def api_summary():
        cfg = load_config(config_path)
        store = Store(cfg.db_path)
        accounts = store.get_status_summary()
        courses = [
            {
                "account_name": a,
                "course_url": u,
                "total": t,
                "done": d,
            }
            for a, u, t, d in store.get_course_summary()
        ]
        totals = {"pending": 0, "done": 0, "failed": 0, "total": 0}
        for s in accounts:
            for k in totals:
                totals[k] += s.get(k, 0)
        return {
            "accounts": accounts,
            "courses": courses,
            "totals": totals,
            "job": jm.current(),
        }

    @app.get("/api/accounts")
    def api_accounts():
        cfg = load_config(config_path)
        status = jm.login_status()
        status_map = {a["name"]: a for a in status.get("accounts", [])}
        out = []
        for acc in cfg.accounts:
            st = status_map.get(acc.name, {})
            out.append({
                "name": acc.name,
                "profile": acc.profile,
                "port": acc.port,
                "logged_in": st.get("logged_in", False),
                "login_session_active": st.get("login_session_active", False),
                "yuketang_name": st.get("yuketang_name", ""),
                "display_name": st.get("display_name") or acc.name,
                "user_id": st.get("user_id", ""),
            })
        return {"accounts": out}

    @app.post("/api/accounts/refresh")
    def api_accounts_refresh(account: Optional[str] = None):
        try:
            return jm.refresh_account_profiles(account_name=account)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/accounts/add")
    def api_accounts_add(
        body: AccountCreateRequest = Body(default_factory=AccountCreateRequest),
    ):
        cfg = load_config(config_path)
        raw = load_raw_config(config_path)

        name = (body.name or "").strip()
        profile = (body.profile or "").strip()
        auto_name, auto_profile = suggest_next_account(cfg)
        name = name or auto_name
        profile = profile or auto_profile

        for acc in cfg.accounts:
            if acc.name == name:
                raise HTTPException(409, "账号名已存在: %s" % name)
            if acc.profile == profile:
                raise HTTPException(409, "profile 已存在: %s" % profile)

        entry = {"name": name, "profile": profile, "port": None}
        raw.setdefault("accounts", []).append(entry)
        save_raw_config(raw, config_path)

        profile_dir = Path(cfg.profiles_root) / profile
        profile_dir.mkdir(parents=True, exist_ok=True)

        return {"ok": True, "account": entry, "total": len(raw["accounts"])}

    @app.post("/api/accounts/delete")
    def api_accounts_delete(body: AccountDeleteRequest):
        name = (body.name or "").strip()
        if not name:
            raise HTTPException(400, "请指定要删除的账号")

        raw = load_raw_config(config_path)
        cfg = load_config(config_path)
        if len(cfg.accounts) <= 1:
            raise HTTPException(400, "至少保留一个账号")

        current = jm.current()
        if current and current.get("state") == "running":
            job_acc = current.get("account")
            if not job_acc or job_acc == name:
                raise HTTPException(409, "有任务运行中，请先取消任务再删除账号")

        accounts = raw.get("accounts") or []
        matched = [a for a in accounts if (a.get("name") or "").strip() == name]
        if not matched:
            raise HTTPException(404, "账号不存在: %s" % name)

        raw["accounts"] = [
            a for a in accounts if (a.get("name") or "").strip() != name
        ]
        save_raw_config(raw, config_path)
        return {
            "ok": True,
            "deleted": name,
            "total": len(raw["accounts"]),
            "note": "仅移除配置，profile 目录与数据库视频记录仍保留",
        }

    # ---------- login ----------

    @app.post("/api/login/start")
    def api_login_start(body: Optional[LoginStartRequest] = None):
        body = body or LoginStartRequest()
        try:
            return jm.start_login(body.account)
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @app.post("/api/login/confirm")
    def api_login_confirm():
        return jm.confirm_login()

    @app.get("/api/login/status")
    def api_login_status(account: Optional[str] = None):
        return jm.login_status(account)

    # ---------- discover ----------

    @app.post("/api/discover/start")
    def api_discover_start(body: Optional[LoginStartRequest] = None):
        body = body or LoginStartRequest()
        try:
            return jm.start_discover(body.account)
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    @app.get("/api/discover/courses")
    def api_discover_courses(account: Optional[str] = None):
        return jm.get_courses(account_name=account)

    @app.post("/api/discover/crawl")
    def api_discover_crawl(body: DiscoverCrawlRequest):
        try:
            return jm.start_crawl(
                [c.model_dump() for c in body.courses],
                account_name=body.account,
                sync_all=body.sync_all,
            )
        except RuntimeError as e:
            raise HTTPException(409, str(e))

    # ---------- jobs / run ----------

    @app.post("/api/jobs/run")
    def api_jobs_run(body: Optional[RunRequest] = None):
        body = body or RunRequest()
        try:
            return jm.start_run(body.account)
        except RuntimeError as e:
            raise HTTPException(409, str(e))
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/jobs/cancel")
    def api_jobs_cancel():
        return jm.cancel()

    @app.get("/api/jobs/current")
    def api_jobs_current():
        return jm.current() or {"state": "idle"}

    # ---------- videos ----------

    @app.get("/api/videos")
    def api_videos(account: Optional[str] = None, status: Optional[str] = None):
        cfg = load_config(config_path)
        store = Store(cfg.db_path)
        videos = store.list_all_detailed(account)
        if status:
            videos = [v for v in videos if v.get("status") == status]
        return {"videos": videos}

    @app.post("/api/videos/reset")
    def api_videos_reset(body: ResetRequest):
        cfg = load_config(config_path)
        store = Store(cfg.db_path)
        n = store.reset_course(body.course_url, account_name=body.account)
        return {"reset": n}

    # ---------- settings ----------

    @app.get("/api/settings")
    def api_settings():
        cfg = load_config(config_path)
        raw = load_raw_config(config_path)
        return {
            "base_url": cfg.base_url,
            "home_url": cfg.home_url,
            "accounts": [
                {"name": a.name, "profile": a.profile, "port": a.port}
                for a in cfg.accounts
            ],
            "loop": cfg.loop.to_dict(),
            "base_port": cfg.base_port,
            "listen_timeout": cfg.listen_timeout,
            "db_path": raw.get("db_path", "./data/yuketang.db"),
            "profiles_root": raw.get("profiles_root", "./profiles"),
        }

    @app.put("/api/settings")
    def api_settings_update(body: SettingsUpdate):
        raw = load_raw_config(config_path)
        if body.base_url is not None:
            raw["base_url"] = body.base_url.rstrip("/")
        if body.home_url is not None:
            raw["home_url"] = body.home_url
        if body.accounts is not None:
            raw["accounts"] = [a.model_dump() for a in body.accounts]
        if body.loop is not None:
            raw["loop"] = body.loop.model_dump()
        if body.base_port is not None:
            raw["base_port"] = body.base_port
        if body.listen_timeout is not None:
            raw["listen_timeout"] = body.listen_timeout
        save_raw_config(raw, config_path)
        cfg = load_config(config_path)
        return {"ok": True, "accounts": len(cfg.accounts)}

    # ---------- SSE ----------

    @app.get("/api/events")
    async def api_events(request: Request):
        q = jm.subscribe()

        async def gen():
            try:
                yield "event: hello\ndata: {}\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        item = q.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.4)
                        yield ": keepalive\n\n"
                        continue
                    event = item.get("event", "message")
                    data = json.dumps(item.get("data", {}), ensure_ascii=False)
                    yield "event: %s\ndata: %s\n\n" % (event, data)
            finally:
                jm.unsubscribe(q)

        return StreamingResponse(
            gen(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


def run_server(
    host: str = "127.0.0.1",
    port: int = 18765,
    config_path: Optional[str] = None,
    open_browser: bool = True,
):
    import webbrowser

    import uvicorn

    # --windowed 打包后无控制台，sys.stdout/stderr 为 None，
    # uvicorn 默认日志 Formatter 会调用 isatty() 导致崩溃。
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")

    app = create_app(config_path=config_path, bind_port=port)
    if open_browser:
        url = "http://%s:%d/" % (host, port)

        def _open():
            import time
            time.sleep(0.8)
            webbrowser.open(url)

        import threading
        threading.Thread(target=_open, daemon=True).start()

    log_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": False,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": '%(levelprefix)s %(client_addr)s - "%(request_line)s" %(status_code)s',
                "use_colors": False,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
            "uvicorn.error": {"level": "INFO"},
            "uvicorn.access": {
                "handlers": ["access"],
                "level": "INFO",
                "propagate": False,
            },
        },
    }

    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        log_config=log_config,
        reload=False,
        workers=1,
    )
    server = uvicorn.Server(config)
    server.run()
