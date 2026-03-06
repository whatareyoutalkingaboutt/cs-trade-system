#!/usr/bin/env python3
"""
实盘策略监控系统

用途：
1. 实时统计策略触发次数
2. 跟踪当前持仓盈亏
3. 生成每日/每周绩效报告

数据表设计（需要添加到数据库）：
CREATE TABLE strategy_signals (
    id SERIAL PRIMARY KEY,
    item_id BIGINT REFERENCES items(id),
    strategy_name VARCHAR(50),
    triggered_at TIMESTAMP DEFAULT NOW(),
    entry_price DECIMAL(10,2),
    confidence DECIMAL(5,2),
    metadata JSONB
);

CREATE TABLE strategy_positions (
    id SERIAL PRIMARY KEY,
    signal_id INTEGER REFERENCES strategy_signals(id),
    item_id BIGINT REFERENCES items(id),
    strategy_name VARCHAR(50),
    entry_time TIMESTAMP,
    entry_price DECIMAL(10,2),
    current_price DECIMAL(10,2),
    exit_time TIMESTAMP,
    exit_price DECIMAL(10,2),
    exit_reason VARCHAR(50),
    actual_roi DECIMAL(10,2),
    status VARCHAR(20) DEFAULT 'holding'  -- holding, closed
);
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from loguru import logger
from sqlalchemy import func, select, and_

from backend.core.database import get_sessionmaker
from backend.core.cache import get_dragonfly_client


class StrategyMonitor:
    """实盘策略监控"""

    def __init__(self):
        self.session = get_sessionmaker()()
        self.redis = get_dragonfly_client()

    def record_signal(
        self,
        item_id: int,
        strategy_name: str,
        entry_price: float,
        confidence: float,
        metadata: Dict
    ) -> int:
        """
        记录策略触发信号
        """
        try:
            # 写入Redis（快速查询）
            signal_key = f"strategy:signal:{item_id}:{strategy_name}:{int(datetime.now().timestamp())}"
            self.redis.hmset(signal_key, {
                'item_id': item_id,
                'strategy_name': strategy_name,
                'entry_price': entry_price,
                'confidence': confidence,
                'triggered_at': datetime.now().isoformat(),
                'metadata': json.dumps(metadata)
            })
            self.redis.expire(signal_key, 86400 * 30)  # 保留30天

            # 写入PostgreSQL（持久化）
            # 这里需要实际的StrategySignal模型，简化处理
            logger.info(
                f"[信号记录] {strategy_name} | 商品ID={item_id} | "
                f"入场价={entry_price:.2f} | 置信度={confidence:.2%}"
            )

            # 返回信号ID（这里简化为时间戳）
            return int(datetime.now().timestamp())

        except Exception as e:
            logger.error(f"信号记录失败: {e}")
            return 0

    def open_position(
        self,
        signal_id: int,
        item_id: int,
        strategy_name: str,
        entry_price: float
    ) -> bool:
        """
        开仓（实际买入后调用）
        """
        try:
            position_key = f"strategy:position:{item_id}"
            self.redis.hmset(position_key, {
                'signal_id': signal_id,
                'item_id': item_id,
                'strategy_name': strategy_name,
                'entry_time': datetime.now().isoformat(),
                'entry_price': entry_price,
                'status': 'holding'
            })

            logger.info(f"[开仓] {strategy_name} | 商品ID={item_id} | 价格={entry_price:.2f}")
            return True

        except Exception as e:
            logger.error(f"开仓记录失败: {e}")
            return False

    def close_position(
        self,
        item_id: int,
        exit_price: float,
        exit_reason: str
    ) -> bool:
        """
        平仓（实际卖出后调用）
        """
        try:
            position_key = f"strategy:position:{item_id}"
            position = self.redis.hgetall(position_key)

            if not position:
                logger.warning(f"未找到持仓: {item_id}")
                return False

            entry_price = float(position['entry_price'])
            actual_roi = (exit_price * 0.975 * 0.99 - entry_price) / entry_price

            # 更新持仓状态
            self.redis.hmset(position_key, {
                'exit_time': datetime.now().isoformat(),
                'exit_price': exit_price,
                'exit_reason': exit_reason,
                'actual_roi': actual_roi * 100,
                'status': 'closed'
            })

            logger.info(
                f"[平仓] {position['strategy_name']} | 商品ID={item_id} | "
                f"收益={actual_roi*100:.2f}% | 原因={exit_reason}"
            )

            # 归档到已平仓列表
            closed_key = f"strategy:closed:{datetime.now().strftime('%Y%m%d')}"
            self.redis.rpush(closed_key, position_key)
            self.redis.expire(closed_key, 86400 * 90)  # 保留90天

            return True

        except Exception as e:
            logger.error(f"平仓记录失败: {e}")
            return False

    def get_current_positions(self) -> List[Dict]:
        """
        获取所有当前持仓
        """
        positions = []

        # 扫描所有持仓键
        for key in self.redis.scan_iter("strategy:position:*"):
            position = self.redis.hgetall(key)

            if position.get('status') == 'holding':
                positions.append({
                    'item_id': int(position['item_id']),
                    'strategy_name': position['strategy_name'],
                    'entry_time': position['entry_time'],
                    'entry_price': float(position['entry_price']),
                    'holding_days': (datetime.now() - datetime.fromisoformat(position['entry_time'])).days
                })

        return positions

    def calculate_daily_stats(self, date: str = None) -> Dict:
        """
        计算每日统计数据
        """
        if date is None:
            date = datetime.now().strftime('%Y%m%d')

        closed_key = f"strategy:closed:{date}"
        closed_positions = self.redis.lrange(closed_key, 0, -1)

        total_trades = len(closed_positions)
        total_profit = 0.0
        win_count = 0
        loss_count = 0

        strategy_breakdown = {}

        for pos_key in closed_positions:
            position = self.redis.hgetall(pos_key)

            if not position:
                continue

            roi = float(position.get('actual_roi', 0))
            strategy = position.get('strategy_name', 'unknown')

            total_profit += roi

            if roi > 0:
                win_count += 1
            else:
                loss_count += 1

            # 按策略统计
            if strategy not in strategy_breakdown:
                strategy_breakdown[strategy] = {'count': 0, 'profit': 0.0}

            strategy_breakdown[strategy]['count'] += 1
            strategy_breakdown[strategy]['profit'] += roi

        return {
            'date': date,
            'total_trades': total_trades,
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': win_count / total_trades * 100 if total_trades > 0 else 0,
            'total_profit': total_profit,
            'avg_profit': total_profit / total_trades if total_trades > 0 else 0,
            'strategy_breakdown': strategy_breakdown
        }

    def generate_daily_report(self) -> str:
        """
        生成每日报告
        """
        stats = self.calculate_daily_stats()

        report = f"""
