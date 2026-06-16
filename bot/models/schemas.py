"""数据模型 — Pydantic 模型定义。

定义了日报生成所需的全部数据结构，新增：
- USMarketData / USStockData / CryptoData / FuturesData / MonetaryData / IntradayComparison
- 扩展 GlobalMacroData / NorthFlowData / ETFData
"""

from pydantic import BaseModel
from typing import Optional


class IndexData(BaseModel):
    """指数行情数据。"""
    name: str
    value: float
    change_pct: float
    volume: Optional[str] = None


class MarketOverview(BaseModel):
    """A 股市场概况。"""
    indices: list[IndexData] = []
    up_count: int = 0
    down_count: int = 0
    flat_count: int = 0
    total_volume: str = ""
    top_sectors: list[dict] = []
    bottom_sectors: list[dict] = []
    fund_flow: str = ""


class MacroData(BaseModel):
    """宏观经济数据。"""
    cpi: Optional[str] = None
    ppi: Optional[str] = None
    pmi: Optional[str] = None
    m2: Optional[str] = None           # M2 同比增速
    m2_yoy: Optional[str] = None       # M2 同比历史对比
    social_finance: Optional[str] = None  # 社融规模
    social_finance_yoy: Optional[str] = None  # 社融同比
    credit_impulse: Optional[str] = None    # 信贷脉冲
    lpr_1y: Optional[str] = None
    lpr_5y: Optional[str] = None
    rrr: Optional[str] = None           # 存款准备金率
    shibor_overnight: Optional[str] = None
    shibor_7d: Optional[str] = None
    shibor_1y: Optional[str] = None     # 1年期 shibor
    highlights: list[str] = []


class NorthFlowData(BaseModel):
    """北向资金数据（扩展：行业流向+个股）。"""
    net_flow: Optional[float] = None
    sh_flow: Optional[float] = None
    sz_flow: Optional[float] = None
    top_industries_buy: list[dict] = []   # 买入最多的行业
    top_industries_sell: list[dict] = []  # 卖出最多的行业
    top_stocks_buy: list[dict] = []       # 买入最多的个股


class ETFData(BaseModel):
    """ETF 行情数据（扩展：资金流+持仓穿透）。"""
    broad_based: list[dict] = []
    industry: list[dict] = []
    highlights: list[str] = []
    top_buy_etf: list[dict] = []      # 资金流入最多的 ETF
    top_sell_etf: list[dict] = []     # 资金流出最多的 ETF


class LeadingStockData(BaseModel):
    """龙头股票动向数据。"""
    headlines: list[dict] = []
    major_events: list[dict] = []
    announcements: list[dict] = []


class USStockData(BaseModel):
    """美股个股行情。"""
    name: str
    value: float
    change_pct: float
    volume: Optional[str] = None


class USMarketData(BaseModel):
    """美股市场数据（新增）。"""
    indices: list[IndexData] = []      # 道指/纳指/标普
    top_stocks: list[USStockData] = [] # 热门个股
    highlights: list[str] = []


class CryptoData(BaseModel):
    """加密货币数据（新增：BTC、ETH 等）。"""
    btc_price: Optional[str] = None
    btc_change: Optional[float] = None   # 24h 涨跌幅
    eth_price: Optional[str] = None
    eth_change: Optional[float] = None
    btc_dominance: Optional[str] = None  # BTC 市占率
    highlights: list[str] = []


class FuturesData(BaseModel):
    """国内商品期货数据（新增）。"""
    items: list[dict] = []               # [{"name": "铁矿石", "price": "...", "change_pct": ...}]
    highlights: list[str] = []


class MonetaryData(BaseModel):
    """货币政策量化数据（新增）。"""
    m2_growth: Optional[str] = None          # M2 增速
    social_finance_growth: Optional[str] = None  # 社融增速
    credit_impulse: Optional[str] = None     # 信贷脉冲
    rrr_current: Optional[str] = None        # 存款准备金率
    mlf_rate: Optional[str] = None           # 中期借贷便利利率
    highlights: list[str] = []


class GlobalMacroData(BaseModel):
    """全球宏观变量数据（扩展：美日欧+VIX+航运+汇率篮子）。"""
    brent_oil: Optional[str] = None          # 布伦特原油
    wti_oil: Optional[str] = None            # WTI 原油（新增）
    gold: Optional[str] = None               # 黄金
    silver: Optional[str] = None             # 白银（新增）
    usd_index: Optional[str] = None          # 美元指数
    us_10y_bond: Optional[str] = None        # 美国 10Y 国债
    us_2y_bond: Optional[str] = None         # 美国 2Y 国债（新增，利差看衰退）
    usd_cny: Optional[str] = None            # 美元/人民币
    usd_jpy: Optional[str] = None            # 美元/日元（新增）
    euro_usd: Optional[str] = None           # 欧元/美元（新增）
    vix: Optional[str] = None                # 恐慌指数 VIX（新增）
    bdi: Optional[str] = None                # 波罗的海干散货指数（新增）
    nikkei: Optional[str] = None             # 日经 225（新增）
    sp500: Optional[str] = None              # 标普 500（新增）
    highlights: list[str] = []


class AlertItem(BaseModel):
    """告警项。"""
    alert_type: str
    title: str
    content: str
    level: str = "info"


class BSEIndexData(BaseModel):
    """北证指数行情数据。"""
    name: str
    value: float
    change_pct: float
    volume: Optional[str] = None


class BSELeadingStockData(BaseModel):
    """北证龙头股票动向数据。"""
    headlines: list[dict] = []
    major_events: list[dict] = []
    announcements: list[dict] = []


class BSEData(BaseModel):
    """北证市场数据。"""
    indices: list[BSEIndexData] = []
    leading: BSELeadingStockData = BSELeadingStockData()
    highlights: list[str] = []


class IntradayComparison(BaseModel):
    """跨市场日内比较（新增：早盘前/午间/收盘对比）。"""
    a_shanghai: Optional[str] = None
    a_shenzhen: Optional[str] = None
    us_sp500: Optional[str] = None
    us_nasdaq: Optional[str] = None
    hk_hsi: Optional[str] = None
    btc: Optional[str] = None
    summary: str = ""


class DailyReportData(BaseModel):
    """完整日报数据（五维框架重组）。"""
    report_date: str = ""
    version: str = "close"
    is_trading_day: bool = True

    # 维度一：金 — 黄金 + 白银
    # 维度二：油 — 布伦特 + WTI + 国内期货
    # 维度三：汇 — 美元指数 + 主要汇率
    # 维度四：债 — 美债 + 中信/国债期货相关
    # 维度五：G — 衍生品/加密货币/VIX/北向资金

    market: MarketOverview = MarketOverview()
    macro: MacroData = MacroData()
    monetary: MonetaryData = MonetaryData()         # 新增
    north_flow: NorthFlowData = NorthFlowData()
    etf: ETFData = ETFData()
    leading: LeadingStockData = LeadingStockData()
    us_market: USMarketData = USMarketData()         # 新增
    crypto: CryptoData = CryptoData()                # 新增
    futures: FuturesData = FuturesData()              # 新增
    global_macro: GlobalMacroData = GlobalMacroData()
    bse: BSEData = BSEData()
    comparison: IntradayComparison = IntradayComparison()  # 新增
    alerts: list[AlertItem] = []
    master_commentary: str = ""
