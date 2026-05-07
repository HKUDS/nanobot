"""Market data tools using akshare for stock/crypto analysis."""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters


def _disable_proxy_for_akshare():
    """Disable proxy for akshare requests to avoid connection issues."""
    import requests
    from urllib.request import getproxies, proxy_bypass
    
    # Save original proxy settings
    original_proxies = {
        'http': os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy'),
        'https': os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy'),
    }
    # Clear proxy environment variables
    for key in ['HTTP_PROXY', 'HTTPS_PROXY', 'http_proxy', 'https_proxy', 
                'ALL_PROXY', 'all_proxy']:
        os.environ.pop(key, None)
    
    # Set NO_PROXY to bypass all proxies
    os.environ['NO_PROXY'] = '*'
    os.environ['no_proxy'] = '*'
    
    # Monkey patch urllib to ignore proxies
    import urllib.request
    urllib.request.getproxies = lambda: {}
    
    # Also set requests session to not use proxies
    try:
        sess = requests.Session()
        sess.trust_env = False
        sess.proxies = {}
    except:
        pass
    
    return original_proxies


def _restore_proxy(original_proxies: dict):
    """Restore original proxy settings."""
    for key, value in original_proxies.items():
        if value is not None:
            os.environ[key.upper()] = value


@tool_parameters({
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Stock code (e.g., '600519' for A-shares, 'AAPL' for US stocks)",
        },
        "market": {
            "type": "string",
            "enum": ["cn", "hk", "us"],
            "description": "Market type: cn (A股), hk (港股), us (美股)",
            "default": "cn",
        },
        "period": {
            "type": "string",
            "enum": ["realtime", "daily", "weekly", "monthly"],
            "description": "Data period",
            "default": "realtime",
        },
        "days": {
            "type": "integer",
            "description": "Number of days for historical data",
            "default": 30,
            "minimum": 1,
        },
    },
    "required": ["symbol"],
})
class StockPriceTool(Tool):
    """Get real-time and historical stock prices using akshare."""

    name = "stock_price"
    description = """获取股票实时价格和歷史数据。支持 A股、港股、美股。

Examples:
- stock_price(symbol="600519")  # 贵州茅台
- stock_price(symbol="AAPL", market="us")  # 苹果美股
- stock_price(symbol="00700", market="hk")  # 腾讯控股
- stock_price(symbol="600519", period="daily", days=30)  # 最近30天日线
"""

    def __init__(self):
        super().__init__()
        self._cache: dict[str, tuple[Any, float]] = {}
        self._cache_ttl = 60  # 60 seconds cache

    async def execute(
        self,
        symbol: str,
        market: str = "cn",
        period: str = "realtime",
        days: int = 30,
        **kwargs: Any,
    ) -> str:
        """
        Execute stock price query.

        Args:
            symbol: Stock code (e.g., "600519" for A-shares, "AAPL" for US stocks)
            market: Market type - "cn" (A股), "hk" (港股), "us" (美股)
            period: Data period - "realtime", "daily", "weekly", "monthly"
            days: Number of days for historical data (default: 30)

        Returns:
            Formatted stock price information
        """
        try:
            import akshare as ak
        except ImportError:
            return "Error: akshare not installed. Run: pip install akshare"

        cache_key = f"{symbol}_{market}_{period}_{days}"
        now = asyncio.get_event_loop().time()

        # Check cache
        if cache_key in self._cache:
            cached_data, cached_time = self._cache[cache_key]
            if now - cached_time < self._cache_ttl:
                logger.debug("Using cached data for {}", symbol)
                return cached_data

        # Disable proxy for akshare to avoid connection issues
        original_proxies = _disable_proxy_for_akshare()
        try:
            if period == "realtime":
                result = await self._get_realtime_price(ak, symbol, market)
            else:
                result = await self._get_historical_data(ak, symbol, market, period, days)

            # Cache the result
            self._cache[cache_key] = (result, now)
            return result
        except Exception as e:
            logger.error("Failed to get stock price for {}: {}", symbol, e)
            return f"Error fetching data for {symbol}: {str(e)}"
        finally:
            # Restore proxy settings
            _restore_proxy(original_proxies)

    async def _get_realtime_price(self, ak: Any, symbol: str, market: str) -> str:
        """Get real-time stock price using Sina API (more stable)."""
        try:
            if market == "cn":
                # A股实时行情 - 使用新浪财经API（更稳定）
                df = ak.stock_zh_a_spot()
                stock_data = df[df['代码'] == symbol]

                if stock_data.empty:
                    return f"未找到股票代码: {symbol}"

                row = stock_data.iloc[0]
                return self._format_cn_stock(row)

            elif market == "hk":
                # 港股实时行情 - 使用新浪财经API
                df = ak.stock_hk_spot()
                stock_data = df[df['代码'] == symbol]

                if stock_data.empty:
                    return f"未找到港股代码: {symbol}"

                row = stock_data.iloc[0]
                return self._format_hk_stock(row)

            elif market == "us":
                # 美股实时行情 - 使用新浪财经API（带错误处理）
                try:
                    df = ak.stock_us_spot()
                    stock_data = df[df['代码'] == symbol]

                    if stock_data.empty:
                        return f"未找到美股代码: {symbol}\n提示: 美股数据可能受网络影响，请稍后重试"

                    row = stock_data.iloc[0]
                    return self._format_us_stock(row)
                except Exception as us_error:
                    logger.warning(f"美股API失败: {us_error}，尝试备用方案")
                    # 备用方案：尝试使用历史数据API获取最新价格
                    try:
                        return await self._get_us_stock_fallback(ak, symbol)
                    except Exception:
                        raise RuntimeError(f"美股数据获取失败: {us_error}")

            else:
                return f"不支持的市场类型: {market} (支持: cn, hk, us)"

        except Exception as e:
            raise RuntimeError(f"Real-time price fetch failed: {e}")

    async def _get_us_stock_fallback(self, ak: Any, symbol: str) -> str:
        """Fallback method for US stocks when spot API fails."""
        # Try to get recent data from historical API
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=5)).strftime("%Y%m%d")
            
            df = ak.stock_us_hist(
                symbol=symbol,
                start_date=start_date,
                end_date=end_date,
                adjust=""
            )
            
            if df.empty:
                return f"无法获取 {symbol} 的数据"
            
            # Get the latest row
            latest = df.iloc[-1]
            
            # Map historical data fields to real-time format
            class FakeRow:
                def __init__(self, data):
                    self.data = data
                def get(self, key, default=None):
                    # Map Chinese field names from stock_us_hist
                    field_map = {
                        '名称': 'name',
                        '代码': 'symbol',
                        '最新价': 'close',
                        '收盘价': 'close',
                        '涨跌幅': 'pct_change',
                        '涨跌额': 'change',
                        '成交量': 'volume',
                        '成交额': 'turnover',
                        '最高': 'high',
                        '最低': 'low',
                        '今开': 'open',
                        '开盘': 'open',
                        '昨收': 'prev_close',
                    }
                    mapped_key = field_map.get(key, key)
                    return self.data.get(mapped_key, self.data.get(key, default))
            
            fake_row = FakeRow(latest.to_dict())
            fake_row.data['名称'] = symbol  # Use symbol as name if not available
            fake_row.data['代码'] = symbol
            
            return self._format_us_stock(fake_row)
        except Exception as e:
            raise RuntimeError(f"美股备用方案也失败: {e}")

    async def _get_historical_data(
        self, ak: Any, symbol: str, market: str, period: str, days: int
    ) -> str:
        """Get historical stock data using Sina API (more stable)."""
        try:
            if market == "cn":
                # A股历史数据 - 使用新浪财经API
                end_date = datetime.now().strftime("%Y%m%d")
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y%m%d")

                df = ak.stock_zh_a_daily(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq"  # 前复权
                )

                if df.empty:
                    return f"未找到 {symbol} 的历史数据"

                return self._format_historical_cn(df, symbol, days)

            elif market == "us":
                # 美股历史数据 - 使用雅虎财经API
                end_date = datetime.now().strftime("%Y-%m-%d")
                start_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

                df = ak.stock_us_daily(
                    symbol=symbol,
                    adjust="qfq"
                )
                
                # Filter by date range
                df['date'] = pd.to_datetime(df['date'])
                df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]

                if df.empty:
                    return f"未找到 {symbol} 的历史数据"

                return self._format_historical_us(df, symbol, days)

            else:
                return f"暂不支持 {market} 市场的历史数据查询"

        except Exception as e:
            raise RuntimeError(f"Historical data fetch failed: {e}")

    def _format_cn_stock(self, row: pd.Series) -> str:
        """Format A-share stock data (Sina API format)."""
        name = row.get('名称', 'N/A')
        code = row.get('代码', 'N/A')
        price = row.get('最新价', 0)
        change = row.get('涨跌幅', 0)
        change_amount = row.get('涨跌额', 0)
        volume = row.get('成交量', 0)
        amount = row.get('成交额', 0)
        high = row.get('最高', 0)
        low = row.get('最低', 0)
        open_price = row.get('今开', 0)
        prev_close = row.get('昨收', 0)

        # Format numbers
        volume_str = self._format_volume(volume)
        amount_str = self._format_amount(amount)

        # Determine trend emoji
        trend = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        change_sign = "+" if change > 0 else ""

        return f"""{trend} **{name} ({code})** - A股实时行情

💰 **当前价格**: ¥{price:.2f}
📊 **涨跌**: {change_sign}{change:.2f}% ({change_sign}{change_amount:.2f})

📈 **今日走势**:
• 开盘: ¥{open_price:.2f}
• 最高: ¥{high:.2f}
• 最低: ¥{low:.2f}
• 昨收: ¥{prev_close:.2f}

📦 **成交情况**:
• 成交量: {volume_str}
• 成交额: {amount_str}

⏰ **更新时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    def _format_hk_stock(self, row: pd.Series) -> str:
        """Format Hong Kong stock data (Sina API format)."""
        name = row.get('名称', 'N/A')
        code = row.get('代码', 'N/A')
        price = row.get('最新价', 0)
        change = row.get('涨跌幅', 0)

        trend = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        change_sign = "+" if change > 0 else ""

        return f"""{trend} **{name} ({code})** - 港股实时行情

