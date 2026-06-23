"""持仓与自选股管理模块。

通过 aiosqlite 提供异步安全的数据库操作：
- 自选股（关注的股票）
- 持仓（已买入的股票、成本价、数量）
- 交易记录
- 策略评分存储

使用 WAL 模式 + asyncio.Lock 确保并发安全。
"""

import asyncio
import re
import aiosqlite
from pathlib import Path
from typing import Optional
from loguru import logger


_DB_PATH = Path(__file__).parent.parent / "data" / "portfolio.db"
_db_conn: Optional[aiosqlite.Connection] = None
_db_lock = asyncio.Lock()


async def _get_db() -> aiosqlite.Connection:
    """获取数据库连接（线程安全，异步兼容 FastAPI 多协程）。"""
    global _db_conn
    if _db_conn is None:
        async with _db_lock:
            if _db_conn is None:
                Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)
                _db_conn = await aiosqlite.connect(str(_DB_PATH))
                _db_conn.row_factory = aiosqlite.Row
                await _db_conn.execute("PRAGMA journal_mode=WAL")
                await _db_conn.execute("PRAGMA busy_timeout=5000")
                await _db_conn.execute("PRAGMA synchronous=NORMAL")
                await _init_db()
    return _db_conn


async def _init_db():
    """初始化数据库表结构。"""
    db = _db_conn
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            shares REAL NOT NULL,
            cost_price REAL NOT NULL,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(symbol)
        );
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            shares REAL NOT NULL,
            price REAL NOT NULL,
            reason TEXT,
            traded_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS strategy_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            strategy_key TEXT NOT NULL,
            score REAL,
            signal INTEGER,
            UNIQUE(symbol, date, strategy_key)
        );
        CREATE INDEX IF NOT EXISTS idx_watchlist_active ON watchlist(active);
        CREATE INDEX IF NOT EXISTS idx_holdings_symbol ON holdings(symbol);
        CREATE INDEX IF NOT EXISTS idx_trade_log_symbol ON trade_log(symbol);
    """)
    await db.commit()


# ═══ 自选股操作 ═══

async def add_watchlist(symbol: str, name: str) -> dict:
    """添加自选股。"""
    db = await _get_db()
    try:
        await db.execute(
            "INSERT OR REPLACE INTO watchlist (symbol, name, active) VALUES (?, ?, 1)",
            (symbol, name),
        )
        await db.commit()
        logger.info(f"Watchlist added: {name} ({symbol})")
        return {"success": True, "symbol": symbol, "name": name}
    except Exception as e:
        logger.error(f"Failed to add watchlist: {e}")
        return {"success": False, "error": str(e)}


async def remove_watchlist(symbol: str) -> dict:
    """取消关注自选股。"""
    db = await _get_db()
    try:
        await db.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
        await db.commit()
        logger.info(f"Watchlist removed: {symbol}")
        return {"success": True, "symbol": symbol}
    except Exception as e:
        logger.error(f"Failed to remove watchlist: {e}")
        return {"success": False, "error": str(e)}


async def get_watchlist() -> list[dict]:
    """获取所有自选股。"""
    db = await _get_db()
    rows = await db.execute_fetchall(
        "SELECT symbol, name, added_at FROM watchlist WHERE active = 1 ORDER BY added_at"
    )
    return [dict(r) for r in rows]


# ═══ 持仓操作 ═══

async def add_holding(symbol: str, name: str, shares: float, cost_price: float) -> dict:
    """添加/更新持仓。"""
    db = await _get_db()
    try:
        await db.execute(
            """INSERT OR REPLACE INTO holdings (symbol, name, shares, cost_price)
               VALUES (?, ?, ?, ?)""",
            (symbol, name, shares, cost_price),
        )
        await db.commit()
        logger.info(f"Holding added: {name} {shares}股 @ {cost_price}")
        return {"success": True, "symbol": symbol, "name": name}
    except Exception as e:
        logger.error(f"Failed to add holding: {e}")
        return {"success": False, "error": str(e)}


async def remove_holding(symbol: str) -> dict:
    """移除持仓。"""
    db = await _get_db()
    try:
        await db.execute("DELETE FROM holdings WHERE symbol = ?", (symbol,))
        await db.commit()
        return {"success": True, "symbol": symbol}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_holdings() -> list[dict]:
    """获取所有持仓。"""
    db = await _get_db()
    rows = await db.execute_fetchall(
        "SELECT symbol, name, shares, cost_price, added_at FROM holdings ORDER BY added_at"
    )
    return [dict(r) for r in rows]


# ═══ 交易记录 ═══

async def log_trade(symbol: str, action: str, shares: float, price: float, reason: str = ""):
    """记录交易。"""
    db = await _get_db()
    await db.execute(
        "INSERT INTO trade_log (symbol, action, shares, price, reason) VALUES (?, ?, ?, ?, ?)",
        (symbol, action, shares, price, reason),
    )
    await db.commit()


async def get_recent_trades(limit: int = 20) -> list[dict]:
    """获取最近交易记录。"""
    db = await _get_db()
    rows = await db.execute_fetchall(
        "SELECT * FROM trade_log ORDER BY traded_at DESC LIMIT ?",
        (limit,),
    )
    return [dict(r) for r in rows]


# ═══ 解析飞书指令 ═══

def parse_feishu_command(text: str) -> dict:
    """解析飞书消息中的指令。
    
    支持：
    - "关注 比亚迪" / "关注 SZ002594"
    - "取消关注 比亚迪"
    - "持仓 比亚迪 100股 280元"
    - "移除持仓 比亚迪"
    - "我的组合" / "组合"
    - "信号 比亚迪" / "分析 比亚迪"
    """
    text = text.strip()
    
    commands = {
        "关注": "add_watchlist",
        "取消关注": "remove_watchlist",
        "持仓": "add_holding",
        "移除持仓": "remove_holding",
        "组合": "portfolio_summary",
        "我的组合": "portfolio_summary",
        "信号": "stock_signals",
        "深度分析": "wisdom_analysis",
        "分析": "stock_signals",
    }
    
    for cmd, action in commands.items():
        if text.startswith(cmd):
            args = text[len(cmd):].strip()
            return {"action": action, "args": args}
    
    return {"action": "unknown", "args": text}


# ═══ 股票代码映射 ═══

_STOCK_NAME_MAP = {
    "比亚迪": "SZ002594",
    "茅台": "SH600519",
    "宁德时代": "SZ300750",
    "腾讯": "HK00700",
    "阿里巴巴": "HK09988",
    "特斯拉": "US_TSLA",
    "苹果": "US_AAPL",
    "英伟达": "US_NVDA",
}

# 模糊匹配辅助：常见股票简称映射
_STOCK_ALIAS_MAP = {
    "宁德": "SZ300750",
    "宁王": "SZ300750",
    "比王": "SZ002594",
    "BYD": "SZ002594",
    "TSLA": "US_TSLA",
    "AAPL": "US_AAPL",
    "NVDA": "US_NVDA",
    "英伟达": "US_NVDA",
    "特斯拉": "US_TSLA",
    "苹果": "US_AAPL",
    "阿里": "HK09988",
    "TX": "HK00700",
}


def resolve_symbol(text: str) -> tuple[str, str]:
    """解析股票名称/代码，返回 (代码, 名称)。
    
    支持：
    - 精确代码：SH600519, SZ002594
    - A 股 6 位代码：600519, 002594
    - 中文全称：比亚迪, 宁德时代
    - 中文简称/别名：宁德, BYD, TSLA
    """
    text = text.strip()

    # 1. 检查别名/简称映射（不区分大小写）
    text_upper = text.upper()
    for alias, code in _STOCK_ALIAS_MAP.items():
        if text == alias or text_upper == alias.upper():
            for name, mapped_code in _STOCK_NAME_MAP.items():
                if mapped_code == code:
                    return code, name
            return code, text

    # 2. 检查已注册的中文名
    text_upper = text.upper()
    for name, code in _STOCK_NAME_MAP.items():
        if name in text:
            return code, name

    # 3. 检查是否为代码格式
    if re.match(r'^(SH|SZ|BJ|HK|US_)\d{5,6}$', text_upper):
        for name, code in _STOCK_NAME_MAP.items():
            if code == text_upper:
                return text_upper, name
        return text_upper, text_upper

    # 4. 尝试 A 股 6 位代码
    if re.match(r'^\d{6}$', text):
        prefix = "SH" if text.startswith("6") else "SZ"
        code = f"{prefix}{text}"
        for name, mapped_code in _STOCK_NAME_MAP.items():
            if mapped_code == code:
                return code, name
        return code, text

    return text, text


async def close():
    """关闭数据库连接。"""
    global _db_conn
    if _db_conn:
        await _db_conn.close()
        _db_conn = None
