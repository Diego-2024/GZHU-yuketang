# -*- coding: utf-8 -*-
"""SQLite 持久化：视频清单与进度"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .models import TaskStatus, Video


class Store:
    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS videos (
                    account_name TEXT NOT NULL,
                    video_id TEXT NOT NULL,
                    course_url TEXT,
                    video_url TEXT NOT NULL,
                    classroom_id TEXT,
                    lms_path TEXT,
                    title TEXT,
                    status TEXT DEFAULT 'pending',
                    updated_at INTEGER,
                    PRIMARY KEY (account_name, video_id)
                );
                CREATE TABLE IF NOT EXISTS progress_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    video_id TEXT,
                    account_name TEXT,
                    last_point REAL,
                    rate REAL,
                    completed INTEGER,
                    ts INTEGER
                );
                CREATE INDEX IF NOT EXISTS idx_videos_status
                    ON videos(account_name, status);
                CREATE TABLE IF NOT EXISTS discovered_courses (
                    account_name TEXT NOT NULL,
                    course_url TEXT NOT NULL,
                    name TEXT,
                    lms_path TEXT,
                    classroom_id TEXT,
                    university_id TEXT,
                    discovered_at INTEGER,
                    PRIMARY KEY (account_name, course_url)
                );
                CREATE INDEX IF NOT EXISTS idx_discovered_account
                    ON discovered_courses(account_name);
                CREATE TABLE IF NOT EXISTS account_profiles (
                    account_name TEXT PRIMARY KEY,
                    yuketang_name TEXT,
                    user_id TEXT,
                    logged_in INTEGER DEFAULT 0,
                    updated_at INTEGER
                );
                CREATE TABLE IF NOT EXISTS course_crawl_meta (
                    account_name TEXT NOT NULL,
                    course_url TEXT NOT NULL,
                    classroom_id TEXT,
                    course_name TEXT,
                    crawl_status TEXT DEFAULT 'pending',
                    video_count INTEGER DEFAULT 0,
                    crawl_note TEXT,
                    crawled_at INTEGER,
                    PRIMARY KEY (account_name, course_url)
                );
                CREATE INDEX IF NOT EXISTS idx_course_crawl_account
                    ON course_crawl_meta(account_name);
                """
            )

    def save_videos(self, videos: List[Video], reset_status: bool = False) -> int:
        """写入/更新视频清单。已存在且非 reset 时保留 status。"""
        now = int(time.time())
        count = 0
        with self._connect() as conn:
            for v in videos:
                status = v.status.value if isinstance(v.status, TaskStatus) else str(v.status)
                if reset_status:
                    conn.execute(
                        """
                        INSERT INTO videos
                        (account_name, video_id, course_url, video_url,
                         classroom_id, lms_path, title, status, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(account_name, video_id) DO UPDATE SET
                            course_url=excluded.course_url,
                            video_url=excluded.video_url,
                            classroom_id=excluded.classroom_id,
                            lms_path=excluded.lms_path,
                            title=excluded.title,
                            status=excluded.status,
                            updated_at=excluded.updated_at
                        """,
                        (
                            v.account_name, v.video_id, v.course_url, v.video_url,
                            v.classroom_id, v.lms_path, v.title, status, now,
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO videos
                        (account_name, video_id, course_url, video_url,
                         classroom_id, lms_path, title, status, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(account_name, video_id) DO UPDATE SET
                            course_url=excluded.course_url,
                            video_url=excluded.video_url,
                            classroom_id=excluded.classroom_id,
                            lms_path=excluded.lms_path,
                            title=COALESCE(NULLIF(excluded.title, ''), videos.title),
                            updated_at=excluded.updated_at
                        """,
                        (
                            v.account_name, v.video_id, v.course_url, v.video_url,
                            v.classroom_id, v.lms_path, v.title, status, now,
                        ),
                    )
                count += 1
        return count

    def list_pending(self, account_name: str) -> List[Video]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM videos
                WHERE account_name=? AND status=?
                ORDER BY rowid
                """,
                (account_name, TaskStatus.PENDING.value),
            ).fetchall()
        return [self._row_to_video(r) for r in rows]

    def list_all(self, account_name: Optional[str] = None) -> List[Video]:
        with self._connect() as conn:
            if account_name:
                rows = conn.execute(
                    "SELECT * FROM videos WHERE account_name=? ORDER BY rowid",
                    (account_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM videos ORDER BY account_name, rowid"
                ).fetchall()
        return [self._row_to_video(r) for r in rows]

    def list_all_detailed(
        self, account_name: Optional[str] = None
    ) -> List[Dict]:
        """视频清单 + 最近一次进度（rate / last_point / completed）"""
        sql = """
            SELECT v.*,
                   p.rate AS progress_rate,
                   p.last_point AS progress_last_point,
                   p.completed AS progress_completed,
                   p.ts AS progress_ts
            FROM videos v
            LEFT JOIN (
                SELECT account_name, video_id, rate, last_point, completed, ts
                FROM progress_log
                WHERE id IN (
                    SELECT MAX(id) FROM progress_log
                    GROUP BY account_name, video_id
                )
            ) p ON p.account_name = v.account_name AND p.video_id = v.video_id
        """
        with self._connect() as conn:
            if account_name:
                rows = conn.execute(
                    sql + " WHERE v.account_name=? ORDER BY v.rowid",
                    (account_name,),
                ).fetchall()
            else:
                rows = conn.execute(
                    sql + " ORDER BY v.account_name, v.rowid"
                ).fetchall()
        out: List[Dict] = []
        for r in rows:
            out.append({
                "video_id": r["video_id"],
                "video_url": r["video_url"],
                "account_name": r["account_name"],
                "course_url": r["course_url"] or "",
                "classroom_id": r["classroom_id"] or "",
                "lms_path": r["lms_path"] or "",
                "title": r["title"] or "",
                "status": r["status"] or "pending",
                "updated_at": r["updated_at"],
                "rate": r["progress_rate"],
                "last_point": r["progress_last_point"],
                "completed": r["progress_completed"],
                "progress_ts": r["progress_ts"],
            })
        return out

    def save_discovered_courses(
        self, account_name: str, courses: List[Dict]
    ) -> int:
        """覆盖写入某账号的课程发现列表"""
        now = int(time.time())
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM discovered_courses WHERE account_name=?",
                (account_name,),
            )
            for c in courses:
                conn.execute(
                    """
                    INSERT INTO discovered_courses
                    (account_name, course_url, name, lms_path,
                     classroom_id, university_id, discovered_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        account_name,
                        c.get("url") or "",
                        c.get("name") or "",
                        c.get("lms_path") or "",
                        c.get("classroom_id") or "",
                        c.get("university_id") or "",
                        now,
                    ),
                )
        return len(courses)

    def list_discovered_courses(self, account_name: str) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT course_url, name, lms_path, classroom_id, university_id
                FROM discovered_courses
                WHERE account_name=?
                ORDER BY rowid
                """,
                (account_name,),
            ).fetchall()
        return [
            {
                "name": r["name"] or "",
                "url": r["course_url"] or "",
                "lms_path": r["lms_path"] or "",
                "classroom_id": r["classroom_id"] or "",
                "university_id": r["university_id"] or "",
            }
            for r in rows
        ]

    def get_course_video_stats(self, account_name: str) -> Dict[str, Dict[str, int]]:
        """按 classroom_id / course_url 统计视频进度"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT classroom_id, course_url, status, COUNT(*) AS cnt
                FROM videos
                WHERE account_name=?
                GROUP BY classroom_id, course_url, status
                """,
                (account_name,),
            ).fetchall()

        def _bump(bucket: Dict[str, Dict[str, int]], key: str, status: str, cnt: int):
            if not key:
                return
            bucket.setdefault(
                key, {"total": 0, "done": 0, "pending": 0, "failed": 0, "skipped": 0}
            )
            bucket[key]["total"] += cnt
            st = status or "pending"
            if st in bucket[key]:
                bucket[key][st] += cnt

        by_cid: Dict[str, Dict[str, int]] = {}
        by_url: Dict[str, Dict[str, int]] = {}
        for r in rows:
            cnt = int(r["cnt"] or 0)
            st = r["status"] or "pending"
            _bump(by_cid, (r["classroom_id"] or "").strip(), st, cnt)
            url_key = (r["course_url"] or "").split("?")[0].strip()
            _bump(by_url, url_key, st, cnt)
        return {"by_classroom_id": by_cid, "by_course_url": by_url}

    def mark_course_crawl(
        self,
        account_name: str,
        course_url: str,
        video_count: int,
        *,
        classroom_id: str = "",
        course_name: str = "",
        crawl_note: str = "",
    ) -> None:
        status = "empty" if video_count <= 0 else "crawled"
        now = int(time.time())
        note = crawl_note or ("无视频或无法解析章节" if video_count <= 0 else "")
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO course_crawl_meta
                (account_name, course_url, classroom_id, course_name,
                 crawl_status, video_count, crawl_note, crawled_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_name, course_url) DO UPDATE SET
                    classroom_id=excluded.classroom_id,
                    course_name=excluded.course_name,
                    crawl_status=excluded.crawl_status,
                    video_count=excluded.video_count,
                    crawl_note=excluded.crawl_note,
                    crawled_at=excluded.crawled_at
                """,
                (
                    account_name,
                    course_url.split("?")[0] if course_url else "",
                    classroom_id,
                    course_name,
                    status,
                    int(video_count),
                    note,
                    now,
                ),
            )

    def get_course_crawl_meta_map(self, account_name: str) -> Dict[str, Dict]:
        """course_url / classroom_id -> meta"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM course_crawl_meta
                WHERE account_name=?
                """,
                (account_name,),
            ).fetchall()
        by_url: Dict[str, Dict] = {}
        by_cid: Dict[str, Dict] = {}
        for r in rows:
            item = {
                "crawl_status": r["crawl_status"] or "pending",
                "video_count": int(r["video_count"] or 0),
                "crawl_note": r["crawl_note"] or "",
                "crawled_at": r["crawled_at"],
                "course_url": r["course_url"] or "",
            }
            url = (r["course_url"] or "").split("?")[0].strip()
            if url:
                by_url[url] = item
            cid = (r["classroom_id"] or "").strip()
            if cid:
                by_cid[cid] = item
        return {"by_url": by_url, "by_cid": by_cid}

    def save_account_profile(
        self,
        account_name: str,
        yuketang_name: Optional[str] = None,
        user_id: Optional[str] = None,
        logged_in: Optional[bool] = None,
    ) -> None:
        existing = self.get_account_profile(account_name)
        name = (
            yuketang_name
            if yuketang_name is not None
            else existing.get("yuketang_name", "")
        )
        uid = (
            user_id
            if user_id is not None
            else existing.get("user_id", "")
        )
        li = (
            logged_in
            if logged_in is not None
            else existing.get("logged_in", False)
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO account_profiles
                (account_name, yuketang_name, user_id, logged_in, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_name) DO UPDATE SET
                    yuketang_name=excluded.yuketang_name,
                    user_id=excluded.user_id,
                    logged_in=excluded.logged_in,
                    updated_at=excluded.updated_at
                """,
                (
                    account_name,
                    name or "",
                    uid or "",
                    1 if li else 0,
                    int(time.time()),
                ),
            )

    def get_account_profile(self, account_name: str) -> Dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM account_profiles WHERE account_name=?",
                (account_name,),
            ).fetchone()
        if not row:
            return {}
        return {
            "account_name": row["account_name"],
            "yuketang_name": row["yuketang_name"] or "",
            "user_id": row["user_id"] or "",
            "logged_in": bool(row["logged_in"]),
            "updated_at": row["updated_at"],
        }

    def mark_status(
        self, account_name: str, video_id: str, status: TaskStatus
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE videos SET status=?, updated_at=?
                WHERE account_name=? AND video_id=?
                """,
                (status.value, int(time.time()), account_name, video_id),
            )

    def mark_done(self, account_name: str, video_id: str) -> None:
        self.mark_status(account_name, video_id, TaskStatus.DONE)

    def mark_failed(self, account_name: str, video_id: str) -> None:
        self.mark_status(account_name, video_id, TaskStatus.FAILED)

    def log_progress(
        self,
        account_name: str,
        video_id: str,
        last_point: float,
        rate: float,
        completed: int,
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO progress_log
                (video_id, account_name, last_point, rate, completed, ts)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    video_id, account_name, last_point, rate,
                    completed, int(time.time()),
                ),
            )

    def reset_course(self, course_url: str, account_name: Optional[str] = None) -> int:
        with self._connect() as conn:
            if account_name:
                cur = conn.execute(
                    """
                    UPDATE videos SET status=?, updated_at=?
                    WHERE course_url=? AND account_name=?
                    """,
                    (TaskStatus.PENDING.value, int(time.time()), course_url, account_name),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE videos SET status=?, updated_at=?
                    WHERE course_url=?
                    """,
                    (TaskStatus.PENDING.value, int(time.time()), course_url),
                )
            return cur.rowcount

    def get_status_summary(self) -> List[Dict]:
        """按账号统计 pending/done/failed"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT account_name, status, COUNT(*) AS cnt
                FROM videos
                GROUP BY account_name, status
                ORDER BY account_name, status
                """
            ).fetchall()
        summary: Dict[str, Dict[str, int]] = {}
        for r in rows:
            name = r["account_name"]
            summary.setdefault(name, {"pending": 0, "done": 0, "failed": 0, "skipped": 0, "total": 0})
            summary[name][r["status"]] = r["cnt"]
            summary[name]["total"] += r["cnt"]
        result = []
        for name, stats in summary.items():
            result.append({"account_name": name, **stats})
        return result

    def get_course_summary(self) -> List[Tuple[str, str, int, int]]:
        """(account, course_url, total, done)"""
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT account_name, course_url,
                       COUNT(*) AS total,
                       SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done
                FROM videos
                GROUP BY account_name, course_url
                ORDER BY account_name, course_url
                """
            ).fetchall()
        return [(r["account_name"], r["course_url"], r["total"], r["done"] or 0) for r in rows]

    @staticmethod
    def _row_to_video(row: sqlite3.Row) -> Video:
        return Video(
            video_id=row["video_id"],
            video_url=row["video_url"],
            account_name=row["account_name"],
            course_url=row["course_url"] or "",
            classroom_id=row["classroom_id"] or "",
            lms_path=row["lms_path"] or "",
            title=row["title"] or "",
            status=TaskStatus(row["status"] or "pending"),
        )
