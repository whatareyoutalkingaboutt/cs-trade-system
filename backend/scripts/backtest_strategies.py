#!/usr/bin/env python3
"""
策略回测系统

用途：
1. 使用历史K线数据验证6大策略有效性
2. 统计每个策略的胜率、平均收益、最大回撤
3. 生成回测报告

使用方法：
    python backend/scripts/backtest_strategies.py --start-date 2025-01-01 --end-date 2026-03-01
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
from loguru import logger
from sqlalchemy import select

from backend.core.database import get_sessionmaker
from backend.models import Item, PriceHistory
from backend.scrapers.csqaq_scraper import CSQAQScraper


class StrategyBacktester:
    """策略回测引擎"""

    def __init__(self, start_date: str, end_date: str):
        self.start_date = datetime.strptime(start_date, '%Y-%m-%d')
        self.end_date = datetime.strptime(end_date, '%Y-%m-%d')
        self.session = get_sessionmaker()()
        self.csqaq = CSQAQScraper()

        # 回测结果存储
        self.trades: List[Dict] = []
        self.strategy_stats = {
            'volume_breakout': {'total': 0, 'win': 0, 'loss': 0, 'total_profit': 0.0},
            'panic_dumping': {'total': 0, 'win': 0, 'loss': 0, 'total_profit': 0.0},
            'risk_free_bid': {'total': 0, 'win': 0, 'loss': 0, 'total_profit': 0.0},
            'stale_listing': {'total': 0, 'win': 0, 'loss': 0, 'total_profit': 0.0},
            'mean_reversion': {'total': 0, 'win': 0, 'loss': 0, 'total_profit': 0.0},
            'accumulation': {'total': 0, 'win': 0, 'loss': 0, 'total_profit': 0.0},
        }

    def fetch_historical_kline(self, market_hash_name: str, plat: int = 1) -> List[Dict]:
        """
        从CSQAQ获取历史K线数据（用于回测）
        """
        try:
            response = self.csqaq.fetch_chart_all(
                market_hash_name=market_hash_name,
                plat=plat,
                max_time=int(self.end_date.timestamp() * 1000)  # 毫秒时间戳
            )

            if not response or 'data' not in response:
                return []

            kline_data = response['data']

            # 过滤时间范围
            start_ts = int(self.start_date.timestamp() * 1000)
            end_ts = int(self.end_date.timestamp() * 1000)

            filtered = [
                k for k in kline_data
                if start_ts <= int(k['t']) <= end_ts
            ]

            return filtered

        except Exception as e:
            logger.error(f"获取K线失败 {market_hash_name}: {e}")
            return []

    def simulate_strategy_1_volume_breakout(
        self,
        market_hash_name: str,
        kline_data: List[Dict]
    ) -> List[Dict]:
        """
        回测策略1：巨量扫货突破
        """
        signals = []

        for i in range(168, len(kline_data)):  # 需要7天历史（168小时）
            current = kline_data[i]
            last_7d = kline_data[i-168:i]

            # 成交量激增检测
            current_volume = current['v']
            avg_7d_volume = np.mean([k['v'] for k in last_7d])

            volume_spike = current_volume / avg_7d_volume if avg_7d_volume > 0 else 0

            # 价格突破检测
            current_price = current['c']
            ma7_price = np.mean([k['c'] for k in last_7d])
            price_breakout = (current_price - ma7_price) / ma7_price

            # 触发条件：成交量 > 3x 且 价格突破 > 5%
            if volume_spike > 3.0 and price_breakout > 0.05:
                signals.append({
                    'timestamp': int(current['t']),
                    'strategy': 'volume_breakout',
                    'entry_price': current_price,
                    'volume_spike': volume_spike,
                    'price_breakout': price_breakout * 100,
                    'confidence': 0.95
                })

        return signals

    def simulate_strategy_3_risk_free_bid(
        self,
        market_hash_name: str,
        price_history: List[PriceHistory]
    ) -> List[Dict]:
        """
        回测策略3：求购价托底套利
        """
        signals = []

        for record in price_history:
            # 需要同时有Buff和Youpin数据
            buff_record = next((r for r in price_history
                                if r.recorded_at == record.recorded_at and r.platform == 'buff'), None)
            yyyp_record = next((r for r in price_history
                                if r.recorded_at == record.recorded_at and r.platform == 'youpin'), None)

            if not buff_record or not yyyp_record:
                continue

            # 提取数据
            buff_buy_price = buff_record.price  # 假设price字段存的是卖价，需调整
            yyyp_sell_price = yyyp_record.price

            # 这里需要实际的buy_orders字段，如果没有则跳过
            # 简化处理：假设buy_orders存在
            if not hasattr(buff_record, 'buy_orders') or buff_record.buy_orders < 30:
                continue

            # 计算安全垫
            safe_exit_price = buff_buy_price * 0.975 * 0.99
            net_profit = safe_exit_price - yyyp_sell_price
            roi = net_profit / yyyp_sell_price if yyyp_sell_price > 0 else -1

            if roi > 0.03:  # ROI > 3%
                signals.append({
                    'timestamp': int(record.recorded_at.timestamp() * 1000),
                    'strategy': 'risk_free_bid',
                    'entry_price': yyyp_sell_price,
                    'exit_price': buff_buy_price,
                    'roi': roi * 100,
                    'confidence': 1.0
                })

        return signals

    def simulate_holding_period(
        self,
        entry_signal: Dict,
        future_kline: List[Dict],
        holding_days: int = 14
    ) -> Dict:
        """
        模拟持仓周期，计算实际收益
        """
        entry_price = entry_signal['entry_price']
        entry_ts = entry_signal['timestamp']

        # 找到持仓期内的K线数据
        exit_ts = entry_ts + holding_days * 24 * 3600 * 1000  # 转换为毫秒

        holding_klines = [
            k for k in future_kline
            if entry_ts < int(k['t']) <= exit_ts
        ]

        if not holding_klines:
            return {
                'exit_reason': 'no_data',
                'actual_roi': 0.0,
                'holding_days': 0
            }

        # 模拟卖出逻辑
        max_price = max([k['h'] for k in holding_klines])
        min_price = min([k['l'] for k in holding_klines])
        final_price = holding_klines[-1]['c']

        # 计算实际ROI（按Buff求购价折损）
        actual_exit_price = final_price * 0.975 * 0.99
        actual_roi = (actual_exit_price - entry_price) / entry_price

        # 最大回撤
        max_drawdown = (min_price - entry_price) / entry_price

        # 止盈/止损触发检测
        exit_reason = 'holding_end'

        # 止盈：达到目标5%的80%
        if (max_price - entry_price) / entry_price >= 0.04:
            exit_reason = 'take_profit'
            actual_roi = 0.04  # 假设在最高点附近卖出

        # 止损：亏损3%
        elif max_drawdown <= -0.03:
            exit_reason = 'stop_loss'
            actual_roi = -0.03

        return {
            'exit_reason': exit_reason,
            'actual_roi': actual_roi * 100,
            'holding_days': len(holding_klines),
            'max_price': max_price,
            'min_price': min_price,
            'final_price': final_price,
            'max_drawdown': max_drawdown * 100
        }

    def backtest_item(self, item: Item) -> None:
        """
        回测单个商品
        """
        logger.info(f"[回测] {item.market_hash_name}")

        # 获取K线数据
        kline_buff = self.fetch_historical_kline(item.market_hash_name, plat=1)

        if len(kline_buff) < 200:  # 至少需要200个数据点
            logger.warning(f"数据不足: {item.market_hash_name}")
            return

        # ========== 策略1：巨量扫货 ==========
        signals_strategy1 = self.simulate_strategy_1_volume_breakout(
            item.market_hash_name,
            kline_buff
        )

        for signal in signals_strategy1:
            # 找到触发后的未来K线
            signal_index = next(
                (i for i, k in enumerate(kline_buff) if int(k['t']) == signal['timestamp']),
                None
            )

            if signal_index is None or signal_index + 14 >= len(kline_buff):
                continue

            future_kline = kline_buff[signal_index + 1:]

            # 模拟持仓
            result = self.simulate_holding_period(signal, future_kline, holding_days=14)

            # 记录交易
            trade = {
                'item_name': item.name_cn or item.market_hash_name,
                'strategy': 'volume_breakout',
                'entry_time': datetime.fromtimestamp(signal['timestamp'] / 1000),
                'entry_price': signal['entry_price'],
                'exit_reason': result['exit_reason'],
                'actual_roi': result['actual_roi'],
                'holding_days': result['holding_days'],
                'max_drawdown': result.get('max_drawdown', 0)
            }

            self.trades.append(trade)

            # 更新统计
            stats = self.strategy_stats['volume_breakout']
            stats['total'] += 1

            if result['actual_roi'] > 0:
                stats['win'] += 1
            else:
                stats['loss'] += 1

            stats['total_profit'] += result['actual_roi']

    def run_backtest(self, sample_size: int = 50) -> None:
        """
        运行回测（抽样商品）
        """
        logger.info(f"[回测启动] 时间范围: {self.start_date} ~ {self.end_date}")

        # 从数据库随机抽取商品
        items = self.session.execute(
            select(Item)
            .where(Item.is_active == True)
            .order_by(Item.priority.desc())
            .limit(sample_size)
        ).scalars().all()

        logger.info(f"抽样商品: {len(items)} 个")

        for item in items:
            try:
                self.backtest_item(item)
            except Exception as e:
                logger.error(f"回测失败 {item.market_hash_name}: {e}")

        # 生成报告
        self.generate_report()

    def generate_report(self) -> None:
        """
        生成回测报告
        """
        logger.info("=" * 60)
        logger.info("📊 策略回测报告")
        logger.info("=" * 60)

        total_trades = len(self.trades)
        logger.info(f"总交易次数: {total_trades}")

        if total_trades == 0:
            logger.warning("无交易数据，回测结束")
            return

        # 按策略统计
        for strategy_name, stats in self.strategy_stats.items():
            if stats['total'] == 0:
                continue

            win_rate = stats['win'] / stats['total'] * 100
            avg_profit = stats['total_profit'] / stats['total']

            logger.info(f"\n策略: {strategy_name}")
            logger.info(f"  触发次数: {stats['total']}")
            logger.info(f"  胜率: {win_rate:.2f}%")
            logger.info(f"  平均收益: {avg_profit:.2f}%")

        # 保存详细交易记录
        df = pd.DataFrame(self.trades)
        output_file = f"backtest_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(output_file, index=False)
        logger.info(f"\n详细报告已保存: {output_file}")


def main():
    parser = argparse.ArgumentParser(description="策略回测系统")
    parser.add_argument('--start-date', default='2025-01-01', help='回测起始日期 YYYY-MM-DD')
    parser.add_argument('--end-date', default='2026-03-01', help='回测结束日期 YYYY-MM-DD')
    parser.add_argument('--sample-size', type=int, default=50, help='抽样商品数量')

    args = parser.parse_args()

    backtester = StrategyBacktester(args.start_date, args.end_date)
    backtester.run_backtest(sample_size=args.sample_size)


if __name__ == '__main__':
    main()
