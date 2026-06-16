"""服务模块导出（v2.0 五维框架）"""

from services.data_fetcher import (
    get_market_overview,
    get_macro_data,
    get_north_flow,
    get_etf_data,
    get_leading_stocks,
    get_global_macro,
    get_bse_data,
    detect_alerts,
    get_us_market,
    get_crypto_data,
    get_futures_data,
    get_monetary_data,
    get_intraday_comparison,
    _extend_alerts,
)
from services.feishu_service import (
    send_card_message,
    send_text_message,
    send_error_notification,
    build_detail_card,
    build_alert_card,
)
from services.llm_service import (
    generate_commentary,
    generate_detailed_commentary,
    generate_five_dimension_analysis,
)
from services.report_generator import (
    generate_daily_report,
    push_daily_report,
)
from services.fund_monitor import (
    FundMonitor,
    FundMonitorConfig,
    FundData,
    MonitorAlert,
    build_fund_monitor_card,
)

__all__ = [
    # 数据获取
    "get_market_overview",
    "get_macro_data",
    "get_north_flow",
    "get_etf_data",
    "get_leading_stocks",
    "get_global_macro",
    "get_bse_data",
    "detect_alerts",
    "get_us_market",
    "get_crypto_data",
    "get_futures_data",
    "get_monetary_data",
    "get_intraday_comparison",
    "_extend_alerts",
    # 飞书服务
    "send_card_message",
    "send_text_message",
    "send_error_notification",
    "build_detail_card",
    "build_alert_card",
    # LLM服务
    "generate_commentary",
    "generate_detailed_commentary",
    "generate_five_dimension_analysis",
    # 报表生成
    "generate_daily_report",
    "push_daily_report",
    # 基金监控
    "FundMonitor",
    "FundMonitorConfig",
    "FundData",
    "MonitorAlert",
    "build_fund_monitor_card",
]
