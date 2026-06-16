import time
import json
import re
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger
from qlib_vnpy_platform.config import get_config, CACHE_DIR


class NewsFetcher:
    def __init__(self):
        self.config = get_config()["news"]
        self.cache_dir = CACHE_DIR / "news"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._akshare = None
        self._akshare_available = None
        logger.info("NewsFetcher initialized")

    @property
    def akshare(self):
        if self._akshare_available is False:
            return None
        if self._akshare is None:
            try:
                import akshare as ak
                self._akshare = ak
                self._akshare_available = True
                logger.info("akshare loaded successfully")
            except ImportError:
                self._akshare_available = False
                logger.warning("akshare is not installed. News fetching will be disabled. "
                               "Install with: pip install akshare")
                return None
        return self._akshare

    def fetch_stock_news(self, symbol: str, max_news: int = None) -> list:
        if max_news is None:
            max_news = self.config.get("max_news", 10)

        cache_file = self.cache_dir / f"news_{symbol}.json"
        if cache_file.exists():
            file_age = time.time() - cache_file.stat().st_mtime
            cache_seconds = self.config.get("cache_hours", 2) * 3600
            if file_age < cache_seconds:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                if cached:
                    logger.debug(f"Loading cached news for {symbol}")
                    return cached[:max_news]

        news_list = []

        try:
            news_list.extend(self._fetch_eastmoney_news(symbol, max_news))
        except Exception as e:
            logger.warning(f"EastMoney news fetch failed for {symbol}: {e}")

        if len(news_list) < max_news:
            try:
                news_list.extend(self._fetch_stock_notice(symbol, max_news - len(news_list)))
            except Exception as e:
                logger.warning(f"Stock notice fetch failed for {symbol}: {e}")

        news_list = news_list[:max_news]

        if news_list:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(news_list, f, ensure_ascii=False, indent=2)

        logger.info(f"Fetched {len(news_list)} news items for {symbol}")
        return news_list

    def _fetch_eastmoney_news(self, symbol: str, max_news: int) -> list:
        ak = self.akshare
        if ak is None:
            return []
        try:
            code = symbol
            if symbol.startswith("SZ") or symbol.startswith("SH"):
                code = symbol[2:]

            df = ak.stock_news_em(symbol=code)
            if df is None or df.empty:
                return []

            news_list = []
            for _, row in df.head(max_news).iterrows():
                news_item = {
                    "title": str(row.get("新闻标题", "")),
                    "content": str(row.get("新闻内容", "")),
                    "source": str(row.get("文章来源", "东方财富")),
                    "publish_time": str(row.get("发布时间", "")),
                    "url": str(row.get("新闻链接", "")),
                    "type": "news",
                }
                if news_item["title"]:
                    news_list.append(news_item)

            return news_list
        except Exception as e:
            logger.error(f"EastMoney news error: {e}")
            return []

    def _fetch_stock_notice(self, symbol: str, max_news: int) -> list:
        ak = self.akshare
        if ak is None:
            return []
        try:
            code = symbol
            if symbol.startswith("SZ") or symbol.startswith("SH"):
                code = symbol[2:]

            df = ak.stock_notice_report(symbol=code)
            if df is None or df.empty:
                return []

            news_list = []
            for _, row in df.head(max_news).iterrows():
                news_item = {
                    "title": str(row.get("公告标题", row.get("标题", ""))),
                    "content": str(row.get("公告内容", row.get("内容", ""))),
                    "source": "公告",
                    "publish_time": str(row.get("公告日期", row.get("日期", ""))),
                    "url": "",
                    "type": "notice",
                }
                if news_item["title"]:
                    news_list.append(news_item)

            return news_list
        except Exception as e:
            logger.error(f"Stock notice error: {e}")
            return []

    def fetch_market_news(self, max_news: int = 20) -> list:
        ak = self.akshare
        if ak is None:
            return []
        try:
            df = ak.stock_news_em(symbol="000001")
            if df is None or df.empty:
                return []

            news_list = []
            for _, row in df.head(max_news).iterrows():
                news_item = {
                    "title": str(row.get("新闻标题", "")),
                    "content": str(row.get("新闻内容", "")),
                    "source": str(row.get("文章来源", "东方财富")),
                    "publish_time": str(row.get("发布时间", "")),
                    "type": "market_news",
                }
                if news_item["title"]:
                    news_list.append(news_item)

            return news_list
        except Exception as e:
            logger.error(f"Market news error: {e}")
            return []

    def format_news_for_llm(self, news_list: list, max_items: int = 5) -> str:
        if not news_list:
            return "暂无相关资讯"

        formatted = []
        for i, news in enumerate(news_list[:max_items], 1):
            title = news.get("title", "无标题")
            source = news.get("source", "")
            pub_time = news.get("publish_time", "")
            content = news.get("content", "")
            summary = content[:200] if len(content) > 200 else content
            formatted.append(f"{i}. [{source} {pub_time}] {title}\n   {summary}")

        return "\n".join(formatted)
