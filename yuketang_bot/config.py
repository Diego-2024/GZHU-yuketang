# -*- coding: utf-8 -*-
"""加载 / 校验 config.yaml"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional, Union

import yaml

from .models import Account, AppConfig, LoopConfig
from .paths import get_data_dir


DEFAULT_CONFIG_NAME = "config.yaml"
_last_config_path: Optional[Path] = None


def get_config_path() -> Optional[Path]:
    return _last_config_path


def _project_root() -> Path:
    """相对路径解析根目录：打包后用可写数据目录"""
    if getattr(sys, "frozen", False):
        return get_data_dir()
    return Path(__file__).resolve().parent.parent


def _resolve_path(raw: str, project_root: Path) -> str:
    p = Path(raw)
    if not p.is_absolute():
        p = project_root / p
    return str(p.resolve())


def resolve_config_path(path: Optional[Union[str, Path]] = None) -> Path:
    project_root = _project_root()
    if path is None:
        cwd_cfg = Path.cwd() / DEFAULT_CONFIG_NAME
        root_cfg = project_root / DEFAULT_CONFIG_NAME
        if cwd_cfg.exists():
            return cwd_cfg.resolve()
        if root_cfg.exists():
            return root_cfg.resolve()
        raise FileNotFoundError(
            "未找到 config.yaml，请复制 config.example.yaml 为 config.yaml"
        )
    cfg_path = Path(path)
    if not cfg_path.is_absolute():
        cfg_path = (Path.cwd() / cfg_path).resolve()
    if not cfg_path.exists():
        raise FileNotFoundError("配置文件不存在: %s" % cfg_path)
    return cfg_path


def load_config(path: Optional[Union[str, Path]] = None) -> AppConfig:
    """
    加载配置文件。
    默认查找顺序：
      1. 显式 path
      2. 当前工作目录 config.yaml
      3. 可写数据目录 / 项目根目录 config.yaml
    """
    global _last_config_path
    project_root = _project_root()
    cfg_path = resolve_config_path(path)
    _last_config_path = cfg_path

    with open(cfg_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    return _validate_and_build(raw, project_root)


def load_raw_config(path: Optional[Union[str, Path]] = None) -> Dict[str, Any]:
    cfg_path = resolve_config_path(path)
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def save_raw_config(
    data: Dict[str, Any], path: Optional[Union[str, Path]] = None
) -> Path:
    global _last_config_path
    if path is not None:
        cfg_path = Path(path)
        if not cfg_path.is_absolute():
            cfg_path = (Path.cwd() / cfg_path).resolve()
    elif _last_config_path is not None:
        cfg_path = _last_config_path
    else:
        cfg_path = resolve_config_path(None)
    with open(cfg_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
    _last_config_path = cfg_path
    return cfg_path


def suggest_next_account(cfg: AppConfig) -> tuple[str, str]:
    """自动生成下一个本地账号名与 profile 目录名"""
    names = {a.name for a in cfg.accounts}
    profiles = {a.profile for a in cfg.accounts}

    n = 1
    while True:
        name = "账号%d" % n
        if name not in names:
            break
        n += 1

    m = 1
    while True:
        profile = "account_%d" % m
        if profile not in profiles:
            break
        m += 1

    return name, profile


def _validate_and_build(raw: Dict[str, Any], project_root: Path) -> AppConfig:
    base_url = (raw.get("base_url") or "https://www.yuketang.cn").rstrip("/")
    home_url = raw.get("home_url") or (base_url + "/v2/web/index")

    accounts_raw = raw.get("accounts") or []
    if not accounts_raw:
        raise ValueError("config.yaml 中 accounts 不能为空")

    accounts = []
    for i, item in enumerate(accounts_raw):
        if not isinstance(item, dict):
            raise ValueError("accounts[%d] 必须是字典" % i)
        name = (item.get("name") or "").strip()
        profile = (item.get("profile") or "").strip()
        if not name or not profile:
            raise ValueError("accounts[%d] 需要 name 和 profile" % i)
        port = item.get("port")
        accounts.append(Account(name=name, profile=profile, port=port))

    loop = LoopConfig.from_dict(raw.get("loop"))

    db_path = _resolve_path(raw.get("db_path") or "./data/yuketang.db", project_root)
    profiles_root = _resolve_path(
        raw.get("profiles_root") or "./profiles", project_root
    )

    return AppConfig(
        base_url=base_url,
        home_url=home_url,
        accounts=accounts,
        loop=loop,
        db_path=db_path,
        profiles_root=profiles_root,
        base_port=int(raw.get("base_port", 9222)),
        listen_timeout=int(raw.get("listen_timeout", 60)),
        project_root=str(project_root),
    )
