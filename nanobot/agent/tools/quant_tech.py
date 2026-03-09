"""技术分析 Tool - K线形态、均线交叉、技术指标"""
import asyncio
import pandas as pd
import numpy as np
from typing import Optional
from datetime import datetime, timedelta

from nanobot.agent.tools.base import Tool


class QuantTechTool(Tool):
    """
    技术分析工具
    提供K线形态识别、均线交叉信号、MACD/KDJ/RSI/BOLL等技术指标计算
    """

    name = "quant_tech"
    description = (
        "股票技术分析工具，提供K线形态识别、均线交叉信号、MACD/KDJ/RSI/BOLL等技术指标。"
        "分析完成后，必须主动为用户提供更多解读："
        "1) 技术信号解读（多头/空头、超买/超卖）"
        "2) 对比该股票与板块/指数的相对强弱"
        "3) 结合基本面分析（如果相关）"
        "4) 搜索该股票或行业的最新消息/研报作为参考"
        "5) 给出风险提示，但不提供具体买卖建议"
    )

    parameters = {
        "type": "object",
        "properties": {
            "analysis_type": {
                "type": "string",
                "enum": [
                    "kline_pattern",    # K线形态
                    "ma_cross",         # 均线交叉
                    "macd",             # MACD指标
                    "kdj",              # KDJ指标
                    "rsi",              # RSI指标
                    "boll",             # 布林带
                    "combo",            # 组合指标
                    "realtime_tech",    # 实时技术指标
                ],
                "description": "分析类型"
            },
            "symbol": {"type": "string", "description": "股票代码，如 000001.SZ"},
            "days": {"type": "integer", "description": "分析天数，默认30"},
            "period": {"type": "string", "description": "指标周期，如 1d/1w"},
        },
        "required": ["analysis_type", "symbol"],
    }

    async def execute(
        self,
        analysis_type: str,
        symbol: str,
        days: int = 30,
        period: str = "1d",
        **kwargs
    ) -> str:
        """执行技术分析"""
        try:
            # 获取历史数据
            df = await self._get_historical_data(symbol, days + 20)
            if df is None or df.empty:
                return f"Error: 无法获取 {symbol} 的历史数据"

            if analysis_type == "kline_pattern":
                return await self._kline_pattern(df, days)
            elif analysis_type == "ma_cross":
                return await self._ma_cross(df, days)
            elif analysis_type == "macd":
                return await self._macd(df, days)
            elif analysis_type == "kdj":
                return await self._kdj(df, days)
            elif analysis_type == "rsi":
                return await self._rsi(df, days)
            elif analysis_type == "boll":
                return await self._boll(df, days)
            elif analysis_type == "combo":
                return await self._combo(df, days)
            elif analysis_type == "realtime_tech":
                return await self._realtime_tech(symbol)
            else:
                return f"Error: 未知分析类型 {analysis_type}"
        except Exception as e:
            return f"Error: 技术分析失败 - {str(e)}"

    async def _get_historical_data(self, symbol: str, days: int) -> Optional[pd.DataFrame]:
        """获取历史K线数据"""
        try:
            import akshare as ak

            code = symbol.replace(".SZ", "").replace(".SH", "")

            # 使用 AkShare 获取日K数据
            def fetch_data():
                return ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=(datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d"),
                    end_date=datetime.now().strftime("%Y%m%d"),
                    adjust="qfq"
                )

            df = await asyncio.wait_for(asyncio.to_thread(fetch_data), timeout=30.0)

            if df is None or df.empty:
                return None

            # 统一列名
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
                '振幅': 'amplitude',
                '涨跌幅': 'change_pct',
                '涨跌额': 'change',
                '换手率': 'turnover'
            })

            df = df.sort_values('date').reset_index(drop=True)
            return df.tail(days)

        except asyncio.TimeoutError:
            return None
        except Exception as e:
            return None

    async def _kline_pattern(self, df: pd.DataFrame, days: int) -> str:
        """K线形态识别"""
        try:
            from ta.volatility import BollingerBands
            from ta.momentum import RSIIndicator

            df = df.tail(days).copy()

            results = []
            results.append("=" * 50)
            results.append("📊 K线形态分析 (最近{}天)".format(days))
            results.append("=" * 50)

            # 识别最近5天的形态
            recent = df.tail(5)

            for idx, row in recent.iterrows():
                patterns = []
                date = row['date']
                o, h, l, c = row['open'], row['high'], row['low'], row['close']

                # 锤子线: 下影线>=实体2倍，上影线很短
                if (l - min(o, c)) >= 2 * abs(o - c) and (max(o, c) - h) < abs(o - c) * 0.3:
                    patterns.append("锤子线")

                # 上吊线: 上影线很短，下影线>=实体2倍
                if (max(o, c) - h) >= 2 * abs(o - c) and (l - min(o, c)) < abs(o - c) * 0.3:
                    patterns.append("上吊线")

                # 十字星: 开盘≈收盘
                if abs(o - c) <= (h - l) * 0.1:
                    patterns.append("十字星")

                # 大阳线: 涨幅>=5%
                if row.get('change_pct', 0) >= 5:
                    patterns.append("大阳线(+5%+)")

                # 大阴线: 跌幅>=5%
                if row.get('change_pct', 0) <= -5:
                    patterns.append("大阴线(-5%-)")

                if patterns:
                    results.append(f"{date}: {', '.join(patterns)} (收:{c:.2f})")

            results.append("")
            results.append("注: 锤子线可能见底，上吊线可能见顶，十字星表示观望")

            return "\n".join(results)

        except Exception as e:
            return f"Error: K线形态分析失败 - {str(e)}"

    async def _ma_cross(self, df: pd.DataFrame, days: int) -> str:
        """均线交叉信号"""
        try:
            df = df.tail(days + 20).copy()

            # 计算均线
            df['MA5'] = df['close'].rolling(window=5).mean()
            df['MA10'] = df['close'].rolling(window=10).mean()
            df['MA20'] = df['close'].rolling(window=20).mean()
            df['MA60'] = df['close'].rolling(window=60).mean()

            df = df.tail(days)

            results = []
            results.append("=" * 50)
            results.append("📈 均线交叉分析 (MA5/MA10/MA20)")
            results.append("=" * 50)

            # 当前均线值
            last = df.iloc[-1]
            results.append(f"最新收盘: {last['close']:.2f}")
            results.append(f"MA5:  {last['MA5']:.2f}")
            results.append(f"MA10: {last['MA10']:.2f}")
            results.append(f"MA20: {last['MA20']:.2f}")
            if pd.notna(last.get('MA60')):
                results.append(f"MA60: {last['MA60']:.2f}")

            results.append("")

            # 判断均线多头/空头排列
            ma5 = last['MA5']
            ma10 = last['MA10']
            ma20 = last['MA20']

            if pd.notna(ma5) and pd.notna(ma10) and pd.notna(ma20):
                if ma5 > ma10 > ma20:
                    results.append("🔥 多头排列 (MA5>MA10>MA20) - 强势上涨趋势")
                elif ma5 < ma10 < ma20:
                    results.append("🔻 空头排列 (MA5<MA10<MA20) - 弱势下跌趋势")
                else:
                    results.append("➡️ 均线缠绕 - 震荡整理")

            # 最近的金叉/死叉
            df_temp = df.tail(10).copy()
            df_temp['golden'] = (df_temp['MA5'] > df_temp['MA10']) & (df_temp['MA10'].shift(1) <= df_temp['MA20'].shift(1))
            df_temp['death'] = (df_temp['MA5'] < df_temp['MA10']) & (df_temp['MA10'].shift(1) >= df_temp['MA20'].shift(1))

            golden = df_temp[df_temp['golden']].tail(1)
            death = df_temp[df_temp['death']].tail(1)

            if not golden.empty:
                results.append(f"最近金叉: {golden.iloc[0]['date']}")
            if not death.empty:
                results.append(f"最近死叉: {death.iloc[0]['date']}")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 均线分析失败 - {str(e)}"

    async def _macd(self, df: pd.DataFrame, days: int) -> str:
        """MACD指标"""
        try:
            from ta.trend import MACD

            df = df.tail(days + 30).copy()

            # 计算MACD
            macd = MACD(close=df['close'], window_slow=26, window_fast=12, window_sign=9)
            df['macd'] = macd.macd()
            df['macd_signal'] = macd.macd_signal()
            df['macd_diff'] = macd.macd_diff()

            df = df.tail(days)

            results = []
            results.append("=" * 50)
            results.append("📉 MACD 指标分析")
            results.append("=" * 50)

            last = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else last

            results.append(f"MACD线:   {last['macd']:.4f}")
            results.append(f"Signal线: {last['macd_signal']:.4f}")
            results.append(f"Diff:     {last['macd_diff']:.4f}")

            results.append("")

            # 判断信号
            if last['macd_diff'] > 0 and prev['macd_diff'] <= 0:
                results.append("🔥 金叉信号 - MACD线上穿Signal线")
            elif last['macd_diff'] < 0 and prev['macd_diff'] >= 0:
                results.append("🔻 死叉信号 - MACD线下穿Signal线")
            elif last['macd_diff'] > 0:
                results.append("⬆️ MACD多头 - 上涨趋势")
            else:
                results.append("⬇️ MACD空头 - 下跌趋势")

            # 零轴位置
            if last['macd'] > 0:
                results.append("📍 零轴上方 - 中期多头")
            else:
                results.append("📍 零轴下方 - 中期空头")

            return "\n".join(results)

        except Exception as e:
            return f"Error: MACD分析失败 - {str(e)}"

    async def _kdj(self, df: pd.DataFrame, days: int) -> str:
        """KDJ随机指标"""
        try:
            from ta.momentum import StochasticOscillator

            df = df.tail(days + 20).copy()

            # 计算KDJ
            stoch = StochasticOscillator(high=df['high'], low=df['low'], close=df['close'], window=14, smooth_window=3)
            df['k'] = stoch.stoch() * 100
            df['d'] = stoch.stoch_signal() * 100
            df['j'] = 3 * df['k'] - 2 * df['d']

            df = df.tail(days)

            results = []
            results.append("=" * 50)
            results.append("📊 KDJ 随机指标")
            results.append("=" * 50)

            last = df.iloc[-1]
            results.append(f"K值: {last['k']:.2f}")
            results.append(f"D值: {last['d']:.2f}")
            results.append(f"J值: {last['j']:.2f}")
            results.append("")

            k, d = last['k'], last['d']

            # 超买超卖
            if k >= 80:
                results.append("⚠️ K值>=80 - 超买区域 注意回调风险")
            elif k <= 20:
                results.append("⚠️ K值<=20 - 超卖区域 可能反弹")

            # 金叉死叉
            prev = df.iloc[-2]
            if k > d and prev['k'] <= prev['d']:
                results.append("🔥 金叉信号 - K线上穿D值")
            elif k < d and prev['k'] >= prev['d']:
                results.append("🔻 死叉信号 - K线下穿D值")

            return "\n".join(results)

        except Exception as e:
            return f"Error: KDJ分析失败 - {str(e)}"

    async def _rsi(self, df: pd.DataFrame, days: int) -> str:
        """RSI相对强弱指标"""
        try:
            from ta.momentum import RSIIndicator

            df = df.tail(days + 20).copy()

            # 计算RSI
            rsi6 = RSIIndicator(close=df['close'], window=6)
            rsi12 = RSIIndicator(close=df['close'], window=12)
            rsi24 = RSIIndicator(close=df['close'], window=24)

            df['rsi6'] = rsi6.rsi()
            df['rsi12'] = rsi12.rsi()
            df['rsi24'] = rsi24.rsi()

            df = df.tail(days)

            results = []
            results.append("=" * 50)
            results.append("📊 RSI 相对强弱指标")
            results.append("=" * 50)

            last = df.iloc[-1]
            results.append(f"RSI(6):  {last['rsi6']:.2f}")
            results.append(f"RSI(12): {last['rsi12']:.2f}")
            results.append(f"RSI(24): {last['rsi24']:.2f}")
            results.append("")

            # 判断
            rsi = last['rsi12']

            if rsi >= 80:
                results.append("⚠️ RSI>=80 - 严重超买 警惕回调")
            elif rsi >= 70:
                results.append("⚠️ RSI>=70 - 超买区域 注意风险")
            elif rsi <= 30:
                results.append("⚠️ RSI<=30 - 超卖区域 可能反弹")
            elif rsi <= 20:
                results.append("⚠️ RSI<=20 - 严重超卖 关注机会")
            elif rsi > 50:
                results.append("⬆️ RSI>50 - 多头市场")
            else:
                results.append("⬇️ RSI<50 - 空头市场")

            return "\n".join(results)

        except Exception as e:
            return f"Error: RSI分析失败 - {str(e)}"

    async def _boll(self, df: pd.DataFrame, days: int) -> str:
        """布林带指标"""
        try:
            from ta.volatility import BollingerBands

            df = df.tail(days + 20).copy()

            # 计算布林带
            bb = BollingerBands(close=df['close'], window=20, window_dev=2)
            df['bb_upper'] = bb.bollinger_hband()
            df['bb_middle'] = bb.bollinger_mavg()
            df['bb_lower'] = bb.bollinger_lband()
            df['bb_pct'] = bb.bollinger_pband()

            df = df.tail(days)

            results = []
            results.append("=" * 50)
            results.append("📊 布林带指标 (20,2)")
            results.append("=" * 50)

            last = df.iloc[-1]
            close = last['close']
            results.append(f"当前价格: {close:.2f}")
            results.append(f"上轨:     {last['bb_upper']:.2f}")
            results.append(f"中轨:     {last['bb_middle']:.2f}")
            results.append(f"下轨:     {last['bb_lower']:.2f}")
            results.append(f"位置:     {last['bb_pct']*100:.1f}%")
            results.append("")

            # 判断位置
            pct = last['bb_pct']

            if pct >= 1.0:
                results.append("⚠️ 突破上轨 - 超买 可能回落")
            elif pct <= 0:
                results.append("⚠️ 跌破下轨 - 超卖 可能反弹")
            elif pct > 0.8:
                results.append("⚠️ 接近上轨 - 谨慎")
            elif pct < 0.2:
                results.append("⚠️ 接近下轨 - 关注")
            else:
                results.append("➡️ 布林带中轨运行")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 布林带分析失败 - {str(e)}"

    async def _combo(self, df: pd.DataFrame, days: int) -> str:
        """组合指标分析"""
        try:
            from ta.trend import MACD
            from ta.momentum import RSIIndicator, StochasticOscillator
            from ta.volatility import BollingerBands

            df = df.tail(days + 60).copy()

            # MACD
            macd = MACD(close=df['close'], window_slow=26, window_fast=12, window_sign=9)
            df['macd_diff'] = macd.macd_diff()

            # RSI
            df['rsi'] = RSIIndicator(close=df['close'], window=12).rsi()

            # KDJ
            stoch = StochasticOscillator(high=df['high'], low=df['low'], close=df['close'], window=14, smooth_window=3)
            df['k'] = stoch.stoch() * 100
            df['d'] = stoch.stoch_signal() * 100

            # 布林带
            bb = BollingerBands(close=df['close'], window=20, window_dev=2)
            df['bb_pct'] = bb.bollinger_pband()

            df = df.tail(days)

            results = []
            results.append("=" * 50)
            results.append("📊 组合指标综合分析")
            results.append("=" * 50)

            last = df.iloc[-1]

            # 统计多方/空方信号
            bullish = 0
            bearish = 0
            signals = []

            # MACD
            if last['macd_diff'] > 0:
                bullish += 1
                signals.append("MACD: 多头")
            else:
                bearish += 1
                signals.append("MACD: 空头")

            # RSI
            if last['rsi'] > 50:
                bullish += 1
                signals.append("RSI: 多头")
            else:
                bearish += 1
                signals.append("RSI: 空头")

            # KDJ
            if last['k'] > last['d']:
                bullish += 1
                signals.append("KDJ: 金叉")
            else:
                bearish += 1
                signals.append("KDJ: 死叉")

            # 布林带
            if last['bb_pct'] > 0.5:
                bullish += 1
                signals.append("BOLL: 中上")
            else:
                bearish += 1
                signals.append("BOLL: 中下")

            for s in signals:
                results.append(f"  {s}")

            results.append("")
            results.append("=" * 50)

            if bullish >= 4:
                results.append("🔥 综合信号: 强烈看多 ({}/5)".format(bullish))
            elif bullish >= 3:
                results.append("📈 综合信号: 偏多 ({}/5)".format(bullish))
            elif bearish >= 4:
                results.append("🔻 综合信号: 强烈看空 ({}/5)".format(bearish))
            elif bearish >= 3:
                results.append("📉 综合信号: 偏空 ({}/5)".format(bearish))
            else:
                results.append("➡️ 综合信号: 中性 ({}/5)".format(bullish))

            return "\n".join(results)

        except Exception as e:
            return f"Error: 组合分析失败 - {str(e)}"

    async def _realtime_tech(self, symbol: str) -> str:
        """实时技术指标 - 从实时行情计算"""
        try:
            import akshare as ak

            code = symbol.replace(".SZ", "").replace(".SH", "")

            # 获取实时行情
            df = await asyncio.wait_for(
                asyncio.to_thread(ak.stock_zh_a_spot_em),
                timeout=30.0
            )

            stock = df[df['代码'] == code]

            if stock.empty:
                return f"未找到股票 {symbol} 的行情数据"

            stock = stock.iloc[0]

            results = []
            results.append("=" * 50)
            results.append(f"📊 {symbol} 实时技术数据")
            results.append("=" * 50)
            results.append(f"当前价格: {stock.get('最新价', 'N/A')}")
            results.append(f"涨跌幅:  {stock.get('涨跌幅', 'N/A')}%")
            results.append(f"涨跌额:  {stock.get('涨跌额', 'N/A')}")
            results.append(f"成交量:  {stock.get('成交量', 'N/A')}")
            results.append(f"成交额:  {stock.get('成交额', 'N/A')}")
            results.append(f"振幅:    {stock.get('振幅', 'N/A')}%")
            results.append(f"换手率:  {stock.get('换手率', 'N/A')}%")
            results.append(f"最高:    {stock.get('最高', 'N/A')}")
            results.append(f"最低:    {stock.get('最低', 'N/A')}")
            results.append(f"今开:    {stock.get('今开', 'N/A')}")
            results.append(f"昨收:    {stock.get('昨收', 'N/A')}")

            # 简单判断
            change = stock.get('涨跌幅', 0)
            if change and isinstance(change, (int, float)):
                if change >= 9.9:
                    results.append("")
                    results.append("⚠️ 触及涨停板")
                elif change <= -9.9:
                    results.append("")
                    results.append("⚠️ 触及跌停板")

            return "\n".join(results)

        except asyncio.TimeoutError:
            return "Error: 获取实时数据超时"
        except Exception as e:
            return f"Error: 获取实时技术数据失败 - {str(e)}"