💰 **当前价格**: HK${price:.2f}
📊 **涨跌幅**: {change_sign}{change:.2f}%

⏰ **更新时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    def _format_us_stock(self, row: pd.Series) -> str:
        """Format US stock data (Sina API format)."""
        name = row.get('名称', 'N/A')
        code = row.get('代码', 'N/A')
        price = row.get('最新价', 0)
        change = row.get('涨跌幅', 0)

        trend = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        change_sign = "+" if change > 0 else ""

        return f"""{trend} **{name} ({code})** - 美股实时行情

💰 **当前价格**: ${price:.2f}
📊 **涨跌幅**: {change_sign}{change:.2f}%

⏰ **更新时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

    def _format_historical_cn(self, df: pd.DataFrame, symbol: str, days: int) -> str:
        """Format historical A-share data (Sina API format)."""
        # Get basic info - Sina API uses English field names
        latest = df.iloc[-1]
        earliest = df.iloc[0]

        name = self._get_stock_name(symbol)
        
        # Try both English and Chinese field names for compatibility
        current_price = latest.get('close', latest.get('收盘', 0))
        start_price = earliest.get('close', earliest.get('收盘', 0))
        total_change = ((current_price - start_price) / start_price) * 100 if start_price != 0 else 0

        # Calculate statistics
        avg_price = df.get('close', df.get('收盘')).mean()
        max_price = df.get('high', df.get('最高')).max()
        min_price = df.get('low', df.get('最低')).min()
        avg_volume = df.get('volume', df.get('成交量')).mean()

        trend = "📈" if total_change > 0 else "📉"
        change_sign = "+" if total_change > 0 else ""

        # Get recent 5 days
        recent = df.tail(5)
        recent_data = "\n".join([
            f"  • {row.get('date', row.get('日期', 'N/A'))}: ¥{row.get('close', row.get('收盘', 0)):.2f} ({'+' if row.get('pricechange', row.get('涨跌幅', 0)) > 0 else ''}{row.get('pricechange', row.get('涨跌幅', 0)):.2f}%)"
            for _, row in recent.iterrows()
        ])

        return f"""{trend} **{name} ({symbol})** - {days}日历史数据分析

