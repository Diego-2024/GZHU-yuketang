# -*- coding: utf-8 -*-
"""数据模型"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class TaskStatus(str, Enum):
    PENDING = "pending"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class Account:
    name: str
    profile: str
    port: Optional[int] = None


@dataclass
class Course:
    name: str
    url: str
    lms_path: str = ""
    classroom_id: str = ""
    university_id: str = ""


@dataclass
class Video:
    video_id: str
    video_url: str
    account_name: str = ""
    course_url: str = ""
    classroom_id: str = ""
    lms_path: str = ""
    title: str = ""
    status: TaskStatus = TaskStatus.PENDING


@dataclass
class LoopConfig:
    heartbeat_count: int = 10
    heartbeat_interval: int = 5
    playback_rate: float = 1
    batch_sleep: float = 2
    target_rate: float = 0.95
    max_batches: int = 200
    start_sq: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "heartbeat_count": self.heartbeat_count,
            "heartbeat_interval": self.heartbeat_interval,
            "playback_rate": self.playback_rate,
            "batch_sleep": self.batch_sleep,
            "target_rate": self.target_rate,
            "max_batches": self.max_batches,
            "start_sq": self.start_sq,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "LoopConfig":
        data = data or {}
        return cls(
            heartbeat_count=int(data.get("heartbeat_count", 10)),
            heartbeat_interval=int(data.get("heartbeat_interval", 5)),
            playback_rate=float(data.get("playback_rate", 1)),
            batch_sleep=float(data.get("batch_sleep", 2)),
            target_rate=float(data.get("target_rate", 0.95)),
            max_batches=int(data.get("max_batches", 200)),
            start_sq=int(data.get("start_sq", 1)),
        )


@dataclass
class AppConfig:
    base_url: str
    home_url: str
    accounts: List[Account]
    loop: LoopConfig
    db_path: str
    profiles_root: str
    base_port: int = 9222
    listen_timeout: int = 60
    project_root: str = ""
