"""持仓与自选股管理模块。

通过 SQLite 存储用户的：
- 自选股（关注的股票）
- 持仓（已买入的股票、成本价、数量）
- 交易记录

飞书指令支持：
  @机器人 关注 比亚迪
  @机器人 取消关注 比亚迪
  @机器人 持仓 比亚迪 100股 280元
  @机器人 我的组合
  @机器人 信号 比亚迪
"""

import json
import sqlite3
from pathlib import Path
from datetime import datetime, date
from typing import Optional
from loguru import logger


# 数据存储路径
_PORTFOLIO_DB: Optional[sqlite3.Connection] = None
_DB_PATH = Path(__file__).parent.parent / "data" / "portfolio.db"


def _get_db() -> sqlite3.Connection:
    global _PORTFOLIO_DB
    if _PORTFOLIO_DB is None:
        _PORTFOLIO_DB = sqlite3.connect(str(_DB_PATH))
        _PORTFOLIO_DB.row_factory = sqlite3.Row
        _init_db()
    return _PORTFOLIO_DB


def _init_db():
    """初始化数据库表结构。"""
    db = _PORTFOLIO_DB
    db.execute("""
        CREATE TABLE IF NOT EXISTS watchlist (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            active INTEGER NOT NULL DEFAULT 1
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            name TEXT NOT NULL,
            shares REAL NOT NULL,
            cost_price REAL NOT NULL,
            added_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(symbol)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS trade_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            action TEXT NOT NULL,
            shares REAL NOT NULL,
            price REAL NOT NULL,
            reason TEXT,
            traded_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS strategy_scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            date TEXT NOT NULL,
            strategy_key TEXT NOT NULL,
            score REAL,
            signal INTEGER,
            UNIQUE(symbol, date, strategy_key)
        )
    """)
    db.commit()


# ═══ 自选股操作 ═══

def add_watchlist(symbol: str, name: str) -> dict:
    """添加自选股。"""
    db = _get_db()
    try:
        db.execute(
            "INSERT OR REPLACE INTO watchlist (symbol, name, active) VALUES (?, ?, 1)",
            (symbol, name),
        )
        db.commit()
        logger.info(f"Watchlist added: {name} ({symbol})")
        return {"success": True, "symbol": symbol, "name": name}
    except Exception as e:
        logger.error(f"Failed to add watchlist: {e}")
        return {"success": False, "error": str(e)}


def remove_watchlist(symbol: str) -> dict:
    """取消关注自选股。"""
    db = _get_db()
    try:
        db.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
        db.commit()
        logger.info(f"Watchlist removed: {symbol}")
        return {"success": True, "symbol": symbol}
    except Exception as e:
        logger.error(f"Failed to remove watchlist: {e}")
        return {"success": False, "error": str(e)}


def get_watchlist() -> list[dict]:
    """获取所有自选股。"""
    db = _get_db()
    rows = db.execute(
        "SELECT symbol, name, added_at FROM watchlist WHERE active = 1 ORDER BY added_at"
    ).fetchall()
    return [dict(r) for r in rows]


# ═══ 持仓操作 ═══

def add_holding(symbol: str, name: str, shares: float, cost_price: float) -> dict:
    """添加/更新持仓。"""
    db = _get_db()
    try:
        db.execute(
            """INSERT OR REPLACE INTO holdings (symbol, name, shares, cost_price)
               VALUES (?, ?, ?, ?)""",
            (symbol, name, shares, cost_price),
        )
        db.commit()
        logger.info(f"Holding added: {name} {shares}股 @ {cost_price}")
        return {"success": True, "symbol": symbol, "name": name}
    except Exception as e:
        logger.error(f"Failed to add holding: {e}")
        return {"success": False, "error": str(e)}


def remove_holding(symbol: str) -> dict:
    """移除持仓。"""
    db = _get_db()
    try:
        db.execute("DELETE FROM holdings WHERE symbol = ?", (symbol,))
        db.commit()
        return {"success": True, "symbol": symbol}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_holdings() -> list[dict]:
    """获取所有持仓。"""
    db = _get_db()
    rows = db.execute(
        "SELECT symbol, name, shares, cost_price, added_at FROM holdings ORDER BY added_at"
    ).fetchall()
    return [dict(r) for r in rows]


# ═══ 交易记录 ═══

def log_trade(symbol: str, action: str, shares: float, price: float, reason: str = ""):
    """记录交易。"""
    db = _get_db()
    db.execute(
        "INSERT INTO trade_log (symbol, action, shares, price, reason) VALUES (?, ?, ?, ?, ?)",
        (symbol, action, shares, price, reason),
    )
    db.commit()


def get_recent_trades(limit: int = 20) -> list[dict]:
    """获取最近交易记录。"""
    db = _get_db()
    rows = db.execute(
        "SELECT * FROM trade_log ORDER BY traded_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
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
        "分析": "stock_signals",
    }
    
    for cmd, action in commands.items():
        if text.startswith(cmd):
            args = text[len(cmd):].strip()
            return {"action": action, "args": args}
    
    return {"action": "unknown", "args": text}


# ═══ 股票代码映射 ═══

# 常见股票的中文名→代码映射
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


def resolve_symbol(text: str) -> tuple[str, str]:
    """解析股票名称/代码，返回 (代码, 名称)。"""
    text = text.strip().upper()
    
    # 检查是否为已注册的中文名
    for name, code in _STOCK_NAME_MAP.items():
        if name in text:
            return code, name
    
    # 检查是否为代码格式
    import re
    if re.match(r'^(SH|SZ|BJ|HK|US_)\d{5,6}$', text):
        # 反查名称
        for name, code in _STOCK_NAME_MAP.items():
            if code == text:
                return text, name
        return text, text
    
    # 尝试 A 股 6 位代码
    if re.match(r'^\d{6}$', text):
        prefix = "SH" if text.startswith("6") else "SZ"
        return f"{prefix}{text}", text
    
    return text, text


# 关闭数据库
def close():
    global _PORTFOLIO_DB
    if _PORTFOLIO_DB:
        _PORTFOLIO_DB.close()
        _PORTFOLIO_DB = None