📊 **价格概览**:
• 当前价格: ¥{current_price:.2f}
• {days}日前: ¥{start_price:.2f}
• 期间涨跌: {change_sign}{total_change:.2f}%

📈 **统计数据**:
• 平均价格: ¥{avg_price:.2f}
• 最高价: ¥{max_price:.2f}
• 最低价: ¥{min_price:.2f}
• 平均成交量: {self._format_volume(avg_volume)}

📅 **最近5个交易日**:
{recent_data}

⏰ **数据范围**: {earliest.get('date', earliest.get('日期', 'N/A'))} 至 {latest.get('date', latest.get('日期', 'N/A'))}
"""

    def _format_historical_us(self, df: pd.DataFrame, symbol: str, days: int) -> str:
        """Format historical US stock data (Yahoo/Sina API format)."""
        latest = df.iloc[-1]
        earliest = df.iloc[0]

        # Try both English and Chinese field names
        current_price = latest.get('close', latest.get('收盘', 0))
        start_price = earliest.get('close', earliest.get('收盘', 0))
        total_change = ((current_price - start_price) / start_price) * 100 if start_price != 0 else 0

        trend = "📈" if total_change > 0 else "📉"
        change_sign = "+" if total_change > 0 else ""

        recent = df.tail(5)
        recent_data = "\n".join([
            f"  • {row.get('date', row.get('日期', 'N/A'))}: ${row.get('close', row.get('收盘', 0)):.2f} ({'+' if row.get('pricechange', row.get('涨跌幅', 0)) > 0 else ''}{row.get('pricechange', row.get('涨跌幅', 0)):.2f}%)"
            for _, row in recent.iterrows()
        ])

        return f"""{trend} **{symbol}** - {days}日历史数据分析