╔═══════════════════════════════════════════════════════╗
║              📊 策略每日报告 {stats['date']}              ║
╠═══════════════════════════════════════════════════════╣

📈 总体数据
  • 总交易次数: {stats['total_trades']}
  • 胜率: {stats['win_rate']:.2f}% ({stats['win_count']}胜 / {stats['loss_count']}负)
  • 总收益: {stats['total_profit']:.2f}%
  • 平均收益: {stats['avg_profit']:.2f}%

📊 策略分解
"""

        for strategy, data in stats['strategy_breakdown'].items():
            avg = data['profit'] / data['count'] if data['count'] > 0 else 0
            report += f"  • {strategy}: {data['count']}次 | 收益{data['profit']:.2f}% | 平均{avg:.2f}%\n"

        report += "\n"

        # 当前持仓
        positions = self.get_current_positions()
        report += f"💼 当前持仓: {len(positions)} 个\n"

        for pos in positions[:5]:  # 只显示前5个
            report += f"  • {pos['strategy_name']} | 持仓{pos['holding_days']}天 | 入场¥{pos['entry_price']:.2f}\n"

        report += "\n╚═══════════════════════════════════════════════════════╝\n"

        return report

    def check_exit_signals(self) -> List[Dict]:
        """
        检查所有持仓的卖出信号
        """
        exit_alerts = []
        positions = self.get_current_positions()

        for pos in positions:
            # 获取当前价格（需要从price_history或快照获取）
            # 这里简化处理
            current_price = self._get_current_price(pos['item_id'])

            if not current_price:
                continue

            entry_price = pos['entry_price']
            holding_days = pos['holding_days']

            # 计算当前ROI
            current_roi = (current_price * 0.975 * 0.99 - entry_price) / entry_price

            # 触发卖出条件
            should_exit = False
            exit_reason = ''

            # 止盈
            if current_roi >= 0.04:  # 达到目标80%
                should_exit = True
                exit_reason = 'take_profit'

            # 止损
            elif current_roi <= -0.03:  # 亏损3%
                should_exit = True
                exit_reason = 'stop_loss'

            # 超期
            elif holding_days > 30 and current_roi < 0.02:
                should_exit = True
                exit_reason = 'timeout'

            if should_exit:
                exit_alerts.append({
                    'item_id': pos['item_id'],
                    'strategy_name': pos['strategy_name'],
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'current_roi': current_roi * 100,
                    'exit_reason': exit_reason,
                    'holding_days': holding_days
                })

        return exit_alerts

    def _get_current_price(self, item_id: int) -> Optional[float]:
        """
        获取商品当前价格（Buff求购价）
        """
        try:
            # 从Redis快照获取
            snapshot_key = f"snapshot:item:{item_id}"
            snapshot = self.redis.hgetall(snapshot_key)

            if snapshot and 'buff_buy_price' in snapshot:
                return float(snapshot['buff_buy_price'])

            return None

        except Exception as e:
            logger.error(f"获取价格失败 {item_id}: {e}")
            return None


# ========== 集成到主扫描任务 ==========

def integrate_with_arbitrage_scan():
    """
    在主套利扫描任务中集成监控系统
    """
    monitor = StrategyMonitor()

    # 示例：当策略触发时记录信号
    def on_strategy_triggered(item_id, strategy_name, entry_price, confidence, metadata):
        signal_id = monitor.record_signal(
            item_id=item_id,
            strategy_name=strategy_name,
            entry_price=entry_price,
            confidence=confidence,
            metadata=metadata
        )

        # 如果自动执行买入（需要API对接）
        # if auto_trade_enabled:
        #     success = execute_buy(item_id, entry_price)
        #     if success:
        #         monitor.open_position(signal_id, item_id, strategy_name, entry_price)

    # 示例：检查卖出信号
    exit_alerts = monitor.check_exit_signals()

    for alert in exit_alerts:
        logger.warning(f"🚨 卖出提醒: {alert['strategy_name']} | ROI={alert['current_roi']:.2f}%")

        # 如果自动执行卖出
        # if auto_trade_enabled:
        #     success = execute_sell(alert['item_id'], alert['current_price'])
        #     if success:
        #         monitor.close_position(alert['item_id'], alert['current_price'], alert['exit_reason'])

    # 生成报告
    if datetime.now().hour == 0:  # 每天0点生成日报
        report = monitor.generate_daily_report()
        logger.info(report)


if __name__ == '__main__':
    # 测试
    monitor = StrategyMonitor()
    report = monitor.generate_daily_report()
    print(report)
