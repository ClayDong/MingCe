from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    # ── 通用 ──
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    VERSION: str = "3.0.0"

    # ── 飞书 ──
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_CHAT_ID: str = ""
    ALERT_WEBHOOK_URL: str = ""  # 关键链路失败告警的飞书 webhook

    # ── LLM ──
    LLM_BASE_URL: str = "https://api.siliconflow.cn/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "Qwen/Qwen3-8B"
    # DeepSeek 官方密钥回退（从环境变量读取，作为 LLM_API_KEY 的回退）
    DEEPSEEK_API_KEY: str = ""

    # ── 数据存储 ──
    SQLITE_DB_PATH: str = "./data/market_daily.db"
    CACHE_DIR: str = "./data/cache"

    # ── 缓存TTL配置（秒） ──
    CACHE_TTL_MARKET: int = 1800      # 市场数据30分钟
    CACHE_TTL_MACRO: int = 43200      # 宏观数据12小时
    CACHE_TTL_NORTH: int = 1800       # 北向资金30分钟
    CACHE_TTL_ETF: int = 1800         # ETF数据30分钟
    CACHE_TTL_LEADING: int = 1800     # 龙头股30分钟
    CACHE_TTL_GLOBAL: int = 3600      # 全球宏观1小时
    CACHE_TTL_BSE: int = 1800         # 北证数据30分钟
    CACHE_TTL_US: int = 1800          # 美股数据30分钟（新增）
    CACHE_TTL_CRYPTO: int = 900       # 加密货币15分钟（新增）
    CACHE_TTL_FUTURES: int = 1800     # 期货数据30分钟（新增）
    CACHE_TTL_MONETARY: int = 43200   # 货币政策12小时（新增）

    # ── 告警阈值 ──
    ALERT_INDEX_THRESHOLD: float = 2.0
    ALERT_NORTH_FLOW_THRESHOLD: float = 50.0
    ALERT_LEADING_STOCK_THRESHOLD: float = 5.0
    ALERT_ETF_FLOW_THRESHOLD: float = 10.0
    ALERT_CRYPTO_THRESHOLD: float = 5.0         # 加密货币异动（新增）
    ALERT_FUTURES_THRESHOLD: float = 3.0        # 期货异动（新增）

    # ── 数据质量阈值 ──
    MIN_VOLUME_THRESHOLD: float = 1000.0
    MIN_INDEX_VALUE_THRESHOLD: float = 100.0

    # ── 目标指数配置 ──
    TARGET_INDICES: list[str] = ["上证指数", "深证成指", "创业板指", "科创50", "北证50"]
    TARGET_US_INDICES: list[str] = ["道琼斯", "标普500", "纳斯达克"]  # 新增

    # ── 龙头股筛选阈值 ──
    LEADING_MARKET_CAP_THRESHOLD: float = 1000.0
    LEADING_CHANGE_PCT_THRESHOLD: float = 3.0

    # ── 时区 ──
    TZ: str = "Asia/Shanghai"

    # ── 数据源开关 ──
    ENABLE_US_MARKET: bool = True       # 美股数据（新增）
    ENABLE_CRYPTO: bool = True          # 加密货币（新增）
    ENABLE_FUTURES: bool = True         # 国内期货（新增）
    ENABLE_MONETARY: bool = True        # 货币政策量化（新增）
    ENABLE_SHIPPING: bool = True        # 航运指数（新增）
    ENABLE_VIX: bool = True             # 恐慌指数（新增）

    @property
    def cache_path(self) -> Path:
        return Path(self.CACHE_DIR)

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
