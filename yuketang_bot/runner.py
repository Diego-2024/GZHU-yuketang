# -*- coding: utf-8 -*-
"""多线程刷课调度"""

from __future__ import annotations

import threading
import time
import traceback
from typing import Dict, List, Optional

from .api import (
    YuketangClient,
    apply_shared_video,
    build_config,
    get_shared_cache_keys,
    probe_watch_progress,
)
from .browser import (
    capture_from_tab,
    cookies_dict,
    create_browser,
    quit_browser,
    wait_qr_login,
)
from .models import Account, AppConfig, TaskStatus
from .store import Store
from .utils import log, origin_from_url


def _base_from_video_url(url: str, fallback: str) -> str:
    origin = origin_from_url(url)
    return origin or fallback


def account_worker(
    account: Account,
    index: int,
    cfg: AppConfig,
    store: Store,
    results: Dict[str, int],
    cancel_event: Optional[threading.Event] = None,
    confirm_event: Optional[threading.Event] = None,
) -> None:
    tag = account.name
    browser = None
    ok = 0
    pending = store.list_pending(tag)
    total = len(pending)
    try:
        if not pending:
            log(tag, "无 pending 视频，跳过")
            results[tag] = 0
            return

        browser, tab = create_browser(account, index, cfg)
        login_url = cfg.home_url
        if not wait_qr_login(
            tab, tag, login_url,
            confirm_event=confirm_event,
            cancel_event=cancel_event,
        ):
            results[tag] = 0
            return

        cookies = cookies_dict(tab)
        for i, video_row in enumerate(pending, 1):
            if cancel_event is not None and cancel_event.is_set():
                log(tag, "收到取消，停止刷课")
                break
            url = video_row.video_url
            log(tag, ">>> video [%d/%d] %s" % (i, total, url))
            base = _base_from_video_url(url, cfg.base_url)
            try:
                # 先查进度：已完成 100%（或达 target_rate）则跳过，不打开播放器
                progress = probe_watch_progress(
                    cookies, url, base_url=base,
                    uv_id=cookies.get("university_id", ""),
                )
                if progress and YuketangClient.is_done(
                    progress, cfg.loop.target_rate
                ):
                    rate_pct = float(progress.get("rate", 0) or 0) * 100
                    log(
                        tag,
                        "skip: already %.1f%% completed=%s"
                        % (rate_pct, progress.get("completed")),
                    )
                    store.mark_done(tag, video_row.video_id)
                    store.log_progress(
                        tag, video_row.video_id,
                        float(progress.get("last_point", 0) or 0),
                        float(progress.get("rate", 0) or 0),
                        int(progress.get("completed", 0) or 0),
                    )
                    ok += 1
                    continue

                capture = capture_from_tab(
                    tab, url, base, tag, listen_timeout=cfg.listen_timeout
                )
                # 抓包后 cookie 可能更新
                cookies = capture.get("cookies") or cookies_dict(tab)
                auth, video, loop = build_config(capture, cfg.loop)
                video_id = video["video_id"]
                auth, video, loop = apply_shared_video(auth, video, loop, video_id)
                log(tag, "user_id=%s video=%s sq=%s" % (
                    auth["user_id"], video_id, loop["start_sq"],
                ))

                def on_progress(info, _aid=tag, _vid=video_id):
                    store.log_progress(
                        _aid, _vid,
                        float(info.get("last_point", 0) or 0),
                        float(info.get("rate", 0) or 0),
                        int(info.get("completed", 0) or 0),
                    )

                client = YuketangClient(auth, loop, tag=tag)
                if client.run(video, on_progress=on_progress):
                    store.mark_done(tag, video_row.video_id)
                    ok += 1
                else:
                    store.mark_failed(tag, video_row.video_id)
            except Exception as e:
                log(tag, "fail: %s" % e)
                traceback.print_exc()
                store.mark_failed(tag, video_row.video_id)

        results[tag] = ok
    except Exception as e:
        log(tag, "fatal: %s" % e)
        traceback.print_exc()
        results[tag] = ok
    finally:
        log(tag, "done %d/%d videos" % (ok, total))
        quit_browser(browser)


def run_login(cfg: AppConfig) -> int:
    """扫码登录所有账号，保存 profile"""
    print("=" * 60)
    print("扫码登录模式")
    print("每个账号会依次打开浏览器，请扫码登录后按 Enter")
    print("登录信息保存在:", cfg.profiles_root)
    print("=" * 60)

    ok = 0
    for index, account in enumerate(cfg.accounts):
        tag = account.name
        browser = None
        try:
            browser, tab = create_browser(account, index, cfg)
            if wait_qr_login(tab, tag, cfg.home_url):
                ok += 1
            time.sleep(1)
        except Exception as e:
            log(tag, "失败: %s" % e)
            traceback.print_exc()
        finally:
            quit_browser(browser)

    print("\n" + "=" * 60)
    print("登录完成: %d/%d 个账号" % (ok, len(cfg.accounts)))
    if ok == len(cfg.accounts):
        print("下一步: python main.py discover")
    print("=" * 60)
    return ok


def run_auto(
    cfg: AppConfig,
    store: Store,
    account_name: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, int]:
    accounts: List[Account] = cfg.accounts
    if account_name:
        accounts = [a for a in cfg.accounts if a.name == account_name]
        if not accounts:
            raise ValueError("未找到账号: %s" % account_name)

    any_pending = False
    for a in accounts:
        if store.list_pending(a.name):
            any_pending = True
            break
    if not any_pending:
        raise ValueError("没有 pending 视频，请先运行 discover")

    print("=" * 60)
    print("自动刷课: %d 账号" % len(accounts))
    print("profile 目录:", cfg.profiles_root)
    print("数据库:", cfg.db_path)
    print("=" * 60)

    results: Dict[str, int] = {}
    threads = []
    for account in accounts:
        index = cfg.accounts.index(account)
        t = threading.Thread(
            target=account_worker,
            args=(account, index, cfg, store, results),
            kwargs={"cancel_event": cancel_event},
            name=account.name,
            daemon=True,
        )
        threads.append(t)
        t.start()
        time.sleep(2)

    for t in threads:
        t.join()

    print("\n" + "=" * 60)
    print("summary:")
    for name, count in results.items():
        pending_left = len(store.list_pending(name))
        print("  %s: 本次完成 %d，剩余 pending %d" % (name, count, pending_left))
    print("shared video cache:", get_shared_cache_keys())
    print("=" * 60)
    return results
