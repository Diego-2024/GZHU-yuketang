# -*- coding: utf-8 -*-
"""API 请求 / 响应模型"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class CourseIn(BaseModel):
    name: str = ""
    url: str
    lms_path: str = ""
    classroom_id: str = ""


class DiscoverCrawlRequest(BaseModel):
    courses: List[CourseIn]
    account: Optional[str] = None
    sync_all: bool = False


class RunRequest(BaseModel):
    account: Optional[str] = None


class LoginStartRequest(BaseModel):
    account: Optional[str] = None


class ResetRequest(BaseModel):
    course_url: str
    account: Optional[str] = None


class LoopSettings(BaseModel):
    heartbeat_count: int = 10
    heartbeat_interval: int = 5
    playback_rate: float = 1
    batch_sleep: float = 2
    target_rate: float = 0.95
    max_batches: int = 200


class AccountSettings(BaseModel):
    name: str
    profile: str
    port: Optional[int] = None


class AccountCreateRequest(BaseModel):
    name: Optional[str] = None
    profile: Optional[str] = None


class AccountDeleteRequest(BaseModel):
    name: str


class SettingsUpdate(BaseModel):
    base_url: Optional[str] = None
    home_url: Optional[str] = None
    accounts: Optional[List[AccountSettings]] = None
    loop: Optional[LoopSettings] = None
    base_port: Optional[int] = None
    listen_timeout: Optional[int] = None


class JobInfo(BaseModel):
    id: int
    action: str
    state: str
    message: str = ""
    account: Optional[str] = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
