"""数据导出 Tool - 批量查询、CSV/Excel导出"""
import asyncio
import pandas as pd
from typing import Optional, List
from datetime import datetime, timedelta
import os

from nanobot.agent.tools.base import Tool


class QuantExportTool(Tool):
    """
    数据导出工具
    提供股票数据批量查询、CSV/Excel导出等功能
    """

    name = "quant_export"
    description = (
        "数据导出工具，提供股票数据批量查询、历史数据导出、CSV/Excel格式导出等功能。"
        "完成数据导出后，必须主动为用户提供更多分析："
        "1) 对比多只股票的走势差异"
        "2) 分析批量数据的统计特征（如平均涨跌幅）"
        "3) 筛选出表现最好/最差的股票"
        "4) 搜索批量股票所属行业的最新动态"
        "5) 给出初步的筛选建议供参考"
    )

    parameters = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": [
                    "batch_quote",     # 批量行情
                    "batch_history",   # 批量历史数据
                    "export_csv",      # 导出CSV
                    "export_excel",    # 导出Excel
                    "batch_info",      # 批量基本信息
                    "watchlist",       # 自选股行情
                ],
                "description": "数据类型"
            },
            "symbols": {"type": "string", "description": "股票代码列表，逗号分隔"},
            "days": {"type": "integer", "description": "查询天数，默认 30"},
            "path": {"type": "string", "description": "导出路径"},
        },
        "required": ["data_type"],
    }

    async def execute(
        self,
        data_type: str,
        symbols: Optional[str] = None,
        days: int = 30,
        path: Optional[str] = None,
        **kwargs
    ) -> str:
        """执行数据导出/批量查询"""
        try:
            if data_type == "batch_quote":
                return await self._batch_quote(symbols)
            elif data_type == "batch_history":
                return await self._batch_history(symbols, days, path)
            elif data_type == "export_csv":
                return await self._export_csv(symbols, days, path)
            elif data_type == "export_excel":
                return await self._export_excel(symbols, days, path)
            elif data_type == "batch_info":
                return await self._batch_info(symbols)
            elif data_type == "watchlist":
                return await self._watchlist(symbols)
            else:
                return f"Error: 未知数据类型 {data_type}"
        except Exception as e:
            return f"Error: 操作失败 - {str(e)}"

    async def _parse_symbols(self, symbols: str) -> List[str]:
        """解析股票代码列表"""
        if not symbols:
            return []
        # 去除空格，按逗号或分号分割
        symbols = symbols.replace(';', ',').replace('，', ',')
        return [s.strip() for s in symbols.split(',') if s.strip()]

    async def _batch_quote(self, symbols: str) -> str:
        """批量行情查询"""
        try:
            import akshare as ak

            symbol_list = await self._parse_symbols(symbols)
            if not symbol_list:
                return "请提供股票代码列表"

            # 获取全部实时行情
            df = await asyncio.wait_for(
                asyncio.to_thread(ak.stock_zh_a_spot_em),
                timeout=30.0
            )

            if df is None or df.empty:
                return "获取行情数据失败"

            results = []
            results.append("=" * 60)
            results.append(f"📊 批量行情查询 ({len(symbol_list)}只)")
            results.append("=" * 60)

            for symbol in symbol_list[:10]:  # 最多显示10只
                code = symbol.replace(".SZ", "").replace(".SH", "")
                stock = df[df['代码'] == code]

                if not stock.empty:
                    row = stock.iloc[0]
                    name = row.get('名称', symbol)
                    price = row.get('最新价', 'N/A')
                    change = row.get('涨跌幅', 'N/A')

                    results.append(f"{name}: {price} ({change}%)")
                else:
                    results.append(f"{symbol}: 未找到")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 批量行情查询失败 - {str(e)}"

    async def _batch_history(self, symbols: str, days: int, path: Optional[str]) -> str:
        """批量历史数据"""
        try:
            import akshare as ak

            symbol_list = await self._parse_symbols(symbols)
            if not symbol_list:
                return "请提供股票代码列表"

            results = []
            results.append("=" * 60)
            results.append(f"📊 批量历史数据 (最近{days}天)")
            results.append("=" * 60)

            for symbol in symbol_list[:5]:  # 限制数量
                code = symbol.replace(".SZ", "").replace(".SH", "")
                name = symbol

                try:
                    df = await asyncio.wait_for(
                        asyncio.to_thread(
                            ak.stock_zh_a_hist,
                            symbol=code,
                            period="daily",
                            start_date=(datetime.now() - timedelta(days=days)).strftime("%Y%m%d"),
                            end_date=datetime.now().strftime("%Y%m%d"),
                            adjust="qfq"
                        ),
                        timeout=30.0
                    )

                    if df is not None and not df.empty:
                        latest = df.iloc[-1]
                        close = latest.get('收盘', 'N/A')
                        change = latest.get('涨跌幅', 'N/A')
                        results.append(f"{name}: 收盘{close} 涨跌{change}%")
                    else:
                        results.append(f"{name}: 无数据")
                except Exception as e:
                    results.append(f"{name}: 获取失败")

            results.append("")
            results.append(f"提示: 共查询 {len(symbol_list)} 只股票")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 批量历史数据获取失败 - {str(e)}"

    async def _export_csv(self, symbols: str, days: int, path: Optional[str]) -> str:
        """导出CSV"""
        try:
            import akshare as ak

            symbol_list = await self._parse_symbols(symbols)
            if not symbol_list:
                return "请提供股票代码列表"

            # 默认保存路径
            if not path:
                export_dir = os.path.expanduser("~/.nanobot/exports")
            else:
                export_dir = path

            os.makedirs(export_dir, exist_ok=True)

            all_data = []

            for symbol in symbol_list:
                code = symbol.replace(".SZ", "").replace(".SH", "")

                try:
                    df = await asyncio.wait_for(
                        asyncio.to_thread(
                            ak.stock_zh_a_hist,
                            symbol=code,
                            period="daily",
                            start_date=(datetime.now() - timedelta(days=days)).strftime("%Y%m%d"),
                            end_date=datetime.now().strftime("%Y%m%d"),
                            adjust="qfq"
                        ),
                        timeout=30.0
                    )

                    if df is not None and not df.empty:
                        df['股票代码'] = symbol
                        all_data.append(df)
                except:
                    pass

            if all_data:
                combined = pd.concat(all_data, ignore_index=True)
                output_path = os.path.join(export_dir, f"stock_history_{datetime.now().strftime('%Y%m%d')}.csv")
                combined.to_csv(output_path, index=False, encoding='utf-8-sig')

                return f"✅ 已导出 {len(all_data)} 只股票的历史数据到:\n{output_path}"
            else:
                return "导出失败，无有效数据"

        except Exception as e:
            return f"Error: CSV导出失败 - {str(e)}"

    async def _export_excel(self, symbols: str, days: int, path: Optional[str]) -> str:
        """导出Excel"""
        try:
            import akshare as ak

            symbol_list = await self._parse_symbols(symbols)
            if not symbol_list:
                return "请提供股票代码列表"

            # 默认保存路径
            if not path:
                export_dir = os.path.expanduser("~/.nanobot/exports")
            else:
                export_dir = path

            os.makedirs(export_dir, exist_ok=True)

            with pd.ExcelWriter(os.path.join(export_dir, f"stock_data_{datetime.now().strftime('%Y%m%d')}.xlsx"), engine='openpyxl') as writer:
                for symbol in symbol_list[:20]:  # Excel限制
                    code = symbol.replace(".SZ", "").replace(".SH", "")

                    try:
                        df = await asyncio.wait_for(
                            asyncio.to_thread(
                                ak.stock_zh_a_hist,
                                symbol=code,
                                period="daily",
                                start_date=(datetime.now() - timedelta(days=days)).strftime("%Y%m%d"),
                                end_date=datetime.now().strftime("%Y%m%d"),
                                adjust="qfq"
                            ),
                            timeout=30.0
                        )

                        if df is not None and not df.empty:
                            sheet_name = symbol[:10]  # Excel sheet名限制
                            df.to_excel(writer, sheet_name=sheet_name, index=False)
                    except:
                        pass

            output_path = os.path.join(export_dir, f"stock_data_{datetime.now().strftime('%Y%m%d')}.xlsx")
            return f"✅ 已导出数据到:\n{output_path}"

        except Exception as e:
            return f"Error: Excel导出失败 - {str(e)}"

    async def _batch_info(self, symbols: str) -> str:
        """批量基本信息"""
        try:
            import akshare as ak

            symbol_list = await self._parse_symbols(symbols)
            if not symbol_list:
                return "请提供股票代码列表"

            results = []
            results.append("=" * 60)
            results.append(f"📊 批量基本信息 ({len(symbol_list)}只)")
            results.append("=" * 60)

            for symbol in symbol_list[:10]:
                code = symbol.replace(".SZ", "").replace(".SH", "")

                try:
                    df = await asyncio.wait_for(
                        asyncio.to_thread(ak.stock_individual_info_em, symbol=code),
                        timeout=30.0
                    )

                    if df is not None and not df.empty:
                        info = dict(zip(df['item'], df['value']))
                        name = info.get('股票简称', symbol)
                        pe = info.get('市盈率', 'N/A')
                        pb = info.get('市净率', 'N/A')

                        results.append(f"{name}: PE={pe} PB={pb}")
                    else:
                        results.append(f"{symbol}: 无数据")
                except:
                    results.append(f"{symbol}: 获取失败")

            return "\n".join(results)

        except Exception as e:
            return f"Error: 批量基本信息获取失败 - {str(e)}"

    async def _watchlist(self, symbols: str) -> str:
        """自选股行情"""
        # 自选股通常是用户自定义的列表
        if not symbols:
            return "请提供自选股代码列表"

        # 复用批量行情功能
        return await self._batch_quote(symbols)
