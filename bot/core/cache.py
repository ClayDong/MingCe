"""文件缓存模块 — 支持 TTL 过期的 JSON 文件缓存。

每个缓存的 key 按天分文件存储: {cache_dir}/{safe_key}_{date}.json
文件内容包含缓存时间和值，get() 时自动检查过期。
支持不同模块使用不同的TTL。
"""

import hashlib
import json
import time
from pathlib import Path
from datetime import date
from typing import Any, Optional

from loguru import logger

from config.settings import get_settings

settings = get_settings()


class FileCache:
    """文件缓存，支持 TTL 过期。

    Args:
        cache_dir: 缓存目录，默认使用 settings.CACHE_DIR
        ttl_seconds: 缓存过期时间（秒），默认 3600
    """

    def __init__(self, cache_dir: Optional[str] = None, ttl_seconds: Optional[int] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else Path(settings.CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds if ttl_seconds is not None else 3600

    def _cache_path(self, key: str) -> Path:
        safe_hash = hashlib.md5(key.encode("utf-8"), usedforsecurity=False).hexdigest()
        today = date.today().isoformat()
        return self.cache_dir / f"{safe_hash[:12]}_{today}.json"

    def get(self, key: str, ttl_seconds: Optional[int] = None) -> Any:
        """获取缓存值，过期或不存在返回 None。
        
        Args:
            key: 缓存键
            ttl_seconds: 自定义TTL（可选），优先使用此值
        """
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_time = data.get("_cached_at", 0)
            ttl = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
            if time.time() - cached_time > ttl:
                logger.debug(f"Cache expired: {key} (TTL: {ttl}s)")
                path.unlink(missing_ok=True)
                return None
            return data.get("value")
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Cache read failed for {key}: {e}")
            return None

    def set(self, key: str, value: Any) -> None:
        """设置缓存值。"""
        path = self._cache_path(key)
        try:
            data = {"value": value, "_cached_at": time.time()}
            path.write_text(json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8")
        except OSError as e:
            logger.warning(f"Cache write failed for {key}: {e}")

    def clear(self, key: Optional[str] = None) -> None:
        """清除缓存。key=None 清除所有缓存，否则清除指定 key 的今天缓存。"""
        if key:
            path = self._cache_path(key)
            path.unlink(missing_ok=True)
        else:
            for p in self.cache_dir.glob("*.json"):
                p.unlink(missing_ok=True)
            logger.info("All cache cleared")

    def clean_expired(self, max_age_hours: int = 48) -> int:
        """清理所有超过指定小时的缓存文件。

        Returns:
            清理的文件数量
        """
        cutoff = time.time() - max_age_hours * 3600
        cleared = 0
        for p in self.cache_dir.glob("*.json"):
            try:
                if p.stat().st_mtime < cutoff:
                    p.unlink()
                    cleared += 1
            except OSError:
                pass
        if cleared:
            logger.info(f"Cleaned {cleared} expired cache files")
        return cleared


def get_cache_for_module(module_name: str) -> FileCache:
    """根据模块名称获取带有特定TTL的缓存实例。"""
    ttl_map = {
        "market": settings.CACHE_TTL_MARKET,
        "macro": settings.CACHE_TTL_MACRO,
        "north_flow": settings.CACHE_TTL_NORTH,
        "etf": settings.CACHE_TTL_ETF,
        "leading": settings.CACHE_TTL_LEADING,
        "global_macro": settings.CACHE_TTL_GLOBAL,
        "bse": settings.CACHE_TTL_BSE,
    }
    ttl = ttl_map.get(module_name, 3600)
    return FileCache(ttl_seconds=ttl)