📊 **价格概览**:
• 当前价格: ${current_price:.2f}
• {days}日前: ${start_price:.2f}
• 期间涨跌: {change_sign}{total_change:.2f}%

📅 **最近5个交易日**:
{recent_data}

⏰ **数据范围**: {earliest.get('date', earliest.get('日期', 'N/A'))} 至 {latest.get('date', latest.get('日期', 'N/A'))}
"""

    def _get_stock_name(self, symbol: str) -> str:
        """Get stock name by symbol (simplified)."""
        # This could be enhanced with a proper stock info lookup
        stock_names = {
            "600519": "贵州茅台",
            "000858": "五粮液",
            "600036": "招商银行",
            "000333": "美的集团",
            "601318": "中国平安",
        }
        return stock_names.get(symbol, f"股票{symbol}")

    @staticmethod
    def _format_volume(volume: float) -> str:
        """Format volume number."""
        if volume >= 1_0000_0000:
            return f"{volume / 1_0000_0000:.2f}亿手"
        elif volume >= 1_0000:
            return f"{volume / 1_0000:.2f}万手"
        else:
            return f"{volume:.0f}手"

    @staticmethod
    def _format_amount(amount: float) -> str:
        """Format amount number."""
        if amount >= 1_0000_0000:
            return f"¥{amount / 1_0000_0000:.2f}亿"
        elif amount >= 1_0000:
            return f"¥{amount / 1_0000:.2f}万"
        else:
            return f"¥{amount:.2f}"


@tool_parameters({
    "type": "object",
    "properties": {
        "symbol": {
            "type": "string",
            "description": "Cryptocurrency symbol (e.g., 'BTC', 'ETH', 'SOL')",
        },
    },
    "required": ["symbol"],
})
class CryptoPriceTool(Tool):
    """Get cryptocurrency prices using akshare."""

    name = "crypto_price"
    description = """获取加密货币实时价格。支持 BTC, ETH, SOL 等主流币种。

