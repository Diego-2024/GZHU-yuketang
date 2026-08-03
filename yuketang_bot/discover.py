# -*- coding: utf-8 -*-
"""主页发现课程 + 课程页爬取视频链接"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin

from .browser import cookies_dict, create_browser, quit_browser, wait_qr_login
from .models import Account, AppConfig, Course, TaskStatus, Video
from .store import Store
from .utils import (
    course_key_from_url,
    is_course_url,
    is_video_url,
    log,
    normalize_url,
    parse_course_url,
    parse_selection,
    parse_video_url,
)


# ---------- 课程发现 ----------

def _collect_links_from_dom(tab, base: str) -> List[Tuple[str, str]]:
    """从 DOM 收集 (text, href) 列表"""
    js = """
    const out = [];
    const seen = new Set();
    document.querySelectorAll('a[href]').forEach(a => {
        const href = a.href || a.getAttribute('href') || '';
        if (!href || seen.has(href)) return;
        seen.add(href);
        const text = (a.innerText || a.textContent || a.getAttribute('title') || '').trim();
        out.push({href, text: text.slice(0, 200)});
    });
    return out;
    """
    try:
        items = tab.run_js(js) or []
    except Exception:
        items = []

    result = []
    for item in items:
        if isinstance(item, dict):
            href = normalize_url(item.get("href", ""), base)
            text = (item.get("text") or "").strip()
        else:
            continue
        if href:
            result.append((text, href))
    return result


def _student_log_id(url: str) -> str:
    m = re.search(r"/v2/web/studentLog/(\d+)", url or "")
    return m.group(1) if m else ""


def _courses_from_links(links: List[Tuple[str, str]]) -> List[Course]:
    courses: List[Course] = []
    seen: Set[str] = set()
    for text, href in links:
        # 主页常见入口：/v2/web/studentLog/{classroom_id}
        slog_id = _student_log_id(href)
        if slog_id:
            key = "studentLog/%s" % slog_id
            if key in seen:
                continue
            seen.add(key)
            name = re.sub(r"\s+", " ", text or "").strip() or ("课程 %s" % slog_id)
            courses.append(Course(
                name=name,
                url=href.split("?")[0],
                lms_path="",
                classroom_id=slog_id,
            ))
            continue

        if not is_course_url(href) and not is_video_url(href):
            continue
        # 视频链接归到所属课程主页
        if is_video_url(href):
            info = parse_video_url(href)
            course_url = re.sub(r"/video/[^/?#]+.*$", "", href)
        else:
            info = parse_course_url(href)
            if not info:
                continue
            # 去掉 /video/... 之后的章节路径，保留 /pro/lms/x/y
            m = re.match(
                r"(https?://[^/]+/(?:pro|v)/lms/[^/]+/[^/?#]+)", href
            )
            course_url = m.group(1) if m else href.split("?")[0]

        key = course_key_from_url(course_url)
        if key in seen:
            continue
        seen.add(key)
        name = text or ("课程 %s" % info.get("classroom_id", key))
        # 清洗名称：去掉多余空白/换行
        name = re.sub(r"\s+", " ", name).strip() or key
        courses.append(Course(
            name=name,
            url=course_url,
            lms_path=info.get("lms_path", ""),
            classroom_id=info.get("classroom_id", ""),
        ))
    return courses


def _parse_lms_from_iframe_src(src: str) -> Optional[Dict[str, str]]:
    """从学习内容 iframe src 解析 sign / classroom_id / university_id"""
    if not src:
        return None
    m = re.search(r"(https?://[^/]+)/(?:pro|v)/lms/([^/]+)/([^/?#]+)/", src)
    if not m:
        return None
    uv = ""
    um = re.search(r"[?&]university_id=(\d+)", src)
    if um:
        uv = um.group(1)
    origin, lms_path, classroom_id = m.group(1), m.group(2), m.group(3)
    return {
        "lms_path": lms_path,
        "classroom_id": classroom_id,
        "university_id": uv,
        "course_url": "%s/pro/lms/%s/%s" % (origin, lms_path, classroom_id),
    }


def _resolve_course_url(tab, course: Course, tag: str) -> Course:
    """若入口是 studentLog，进入后从学习内容 iframe 解析 /pro/lms/{sign}/{cid}"""
    if course.lms_path and is_course_url(course.url) and not _student_log_id(course.url):
        return course

    # 确保走 studentLog + tab=content，才能出现学习内容 iframe
    cid = course.classroom_id or _student_log_id(course.url)
    if not cid and is_course_url(course.url):
        info = parse_course_url(course.url) or {}
        cid = info.get("classroom_id", "")
        if info.get("lms_path"):
            return course

    if not cid:
        log(tag, "无法解析 classroom_id，跳过: %s" % course.url)
        return course

    uv = course.university_id or ""
    entry = (
        "https://www.yuketang.cn/v2/web/studentLog/%s"
        "?university_id=%s&platform_id=3&classroom_id=%s&tab=content"
        % (cid, uv or "0", cid)
    )
    log(tag, "解析课程真实地址: %s" % entry)
    tab.get(entry)
    tab.wait.doc_loaded(timeout=30)
    time.sleep(2)

    # 点「学习内容」确保 iframe 出现
    try:
        tab.run_js(
            """
            const items = [...document.querySelectorAll('.rain-tabs__nav-item, .rain-tabs__nav-item-text')];
            const el = items.find(e => (e.innerText||'').trim() === '学习内容');
            if (el) { el.click(); if (el.parentElement) el.parentElement.click(); }
            """
        )
        time.sleep(2)
    except Exception:
        pass

    # 等 iframe
    iframe_src = ""
    for _ in range(15):
        try:
            iframe_src = tab.run_js(
                "var f=document.querySelector('iframe.tab-pane-content-iframe, iframe[src*=\"/pro/lms/\"]');"
                "return f ? f.src : '';"
            ) or ""
        except Exception:
            iframe_src = ""
        if iframe_src and "/pro/lms/" in iframe_src:
            break
        time.sleep(0.8)

    parsed = _parse_lms_from_iframe_src(iframe_src)
    if parsed:
        course_url = parsed.get("course_url") or (
            "https://www.yuketang.cn/pro/lms/%s/%s"
            % (parsed["lms_path"], parsed["classroom_id"])
        )
        log(tag, "解析到 lms: %s" % course_url)
        return Course(
            name=course.name,
            url=course_url,
            lms_path=parsed["lms_path"],
            classroom_id=parsed["classroom_id"],
            university_id=parsed.get("university_id") or uv,
        )

    # 当前 URL / 页面链接兜底
    try:
        cur = tab.url or ""
    except Exception:
        cur = ""
    if is_course_url(cur) or is_video_url(cur):
        m = re.match(r"(https?://[^/]+/(?:pro|v)/lms/[^/]+/[^/?#]+)", cur)
        if m:
            info = parse_course_url(m.group(1)) or {}
            return Course(
                name=course.name,
                url=m.group(1),
                lms_path=info.get("lms_path", ""),
                classroom_id=info.get("classroom_id", cid),
                university_id=uv,
            )

    log(tag, "未能解析到 /pro/lms/ 地址，仍使用原 URL")
    return course


def _courses_from_api(tab, base_url: str, tag: str) -> List[Course]:
    """
    兜底：通过页面内 fetch / 已知接口拉取课程列表。
    雨课堂常见接口会随版本变化，失败则返回空列表。
    """
    endpoints = [
        "/v2/api/web/courses/list?identity=2",
        "/v2/api/web/courses/list?identity=1",
        "/mooc-api/v1/lms/user/user-courses/?status=1&page=1&page_size=50",
        "/api/v3/classroom/on-lesson-courses",
        "/v/course_meta/user_courses",
    ]
    courses: List[Course] = []
    seen: Set[str] = set()

    for ep in endpoints:
        url = urljoin(base_url.rstrip("/") + "/", ep.lstrip("/"))
        js = """
        const url = arguments[0];
        return fetch(url, {credentials: 'include'})
            .then(r => r.ok ? r.json() : null)
            .then(j => j)
            .catch(e => null);
        """
        try:
            data = tab.run_js(js, url)
        except Exception:
            # 某些 DrissionPage 版本不支持传参，改用字符串拼接
            js2 = (
                "return fetch(%s, {credentials:'include'})"
                ".then(r => r.ok ? r.json() : null).catch(e => null);"
                % json.dumps(url)
            )
            try:
                data = tab.run_js(js2)
            except Exception as exc:
                log(tag, "API 探测失败 %s: %s" % (ep, exc))
                continue

        if not data:
            continue

        found = _parse_course_api_payload(data, base_url)
        for c in found:
            key = course_key_from_url(c.url)
            if key in seen:
                continue
            seen.add(key)
            courses.append(c)

        if courses:
            log(tag, "API %s 发现 %d 门课程" % (ep, len(found)))
            break

    return courses


def _parse_course_api_payload(data: Any, base_url: str) -> List[Course]:
    """解析 /v2/api/web/courses/list 等接口，入口统一为 studentLog"""
    courses: List[Course] = []
    items: List[Any] = []

    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        for key in ("data", "course_list", "product_list", "results", "list", "courses"):
            val = data.get(key)
            if isinstance(val, list):
                items = val
                break
            if isinstance(val, dict):
                for k2 in ("product_list", "course_list", "list", "results", "classroom_list"):
                    if isinstance(val.get(k2), list):
                        items = val[k2]
                        break
                if items:
                    break

    base = (base_url or "https://www.yuketang.cn").rstrip("/")

    for item in items:
        if not isinstance(item, dict):
            continue
        course_obj = item.get("course") if isinstance(item.get("course"), dict) else {}
        classroom_id = str(
            item.get("classroom_id")
            or item.get("classroomid")
            or ""
        )
        if not classroom_id:
            continue

        course_name = str(course_obj.get("name") or item.get("name") or "")
        class_name = str(item.get("name") or "")
        if course_name and class_name and class_name != course_name:
            name = "%s · %s" % (course_name, class_name)
        else:
            name = course_name or class_name or ("课程 %s" % classroom_id)

        uv = str(
            course_obj.get("university_id")
            or item.get("university_id")
            or "0"
        )
        lms_path = str(
            item.get("sign")
            or item.get("course_sign")
            or item.get("lms_path")
            or ""
        )
        # 列表接口通常没有 short sign，先用 studentLog 入口，后续再解析 iframe
        if lms_path and not re.match(r"^\d", lms_path) and "-" not in lms_path:
            course_url = "%s/pro/lms/%s/%s" % (base, lms_path, classroom_id)
        else:
            lms_path = ""
            course_url = (
                "%s/v2/web/studentLog/%s"
                "?university_id=%s&platform_id=3&classroom_id=%s"
                % (base, classroom_id, uv, classroom_id)
            )

        courses.append(Course(
            name=re.sub(r"\s+", " ", name).strip(),
            url=course_url,
            lms_path=lms_path,
            classroom_id=classroom_id,
            university_id=uv,
        ))
    return courses


def discover_courses(tab, cfg: AppConfig, tag: str) -> List[Course]:
    """打开主页，优先 API 发现「我听的课」"""
    home = cfg.home_url
    log(tag, "打开主页: %s" % home)
    tab.get(home)
    tab.wait.doc_loaded(timeout=30)
    time.sleep(3)

    # 点「我听的课」
    try:
        tab.run_js(
            """
            const tabs=[...document.querySelectorAll('[role=tab], .el-tabs__item, span, div')];
            const t=tabs.find(e=>(e.innerText||'').trim()==='我听的课');
            if(t) t.click();
            """
        )
        time.sleep(1.5)
    except Exception:
        pass

    # 主路径：课程列表 API（DOM 卡片无 href）
    log(tag, "通过 API 发现课程: /v2/api/web/courses/list?identity=2")
    courses = _courses_from_api(tab, cfg.base_url, tag)

    if not courses:
        log(tag, "API 未命中，尝试 DOM 链接兜底...")
        for _ in range(3):
            try:
                tab.run_js("window.scrollTo(0, document.body.scrollHeight);")
            except Exception:
                pass
            time.sleep(0.8)
        links = _collect_links_from_dom(tab, cfg.base_url)
        courses = _courses_from_links(links)

    uniq: Dict[str, Course] = {}
    for c in courses:
        key = c.classroom_id or course_key_from_url(c.url)
        uniq[key] = c
    courses = list(uniq.values())
    for c in courses:
        log(tag, "  course: %s | %s" % (c.name[:40], c.url))
    log(tag, "共发现 %d 门课程" % len(courses))
    return courses


# ---------- 视频发现 ----------

def _expand_chapters(tab, tag: str) -> None:
    """尝试展开章节树 / 滚动加载"""
    # 点击常见「展开」按钮
    selectors = [
        "text:展开",
        "text:全部展开",
        "css:.expand",
        "css:.chapter-title",
        "css:.section-title",
        "css:.el-icon-arrow-right",
        "css:.icon-arrow",
        "css:[class*='fold']",
        "css:[class*='expand']",
    ]
    for sel in selectors:
        try:
            eles = tab.eles(sel, timeout=1)
        except Exception:
            eles = []
        for ele in (eles or [])[:20]:
            try:
                ele.click()
                time.sleep(0.2)
            except Exception:
                pass

    for _ in range(8):
        try:
            tab.run_js("window.scrollBy(0, 800);")
        except Exception:
            pass
        time.sleep(0.4)
    try:
        tab.run_js("window.scrollTo(0, 0);")
    except Exception:
        pass
    time.sleep(0.5)


def _videos_from_dom(tab, course: Course, base: str) -> List[Video]:
    links = _collect_links_from_dom(tab, base)
    videos: List[Video] = []
    seen: Set[str] = set()
    for text, href in links:
        if not is_video_url(href):
            continue
        try:
            info = parse_video_url(href)
        except ValueError:
            continue
        vid = info["video_id"]
        if vid in seen:
            continue
        seen.add(vid)
        videos.append(Video(
            video_id=vid,
            video_url=href.split("?")[0],
            course_url=course.url,
            classroom_id=info["classroom_id"],
            lms_path=info["lms_path"],
            title=re.sub(r"\s+", " ", text).strip(),
            status=TaskStatus.PENDING,
        ))
    return videos


def _videos_from_api(tab, course: Course, tag: str) -> List[Video]:
    """通过章节目录 API 拉取视频叶子（leaf_type=0）"""
    classroom_id = course.classroom_id or (parse_course_url(course.url) or {}).get("classroom_id", "")
    lms = course.lms_path or (parse_course_url(course.url) or {}).get("lms_path", "")
    if not classroom_id or not lms:
        return []

    origin = re.match(r"https?://[^/]+", course.url)
    base = origin.group(0) if origin else "https://www.yuketang.cn"
    uv = course.university_id or "0"

    ep = (
        "/mooc-api/v1/lms/learn/course/chapter"
        "?cid=%s&term=latest&uv_id=%s&sign=%s" % (classroom_id, uv, lms)
    )
    url = urljoin(base + "/", ep.lstrip("/"))
    # 也可在主站请求（已验证 www.yuketang.cn 可用）
    urls = [
        url,
        "https://www.yuketang.cn" + ep,
    ]
    headers = {
        "xtbz": "ykt",
        "x-requested-with": "XMLHttpRequest",
        "university-id": str(uv),
        "classroom-id": str(classroom_id),
    }

    for api_url in urls:
        js = (
            "return fetch(%s, {credentials:'include', headers:%s})"
            ".then(r => r.ok ? r.json() : null).catch(e => null);"
            % (json.dumps(api_url), json.dumps(headers))
        )
        try:
            data = tab.run_js(js)
        except Exception as exc:
            log(tag, "章节 API 失败 %s: %s" % (api_url, exc))
            continue
        if not data:
            continue

        leaves = _extract_video_leaves(data)
        videos: List[Video] = []
        seen: Set[str] = set()
        for leaf in leaves:
            vid = str(leaf.get("video_id") or "")
            if not vid or vid in seen:
                continue
            seen.add(vid)
            video_url = "%s/pro/lms/%s/%s/video/%s" % (base, lms, classroom_id, vid)
            videos.append(Video(
                video_id=vid,
                video_url=video_url,
                course_url=course.url.split("?")[0],
                classroom_id=str(classroom_id),
                lms_path=lms,
                title=str(leaf.get("title") or ""),
                status=TaskStatus.PENDING,
            ))
        if videos:
            log(tag, "章节 API 发现 %d 个视频" % len(videos))
            return videos
    return []


def _extract_video_leaves(data: Any) -> List[Dict[str, Any]]:
    """递归提取视频叶子：leaf_type=0 为视频（6=习题，4=讨论等，排除）"""
    leaves: List[Dict[str, Any]] = []

    def walk(node):
        if isinstance(node, list):
            for x in node:
                walk(x)
            return
        if not isinstance(node, dict):
            return
        leaf_type = node.get("leaf_type")
        # 严格：0 或 "0" 或 video
        is_video = leaf_type == 0 or leaf_type == "0" or str(leaf_type).lower() == "video"
        if is_video and node.get("id"):
            leaves.append({
                "video_id": node.get("id"),
                "title": node.get("name") or node.get("title") or "",
            })
        for v in node.values():
            if isinstance(v, (dict, list)):
                walk(v)

    walk(data)
    return leaves


def discover_videos_for_course(tab, course: Course, tag: str, base_url: str) -> List[Video]:
    log(tag, "进入课程: %s" % course.name)
    log(tag, "  url: %s" % course.url)

    # 先解析 sign（studentLog -> iframe）
    if not course.lms_path or _student_log_id(course.url):
        course = _resolve_course_url(tab, course, tag)

    if not course.lms_path:
        log(tag, "无 lms_path，无法拉取章节")
        return []

    # 优先章节 API（比 DOM 可靠）
    videos = _videos_from_api(tab, course, tag)
    if videos:
        for i, v in enumerate(videos[:10], 1):
            log(tag, "  video[%d] %s %s" % (i, v.video_id, v.title or v.video_url))
        if len(videos) > 10:
            log(tag, "  ... 共 %d 个视频" % len(videos))
        else:
            log(tag, "  共 %d 个视频" % len(videos))
        return videos

    # DOM 兜底：打开 studycontent
    study = "%s/pro/lms/%s/%s/studycontent" % (
        re.match(r"https?://[^/]+", course.url).group(0)
        if re.match(r"https?://[^/]+", course.url)
        else base_url.rstrip("/"),
        course.lms_path,
        course.classroom_id,
    )
    log(tag, "API 无结果，打开学习内容页: %s" % study)
    tab.get(study)
    tab.wait.doc_loaded(timeout=30)
    time.sleep(2)
    _expand_chapters(tab, tag)

    videos = _videos_from_dom(tab, course, base_url)
    if not videos:
        log(tag, "DOM 未找到视频链接")

    # 打印预览
    for i, v in enumerate(videos[:10], 1):
        log(tag, "  video[%d] %s %s" % (i, v.video_id, v.title or v.video_url))
    if len(videos) > 10:
        log(tag, "  ... 共 %d 个视频" % len(videos))
    else:
        log(tag, "  共 %d 个视频" % len(videos))
    return videos


def prompt_select_courses(courses: List[Course]) -> List[Course]:
    if not courses:
        print("未发现任何课程，请确认已登录且主页有课程。")
        return []
    print("\n" + "=" * 60)
    print("发现以下课程：")
    for i, c in enumerate(courses, 1):
        print("  [%d] %s" % (i, c.name))
        print("       %s" % c.url)
    print("=" * 60)
    print("请选择要刷的课程（示例: 1,3 或 1-3 或 all，回车=全部）:")
    text = input("> ").strip()
    idxs = parse_selection(text, len(courses))
    selected = [courses[i] for i in idxs]
    print("已选择 %d 门课程" % len(selected))
    return selected


def course_to_dict(course: Course) -> Dict[str, str]:
    return {
        "name": course.name,
        "url": course.url,
        "lms_path": course.lms_path,
        "classroom_id": course.classroom_id,
        "university_id": course.university_id,
    }


def course_from_dict(data: Dict[str, Any]) -> Course:
    return Course(
        name=str(data.get("name") or ""),
        url=str(data.get("url") or ""),
        lms_path=str(data.get("lms_path") or ""),
        classroom_id=str(data.get("classroom_id") or ""),
        university_id=str(data.get("university_id") or ""),
    )


def crawl_videos_for_courses(
    tab,
    courses: List[Course],
    account_name: str,
    cfg: AppConfig,
    tag: str,
    store=None,
    sync_all: bool = False,
) -> List[Video]:
    """对已选课程解析真实地址并爬取视频链接（无交互）"""
    all_videos: List[Video] = []
    for course in courses:
        vids = discover_videos_for_course(tab, course, tag, cfg.base_url)
        for v in vids:
            v.account_name = account_name
        all_videos.extend(vids)
        if store is not None:
            note = ""
            if not vids:
                if not course.lms_path:
                    note = "无法解析课程内容页"
                else:
                    note = "章节中无视频"
            targets = [a.name for a in cfg.accounts] if sync_all else [account_name]
            for acc in targets:
                store.mark_course_crawl(
                    acc,
                    course.url,
                    len(vids),
                    classroom_id=course.classroom_id,
                    course_name=course.name,
                    crawl_note=note,
                )
    return all_videos


def save_videos_to_store(
    store: Store,
    videos: List[Video],
    cfg: AppConfig,
    sync_all: bool = False,
) -> int:
    if not videos:
        return 0
    if sync_all and len(cfg.accounts) > 1:
        batch: List[Video] = []
        for a in cfg.accounts:
            for v in videos:
                batch.append(Video(
                    video_id=v.video_id,
                    video_url=v.video_url,
                    account_name=a.name,
                    course_url=v.course_url,
                    classroom_id=v.classroom_id,
                    lms_path=v.lms_path,
                    title=v.title,
                    status=TaskStatus.PENDING,
                ))
        return store.save_videos(batch)
    return store.save_videos(videos)


def run_discover(
    cfg: AppConfig,
    store: Store,
    account: Optional[Account] = None,
    sync_all: Optional[bool] = None,
) -> int:
    """
    CLI：登录 → 发现课程 → 用户选择 → 爬视频 → 写入 DB
    返回写入的视频条数。
    """
    total_saved = 0

    for acc in cfg.accounts:
        if account and acc.name != account.name:
            continue
        real_index = cfg.accounts.index(acc)
        browser = None
        tag = acc.name
        try:
            browser, tab = create_browser(acc, real_index, cfg)
            if not wait_qr_login(tab, tag, cfg.home_url):
                continue

            courses = discover_courses(tab, cfg, tag)
            selected = prompt_select_courses(courses)
            if not selected:
                continue

            all_videos = crawl_videos_for_courses(
                tab, selected, acc.name, cfg, tag
            )

            if sync_all is None:
                if not account and len(cfg.accounts) > 1:
                    print("\n是否把视频清单同步到所有账号？[Y/n]")
                    ans = input("> ").strip().lower()
                    do_sync = ans in ("", "y", "yes", "是")
                else:
                    do_sync = False
            else:
                do_sync = bool(sync_all)

            n = save_videos_to_store(store, all_videos, cfg, sync_all=do_sync)
            total_saved += n
            log(tag, "已写入 %d 条视频到数据库" % n)
            break
        except Exception as e:
            log(tag, "discover 失败: %s" % e)
            import traceback
            traceback.print_exc()
        finally:
            quit_browser(browser)

    return total_saved
