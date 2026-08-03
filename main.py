# -*- coding: utf-8 -*-
"""
雨课堂通用刷课工具 CLI

用法:
  python main.py web
  python main.py login
  python main.py discover
  python main.py run
  python main.py run --account 账号1
  python main.py status
  python main.py reset --course <course_url>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 保证包可导入
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from yuketang_bot.config import load_config
from yuketang_bot.discover import run_discover
from yuketang_bot.runner import run_auto, run_login
from yuketang_bot.store import Store


def cmd_login(args):
    cfg = load_config(args.config)
    run_login(cfg)


def cmd_discover(args):
    cfg = load_config(args.config)
    store = Store(cfg.db_path)
    account = None
    if args.account:
        matched = [a for a in cfg.accounts if a.name == args.account]
        if not matched:
            print("未找到账号:", args.account)
            return 1
        account = matched[0]
    n = run_discover(cfg, store, account=account)
    print("\n发现完成，共写入 %d 条视频。下一步: python main.py run" % n)
    return 0


def cmd_run(args):
    cfg = load_config(args.config)
    store = Store(cfg.db_path)
    try:
        run_auto(cfg, store, account_name=args.account)
    except ValueError as e:
        print("错误:", e)
        return 1
    return 0


def cmd_status(args):
    cfg = load_config(args.config)
    store = Store(cfg.db_path)
    summary = store.get_status_summary()
    courses = store.get_course_summary()

    print("=" * 60)
    print("账号进度")
    print("=" * 60)
    if not summary:
        print("(空) 请先运行 python main.py discover")
    for s in summary:
        print(
            "  %s: total=%d pending=%d done=%d failed=%d"
            % (
                s["account_name"],
                s["total"],
                s.get("pending", 0),
                s.get("done", 0),
                s.get("failed", 0),
            )
        )

    print("\n" + "=" * 60)
    print("课程进度")
    print("=" * 60)
    if not courses:
        print("(空)")
    for account_name, course_url, total, done in courses:
        print("  [%s] %d/%d" % (account_name, done, total))
        print("       %s" % course_url)
    print("=" * 60)
    return 0


def cmd_reset(args):
    cfg = load_config(args.config)
    store = Store(cfg.db_path)
    if not args.course:
        print("请指定 --course <course_url>")
        return 1
    n = store.reset_course(args.course, account_name=args.account)
    print("已重置 %d 条视频为 pending" % n)
    return 0


def cmd_web(args):
    from yuketang_bot.web.app import run_server

    # 预加载配置，尽早报错
    load_config(args.config)
    print("=" * 60)
    print("雨课堂本地控制台")
    print("地址: http://127.0.0.1:%d/" % args.port)
    print("仅绑定本机回环地址，数据不离开本机")
    print("=" * 60)
    run_server(
        host="127.0.0.1",
        port=args.port,
        config_path=args.config,
        open_browser=not args.no_browser,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="yuketang-bot",
        description="雨课堂通用刷课工具：Web 控制台 / 扫码登录 / 发现课程 / 刷课",
    )
    p.add_argument(
        "-c", "--config",
        default=None,
        help="配置文件路径（默认 config.yaml）",
    )
    sub = p.add_subparsers(dest="command", required=True)

    p_web = sub.add_parser("web", help="启动本地网页控制台（推荐）")
    p_web.add_argument("--port", type=int, default=18765, help="端口，默认 18765")
    p_web.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    p_web.set_defaults(func=cmd_web)

    p_login = sub.add_parser("login", help="扫码登录，保存 browser profile")
    p_login.set_defaults(func=cmd_login)

    p_discover = sub.add_parser("discover", help="主页发现课程并爬取视频链接")
    p_discover.add_argument("--account", default=None, help="指定账号名")
    p_discover.set_defaults(func=cmd_discover)

    p_run = sub.add_parser("run", help="开始刷课（断点续刷）")
    p_run.add_argument("--account", default=None, help="只刷指定账号")
    p_run.set_defaults(func=cmd_run)

    p_status = sub.add_parser("status", help="查看任务进度")
    p_status.set_defaults(func=cmd_status)

    p_reset = sub.add_parser("reset", help="重置某课程状态为 pending")
    p_reset.add_argument("--course", required=True, help="课程 URL")
    p_reset.add_argument("--account", default=None, help="只重置指定账号")
    p_reset.set_defaults(func=cmd_reset)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    code = args.func(args)
    if code is None:
        code = 0
    return code


if __name__ == "__main__":
    sys.exit(main())