Examples:
- crypto_price(symbol="BTC")  # 比特币
- crypto_price(symbol="ETH")  # 以太坊
- crypto_price(symbol="SOL")  # Solana
"""

    async def execute(self, symbol: str, **kwargs: Any) -> str:
        """Get crypto price."""
        try:
            import akshare as ak
        except ImportError:
            return "Error: akshare not installed. Run: pip install akshare"

        # Disable proxy for akshare to avoid connection issues
        original_proxies = _disable_proxy_for_akshare()
        try:
            # Use crypto JS spot prices (more stable)
            df = ak.crypto_js_spot()

            # Normalize symbol
            symbol_upper = symbol.upper()
            symbol_map = {
                "BTC": "BTC",
                "ETH": "ETH",
                "SOL": "SOL",
                "BNB": "BNB",
                "XRP": "XRP",
                "ADA": "ADA",
                "DOGE": "DOGE",
            }

            normalized = symbol_map.get(symbol_upper, symbol_upper)

            # Find the crypto - try both 'symbol' and '交易对' column names
            if 'symbol' in df.columns:
                crypto_data = df[df['symbol'] == normalized]
            elif '交易品种' in df.columns:
                # For crypto_js_spot, symbol is like "BTCUSD", "ETHUSD", etc.
                # Try to match with USD or USDT suffix
                crypto_data = df[df['交易品种'].str.startswith(normalized, na=False)]
                # If multiple matches, take the first one
                if len(crypto_data) > 1:
                    crypto_data = crypto_data.head(1)
            else:
                return f"无法解析加密货币数据格式\n可用列: {df.columns.tolist()}"

            if crypto_data.empty:
                # Get available symbols for user reference
                if '交易品种' in df.columns:
                    available = df['交易品种'].unique().tolist()
                elif 'symbol' in df.columns:
                    available = df['symbol'].unique().tolist()
                else:
                    available = []
                return f"未找到加密货币: {symbol}\n当前可用的币种: {', '.join(available[:10])}"

            row = crypto_data.iloc[0]
            return self._format_crypto(row, symbol_upper)

        except Exception as e:
            logger.error("Failed to get crypto price for {}: {}", symbol, e)
            return f"Error fetching crypto data for {symbol}: {str(e)}"
        finally:
            # Restore proxy settings
            _restore_proxy(original_proxies)

    def _format_crypto(self, row: pd.Series, symbol: str) -> str:
        """Format cryptocurrency data (crypto_js_spot format)."""
        # Try both English and Chinese field names
        name = row.get('交易品种', row.get('name', symbol))
        price = row.get('最近报价', row.get('price', 0))
        change_24h = row.get('涨跌幅', row.get('percent_change_24h', 0))
        change_amount = row.get('涨跌额', 0)
        high_24h = row.get('24小时最高', 0)
        low_24h = row.get('24小时最低', 0)
        volume_24h = row.get('24小时成交量', row.get('volume_24h', 0))
        market = row.get('市场', 'N/A')

        trend = "📈" if change_24h > 0 else "📉" if change_24h < 0 else "➡️"
        change_sign = "+" if change_24h > 0 else ""

        return f"""{trend} **{symbol}** - 加密货币实时价格

💰 **当前价格**: ${price:,.2f}
📊 **24h涨跌**: {change_sign}{change_24h:.2f}% ({change_sign}{change_amount:.2f})

📈 **24h走势**:
• 最高: ${high_24h:,.2f}
• 最低: ${low_24h:,.2f}
• 成交量: ${volume_24h:,.2f}

🏢 **交易市场**: {market}

⏰ **更新时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
