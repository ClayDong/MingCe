import os
import time
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps
from loguru import logger
from qlib_vnpy_platform.config import get_config, CACHE_DIR


def retry(max_attempts=3, delay=1.0, backoff=2.0):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            current_delay = delay
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    if attempts >= max_attempts:
                        logger.error(f"{func.__name__} failed after {max_attempts} attempts: {e}")
                        raise
                    logger.warning(f"{func.__name__} attempt {attempts} failed, retrying in {current_delay:.1f}s: {e}")
                    time.sleep(current_delay)
                    current_delay *= backoff
        return wrapper
    return decorator


class DataBridge:
    EXCHANGE_MAP = {
        "SZ": "SZ",
        "SH": "SH",
        "0": "SZ",
        "3": "SZ",
        "6": "SH",
        "8": "BJ",
        "4": "BJ",
    }

    def __init__(self):
        self.config = get_config()["data"]
        self.cache_dir = CACHE_DIR / "stock_data"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self._akshare = None
        self._data_source_healthy = True
        self._last_health_check = None
        self._tushare_available = False
        logger.info(f"DataBridge initialized, cache_dir={self.cache_dir}")

    @property
    def akshare(self):
        if self._akshare is None:
            import akshare as ak
            self._akshare = ak
        return self._akshare

    def check_data_source_health(self) -> dict:
        result = {
            "healthy": False,
            "latency_ms": -1,
            "timestamp": datetime.now().isoformat(),
            "primary_source": self.config.get("primary_source", "akshare"),
            "fallback_source": self.config.get("fallback_source", "tushare"),
            "tushare_available": self._tushare_available,
        }

        try:
            start_time = time.time()
            df = self.akshare.stock_zh_a_spot_em()
            latency = (time.time() - start_time) * 1000
            result["latency_ms"] = round(latency, 2)
            result["healthy"] = df is not None and not df.empty
            self._data_source_healthy = result["healthy"]
        except Exception as e:
            logger.warning(f"Data source health check failed: {e}")
            self._data_source_healthy = False

        self._last_health_check = result
        return result

    def akshare_to_qlib_symbol(self, akshare_code: str) -> str:
        if akshare_code.startswith("SZ") or akshare_code.startswith("SH"):
            return akshare_code
        first_char = akshare_code[0]
        exchange = self.EXCHANGE_MAP.get(first_char, "SZ")
        return f"{exchange}{akshare_code}"

    def qlib_to_akshare_symbol(self, qlib_symbol: str) -> str:
        if qlib_symbol.startswith("SZ") or qlib_symbol.startswith("SH"):
            return qlib_symbol[2:]
        return qlib_symbol

    def qlib_to_vnpy_symbol(self, qlib_symbol: str) -> str:
        if qlib_symbol.startswith("SZ"):
            return f"{qlib_symbol[2:]}.SZ"
        elif qlib_symbol.startswith("SH"):
            return f"{qlib_symbol[2:]}.SH"
        elif qlib_symbol.startswith("BJ"):
            return f"{qlib_symbol[2:]}.BJ"
        return qlib_symbol

    def vnpy_to_qlib_symbol(self, vnpy_symbol: str) -> str:
        parts = vnpy_symbol.split(".")
        if len(parts) == 2:
            code, exchange = parts
            return f"{exchange}{code}"
        return vnpy_symbol

    def fetch_stock_daily(self, symbol: str, days: int = None) -> pd.DataFrame:
        if days is None:
            days = self.config.get("history_days", 365)

        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)

        cache_file = self.cache_dir / f"daily_{symbol}.parquet"
        if cache_file.exists():
            file_age = time.time() - cache_file.stat().st_mtime
            # 根据时段设置不同的缓存过期时间：
            # 工作日9:00-15:00，缓存3600秒（1小时）
            # 其他时间缓存21600秒（6小时）
            now = datetime.now()
            is_trading_time = now.weekday() < 5 and 9 <= now.hour < 15
            cache_timeout = self.config.get("update_interval", 3600) if is_trading_time else 21600
            
            if file_age < cache_timeout:
                logger.debug(f"Loading cached data for {symbol} (file age: {file_age:.0f}s)")
                df = pd.read_parquet(cache_file)
                latest = pd.to_datetime(df["date"].max())
                # 检查是否包含足够的数据
                if latest >= pd.Timestamp(end_date.date()) - timedelta(days=2):
                    return df

        df = self._fetch_daily_from_primary(symbol, start_date, end_date)

        if df.empty:
            df = self._fetch_daily_from_fallback(symbol, start_date, end_date)

        if not df.empty:
            df = self._normalize_akshare_daily(df, symbol)
            df.to_parquet(cache_file, index=False)
            logger.info(f"Fetched {len(df)} records for {symbol}")
        elif cache_file.exists():
            file_age = time.time() - cache_file.stat().st_mtime
            now = datetime.now()
            is_trading_time = now.weekday() < 5 and 9 <= now.hour < 15
            if is_trading_time and file_age > 3600:
                logger.warning(f"⚠️ Using stale cached data for {symbol} (file age: {file_age:.0f}s, >1h) during trading hours — data may be outdated")
            else:
                logger.warning(f"Using cached data for {symbol} due to API failures (file age: {file_age:.0f}s)")
            df = pd.read_parquet(cache_file)
        else:
            df = self._generate_simulated_daily(symbol, start_date, end_date)
            if not df.empty:
                df.to_parquet(cache_file, index=False)
                logger.warning(f"⚠️🚨 使用模拟数据 {symbol} — 此数据仅用于UI展示，不应传入因子引擎训练。如需训练请使用真实数据源。")

        return df

    @retry(max_attempts=2, delay=0.5)
    def _fetch_daily_from_primary(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        try:
            if not self._data_source_healthy and self._last_health_check:
                time_since_check = (datetime.now() - pd.to_datetime(self._last_health_check["timestamp"])).total_seconds()
                if time_since_check < 300:
                    logger.debug(f"Skipping primary source (health check failed recently)")
                    return pd.DataFrame()

            logger.info(f"Fetching daily data for {symbol} from Sina (primary)")

            # 使用新浪财经 API 获取日K线数据
            code = self.qlib_to_akshare_symbol(symbol)
            exchange = "sh" if code.startswith("6") or code.startswith("SH") else "sz"
            sina_symbol = f"{exchange}{code}"
            if code.startswith("BJ") or symbol.startswith("BJ"):
                sina_symbol = f"bj{code}"

            import urllib.request, json
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

            url = (
                f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
                f"CN_MarketData.getKLineData?symbol={sina_symbol}"
                f"&scale=240&ma=5&datalen={min((end_date - start_date).days, 1024)}"
            )
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
                "Referer": "https://finance.sina.com.cn/",
            })
            resp = urllib.request.urlopen(req, timeout=15, context=ctx)
            raw = resp.read().decode("utf-8")
            records = json.loads(raw)

            if records and isinstance(records, list):
                rows = []
                for r in records:
                    rows.append({
                        "日期": r["day"],
                        "开盘": float(r["open"]),
                        "收盘": float(r["close"]),
                        "最高": float(r["high"]),
                        "最低": float(r["low"]),
                        "成交量": float(r.get("volume", 0)),
                    })
                if rows:
                    df = pd.DataFrame(rows)
                    df["日期"] = pd.to_datetime(df["日期"])
                    df = df.sort_values("日期")
                    self._data_source_healthy = True
                    logger.info(f"Sina returned {len(df)} records for {symbol}")
                    return df

            logger.warning(f"No data from Sina for {symbol}, trying AKShare")
            code_ak = self.qlib_to_akshare_symbol(symbol)
            df = self.akshare.stock_zh_a_hist(
                symbol=code_ak, period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"), adjust="qfq",
            )
            if df is not None and not df.empty:
                self._data_source_healthy = True
                return df
            return pd.DataFrame()

        except Exception as e:
            logger.error(f"Primary data source failed for {symbol}: {e}")
            self._data_source_healthy = False
            return pd.DataFrame()

    def _fetch_daily_from_fallback(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        fallback_source = self.config.get("fallback_source", "tushare")
        logger.info(f"Attempting fallback source: {fallback_source}")

        try:
            if fallback_source == "tushare":
                import tushare as ts
                self._tushare_available = True
                code = self.qlib_to_akshare_symbol(symbol)
                exchange = "SZ" if symbol.startswith("SZ") else ("BJ" if symbol.startswith("BJ") else "SH")
                ts_code = f"{code}.{exchange}"
                pro = ts.pro_api()
                df = pro.daily(
                    ts_code=ts_code,
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                )
                if df is not None and not df.empty:
                    df = df.rename(columns={
                        "trade_date": "日期",
                        "open": "开盘",
                        "high": "最高",
                        "low": "最低",
                        "close": "收盘",
                        "vol": "成交量",
                    })
                    df = df[["日期", "开盘", "收盘", "最高", "最低", "成交量"]]
                    logger.info(f"Fallback source returned {len(df)} records for {symbol}")
                    return df
        except ImportError:
            logger.warning("Tushare not installed, skipping fallback")
            self._tushare_available = False
        except Exception as e:
            logger.error(f"Fallback source failed for {symbol}: {e}")

        yf_df = self._fetch_daily_from_yfinance(symbol, start_date, end_date)
        if not yf_df.empty:
            return yf_df

        return pd.DataFrame()

    def _fetch_daily_from_yfinance(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        try:
            import yfinance as yf
            code = self.qlib_to_akshare_symbol(symbol)
            if symbol.startswith("SZ"):
                yf_symbol = f"{code}.SZ"
            elif symbol.startswith("SH"):
                yf_symbol = f"{code}.SS"
            else:
                yf_symbol = code

            logger.info(f"Attempting yfinance for {yf_symbol}")
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(start=start_date, end=end_date, auto_adjust=True)

            if df is None or df.empty:
                return pd.DataFrame()

            df = df.reset_index()
            df = df.rename(columns={
                "Date": "日期",
                "Open": "开盘",
                "High": "最高",
                "Low": "最低",
                "Close": "收盘",
                "Volume": "成交量",
            })
            df = df[["日期", "开盘", "收盘", "最高", "最低", "成交量"]]
            df["日期"] = pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d")
            logger.info(f"yfinance returned {len(df)} records for {symbol}")
            return df
        except ImportError:
            logger.warning("yfinance not installed, skipping")
            return pd.DataFrame()
        except Exception as e:
            logger.error(f"yfinance failed for {symbol}: {e}")
            return pd.DataFrame()

    def _generate_simulated_daily(self, symbol: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        default_params = {"base_price": 50, "volatility": 0.02, "drift": 0.0001, "name": symbol}
        
        try:
            config = get_config()
            params = config.get("simulated_stocks", {}).get(symbol, default_params)
        except Exception as e:
            logger.warning(f"Failed to get simulated stock params from config: {e}")
            params = default_params

        np.random.seed(hash(symbol) % 2**31)

        base_price = params["base_price"]
        volatility = params["volatility"]
        drift = params["drift"]

        business_days = pd.bdate_range(start=start_date, end=end_date)
        n = len(business_days)
        if n == 0:
            return pd.DataFrame()

        returns = np.random.normal(drift, volatility, n)
        trend = np.linspace(0, 0.3 * np.random.choice([-1, 1]), n)
        cycle = 0.05 * np.sin(np.linspace(0, 4 * np.pi, n))
        returns = returns + trend / n + cycle / n

        prices = base_price * np.exp(np.cumsum(returns))

        open_prices = np.round(prices * (1 + np.random.uniform(-0.01, 0.01, n)), 2)
        close_prices = np.round(prices, 2)
        high_prices = np.round(prices * (1 + np.abs(np.random.normal(0, 0.008, n))), 2)
        low_prices = np.round(prices * (1 - np.abs(np.random.normal(0, 0.008, n))), 2)
        high_prices = np.maximum(high_prices, np.maximum(open_prices, close_prices))
        low_prices = np.minimum(low_prices, np.minimum(open_prices, close_prices))

        df = pd.DataFrame({
            "date": business_days,
            "open": open_prices,
            "close": close_prices,
            "high": high_prices,
            "low": low_prices,
            "volume": np.random.randint(500000, 5000000, n).astype(int),
            "symbol": symbol,
        })

        logger.info(f"Generated {len(df)} simulated records for {symbol} ({params.get('name', '')})")
        return df

    def fetch_stock_realtime(self, symbol: str) -> dict:
        result = self._fetch_realtime_from_primary(symbol)
        if not result:
            result = self._fetch_realtime_from_fallback(symbol)

        if result and result.get("price", 0) > 0:
            result["data_source"] = "realtime"
            result["is_delayed"] = False
        else:
            result = self._get_price_from_daily(symbol)
            if result:
                result["data_source"] = "daily_fallback"
                result["is_delayed"] = True
                logger.warning(f"Using delayed daily data for {symbol}")

        return result

    @retry(max_attempts=2, delay=0.3)
    def _fetch_realtime_from_primary(self, symbol: str) -> dict:
        try:
            code = self.qlib_to_akshare_symbol(symbol)
            df = self.akshare.stock_zh_a_spot_em()
            row = df[df["代码"] == code]
            if row.empty:
                logger.warning(f"No realtime data for {symbol}")
                return {}

            row = row.iloc[0]
            return {
                "symbol": symbol,
                "name": row.get("名称", ""),
                "price": float(row.get("最新价", 0)),
                "change_pct": float(row.get("涨跌幅", 0)),
                "change_amt": float(row.get("涨跌额", 0)),
                "volume": float(row.get("成交量", 0)),
                "turnover": float(row.get("成交额", 0)),
                "high": float(row.get("最高", 0)),
                "low": float(row.get("最低", 0)),
                "open": float(row.get("今开", 0)),
                "prev_close": float(row.get("昨收", 0)),
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.error(f"Failed to fetch realtime data from primary for {symbol}: {e}")
            return {}

    def _fetch_realtime_from_fallback(self, symbol: str) -> dict:
        try:
            code = self.qlib_to_akshare_symbol(symbol)
            df = self.akshare.stock_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=(datetime.now() - timedelta(days=5)).strftime("%Y%m%d"),
                end_date=datetime.now().strftime("%Y%m%d"),
                adjust="qfq",
            )
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                return {
                    "symbol": symbol,
                    "name": "",
                    "price": float(latest.get("收盘", 0)),
                    "change_pct": float((latest.get("收盘", 0) - prev.get("收盘", 0)) / prev.get("收盘", 1) * 100),
                    "change_amt": float(latest.get("收盘", 0) - prev.get("收盘", 0)),
                    "volume": float(latest.get("成交量", 0)),
                    "turnover": float(latest.get("成交额", 0)),
                    "high": float(latest.get("最高", 0)),
                    "low": float(latest.get("最低", 0)),
                    "open": float(latest.get("开盘", 0)),
                    "prev_close": float(prev.get("收盘", 0)),
                    "timestamp": datetime.now().isoformat(),
                }
        except Exception as e:
            logger.error(f"Fallback realtime fetch failed for {symbol}: {e}")

        return {}

    def _get_price_from_daily(self, symbol: str) -> dict:
        try:
            df = self.fetch_stock_daily(symbol, days=5)
            if df is not None and not df.empty:
                latest = df.iloc[-1]
                prev = df.iloc[-2] if len(df) > 1 else latest
                return {
                    "symbol": symbol,
                    "name": "",
                    "price": float(latest.get("close", 0)),
                    "change_pct": float(latest.get("change_pct", 0)),
                    "volume": float(latest.get("volume", 0)),
                    "high": float(latest.get("high", 0)),
                    "low": float(latest.get("low", 0)),
                    "open": float(latest.get("open", 0)),
                    "prev_close": float(prev.get("close", 0)),
                    "timestamp": datetime.now().isoformat(),
                    "is_delayed": True,
                }
        except Exception as e:
            logger.error(f"Failed to get price from daily data for {symbol}: {e}")

        return {}

    def fetch_stock_minutes(self, symbol: str, period: str = "5") -> pd.DataFrame:
        try:
            code = self.qlib_to_akshare_symbol(symbol)
            period_map = {"1": "1", "5": "5", "15": "15", "30": "30", "60": "60"}
            ak_period = period_map.get(period, "5")

            df = self.akshare.stock_zh_a_hist_min_em(
                symbol=code,
                period=ak_period,
                adjust="qfq",
            )

            if df is None or df.empty:
                return pd.DataFrame()

            return self._normalize_akshare_minutes(df, symbol)
        except Exception as e:
            logger.error(f"Failed to fetch minute data for {symbol}: {e}")
            return pd.DataFrame()

    def fetch_multi_stocks(self, symbols: list, days: int = None) -> dict:
        result = {}
        for symbol in symbols:
            df = self.fetch_stock_daily(symbol, days)
            if not df.empty:
                result[symbol] = df
            time.sleep(0.5)
        return result

    def get_market_overview(self) -> pd.DataFrame:
        try:
            df = self.akshare.stock_zh_a_spot_em()
            return df
        except Exception as e:
            logger.error(f"Failed to fetch market overview: {e}")
            return pd.DataFrame()

    def _normalize_akshare_daily(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        col_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "turnover",
            "振幅": "amplitude",
            "涨跌幅": "change_pct",
            "涨跌额": "change_amt",
            "换手率": "turnover_rate",
        }

        df = df.rename(columns=col_map)

        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])

        df["symbol"] = symbol

        numeric_cols = ["open", "close", "high", "low", "volume", "turnover"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["open", "close", "high", "low"])

        df = df.sort_values("date").reset_index(drop=True)
        return df

    def _normalize_akshare_minutes(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        col_map = {
            "时间": "datetime",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "turnover",
        }

        df = df.rename(columns=col_map)

        if "datetime" in df.columns:
            df["datetime"] = pd.to_datetime(df["datetime"])

        df["symbol"] = symbol

        numeric_cols = ["open", "close", "high", "low", "volume", "turnover"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df.sort_values("datetime").reset_index(drop=True)

    def to_qlib_format(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if df.empty:
            return df

        qlib_df = pd.DataFrame()
        date_col = "date" if "date" in df.columns else "datetime"
        qlib_df["date"] = pd.to_datetime(df[date_col]).dt.strftime("%Y-%m-%d")
        qlib_df["instrument"] = symbol
        qlib_df["$open"] = df["open"].values
        qlib_df["$high"] = df["high"].values
        qlib_df["$low"] = df["low"].values
        qlib_df["$close"] = df["close"].values
        qlib_df["$volume"] = df["volume"].values

        if "turnover" in df.columns:
            qlib_df["$turnover"] = df["turnover"].values

        qlib_df["$factor"] = 1.0

        return qlib_df

    def calc_technical_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or len(df) < 20:
            return df

        df = df.copy()

        df["ma5"] = df["close"].rolling(window=5).mean()
        df["ma10"] = df["close"].rolling(window=10).mean()
        df["ma20"] = df["close"].rolling(window=20).mean()
        df["ma60"] = df["close"].rolling(window=60).mean()

        delta = df["close"].diff()
        gain = delta.where(delta > 0, 0)
        loss = (-delta).where(delta < 0, 0)
        avg_gain = gain.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, np.inf)
        df["rsi"] = 100 - (100 / (1 + rs))

        ema12 = df["close"].ewm(span=12, adjust=False).mean()
        ema26 = df["close"].ewm(span=26, adjust=False).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        low_min = df["low"].rolling(window=14).min()
        high_max = df["high"].rolling(window=14).max()
        df["KDJ_K"] = 100 * (df["close"] - low_min) / (high_max - low_min).replace(0, np.inf)
        df["KDJ_D"] = df["KDJ_K"].rolling(window=3).mean()
        df["KDJ_J"] = 3 * df["KDJ_K"] - 2 * df["KDJ_D"]

        df["boll_mid"] = df["close"].rolling(window=20).mean()
        boll_std = df["close"].rolling(window=20).std()
        df["boll_upper"] = df["boll_mid"] + 2 * boll_std
        df["boll_lower"] = df["boll_mid"] - 2 * boll_std

        df["vol_ma5"] = df["volume"].rolling(window=5).mean()
        df["vol_ma10"] = df["volume"].rolling(window=10).mean()

        return df

    def is_qlib_available(self) -> bool:
        try:
            import qlib
            return True
        except ImportError:
            return False

    def is_akshare_available(self) -> bool:
        try:
            import akshare
            return True
        except ImportError:
            return False

    def is_tushare_available(self) -> bool:
        return self._tushare_available
