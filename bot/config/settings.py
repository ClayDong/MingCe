"""配置模块 — 基于 pydantic-settings。

环境变量 (.env) → Settings 对象，支持类型校验和默认值。
"""

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
    ALERT_WEBHOOK_URL: str = ""

    # ── LLM ──
    LLM_BASE_URL: str = "https://api.siliconflow.cn/v1"
    LLM_API_KEY: str = ""
    LLM_MODEL: str = "Qwen/Qwen3-8B"
    DEEPSEEK_API_KEY: str = ""  # 旧版兼容，优先使用 LLM_API_KEY

    # ── API 认证 ──
    API_KEY: str = ""  # HTTP API 访问密钥，为空则不启用认证

    # ── 风控规则 ──
    RISK_SINGLE_STOCK_MAX_PCT: float = 30.0   # 单股持仓上限%
    RISK_DAILY_LOSS_WARNING_PCT: float = 3.0   # 日亏损预警%
    RISK_DAILY_LOSS_CIRCUIT_PCT: float = 5.0   # 日亏损熔断%
    RISK_FUND_VOLATILITY_MIN_POINTS: int = 20  # 波动率计算最少数据点数

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
    CACHE_TTL_US: int = 1800          # 美股数据30分钟
    CACHE_TTL_CRYPTO: int = 900       # 加密货币15分钟
    CACHE_TTL_FUTURES: int = 1800     # 期货数据30分钟
    CACHE_TTL_MONETARY: int = 43200   # 货币政策12小时

    # ── 告警阈值 ──
    ALERT_INDEX_THRESHOLD: float = 2.0
    ALERT_NORTH_FLOW_THRESHOLD: float = 50.0
    ALERT_LEADING_STOCK_THRESHOLD: float = 5.0
    ALERT_ETF_FLOW_THRESHOLD: float = 10.0
    ALERT_CRYPTO_THRESHOLD: float = 5.0
    ALERT_FUTURES_THRESHOLD: float = 3.0

    # ── 数据质量阈值 ──
    MIN_VOLUME_THRESHOLD: float = 1000.0
    MIN_INDEX_VALUE_THRESHOLD: float = 100.0
    # 数据质量门禁：低于此分数的数据模块自动降级到缓存/模板
    DATA_QUALITY_MIN_ACCEPTABLE_SCORE: float = 0.7

    # ── 目标指数配置 ──
    TARGET_INDICES: list[str] = ["上证指数", "深证成指", "创业板指", "科创50", "北证50"]
    TARGET_US_INDICES: list[str] = ["道琼斯", "标普500", "纳斯达克"]

    # ── 关注期货品种 ──
    TARGET_FUTURES: list[str] = ["铁矿石", "螺纹钢", "碳酸锂", "生猪", "沪铜", "沪铝", "焦煤", "纯碱", "玻璃"]

    # ── 龙头股筛选阈值 ──
    LEADING_MARKET_CAP_THRESHOLD: float = 1000.0
    LEADING_CHANGE_PCT_THRESHOLD: float = 3.0

    # ── 时区 ──
    TZ: str = "Asia/Shanghai"

    # ── 日志 ──
    LOG_DIR: str = "logs"

    # ── 数据源开关 ──
    ENABLE_US_MARKET: bool = True
    ENABLE_CRYPTO: bool = True
    ENABLE_FUTURES: bool = True
    ENABLE_MONETARY: bool = True
    ENABLE_SHIPPING: bool = True
    ENABLE_VIX: bool = True

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
