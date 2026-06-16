"""数据库模块 — SQLite 异步数据库操作。

使用 aiosqlite 提供异步数据库访问，支持 WAL 模式以提升并发性能。
采用单例模式管理数据库连接，使用 asyncio.Lock 确保线程安全。
"""

import asyncio
import aiosqlite
from pathlib import Path
from typing import Optional

from config.settings import get_settings

settings = get_settings()


class Database:
    """异步 SQLite 数据库封装。

    每个实例对应一个数据库文件。使用 WAL 模式和 busy_timeout
    来正确处理并发访问。
    """

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.SQLITE_DB_PATH
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[aiosqlite.Connection] = None

    async def init(self):
        """初始化数据库连接并创建表。"""
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._enable_wal()
        await self._create_tables()

    async def _enable_wal(self):
        """启用 WAL 模式并设置超时。"""
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA busy_timeout=5000")
        await self._conn.execute("PRAGMA synchronous=NORMAL")

    async def close(self):
        """关闭数据库连接。"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _create_tables(self):
        """创建所有必要的表并建立索引。"""
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS daily_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_date TEXT NOT NULL,
                version TEXT NOT NULL,
                content TEXT NOT NULL,
                modules TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'generating',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(report_date, version)
            );

            CREATE TABLE IF NOT EXISTS data_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cache_key TEXT NOT NULL UNIQUE,
                cache_date TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS alert_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                alert_date TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                alert_content TEXT NOT NULL,
                is_sent INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 信号生命周期追踪表
            CREATE TABLE IF NOT EXISTS signal_lifecycle (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_id TEXT NOT NULL,             -- 信号唯一ID（uuid）
                symbol TEXT NOT NULL,                -- 股票代码
                signal_date TEXT NOT NULL,           -- 信号产生日期
                direction TEXT NOT NULL,             -- BUY / SELL / HOLD
                confidence REAL NOT NULL,            -- 置信度 0-1
                entry_price REAL,                    -- 信号产生时价格
                strategy_source TEXT,                -- 信号来源（QLib/LLM/融合）
                market_regime TEXT,                  -- 市场状态
                status TEXT NOT NULL DEFAULT 'active', -- active / expired / hit_target / hit_stop / closed
                target_price REAL,                   -- 目标价
                stop_loss REAL,                      -- 止损价
                exit_price REAL,                     -- 退出价
                exit_date TEXT,                      -- 退出日期
                holding_days INTEGER DEFAULT 0,      -- 持有天数
                return_pct REAL,                     -- 实际收益率%
                hit_target INTEGER DEFAULT 0,        -- 是否命中目标 1/0
                hit_stop INTEGER DEFAULT 0,          -- 是否触发止损 1/0
                evaluated_at TIMESTAMP,              -- 评估时间
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            -- 任务状态持久化表
            CREATE TABLE IF NOT EXISTS task_store (
                task_id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                result TEXT,
                error TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_reports_date ON daily_reports(report_date, version);
            CREATE INDEX IF NOT EXISTS idx_alert_logs_date ON alert_logs(alert_date);
            CREATE INDEX IF NOT EXISTS idx_signal_lifecycle_symbol ON signal_lifecycle(symbol, signal_date);
            CREATE INDEX IF NOT EXISTS idx_signal_lifecycle_status ON signal_lifecycle(status, signal_date);
            CREATE INDEX IF NOT EXISTS idx_signal_lifecycle_date ON signal_lifecycle(signal_date);
        """)
        await self._conn.commit()

    async def execute(self, sql: str, params: tuple = ()):
        """执行 SQL 并提交。"""
        cursor = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cursor

    async def executemany(self, sql: str, params_list: list):
        """批量执行 SQL。"""
        cursor = await self._conn.executemany(sql, params_list)
        await self._conn.commit()
        return cursor

    async def fetchone(self, sql: str, params: tuple = ()):
        """查询单条记录。"""
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchone()

    async def fetchall(self, sql: str, params: tuple = ()):
        """查询多条记录。"""
        cursor = await self._conn.execute(sql, params)
        return await cursor.fetchall()


_db: Optional[Database] = None
_db_lock = asyncio.Lock()


async def get_db() -> Database:
    """获取数据库单例（线程安全）。"""
    global _db
    if _db is None:
        async with _db_lock:
            # 双重检查锁定
            if _db is None:
                _db = Database()
                await _db.init()
    return _db
