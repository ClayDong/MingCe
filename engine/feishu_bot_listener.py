#!/usr/bin/env python3
"""
飞书机器人消息监听服务
使用 lark-cli event consume 或直接 Feishu API 监听群消息并自动回复策略查询

支持命令：
  - 报告 / report       → 立即生成并发送策略报告
  - 状态 / status       → 查看当前策略持仓情况
  - 排名 / rank         → 查看策略收益排名
  - 持仓 / holdings     → 查看当前持仓详情
  - 帮助 / help         → 显示可用命令

启动方式：
  # 方式1：使用 lark-cli（推荐，实时事件推送）
  python3 feishu_bot_listener.py

  # 方式2：使用启动脚本
  bash run_bot_listener.sh
"""
import sys
import json
import time
import threading
import subprocess
import os
import shutil
import glob as glob_module
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from daily_strategy_trade_report import DailyStrategyTradeReport
from qlib_vnpy_platform.core.sentiment_analyzer import SentimentSystem


LARK_CLI_PATHS = [
    "/Users/dong/.nvm/versions/node/v22.22.3/bin/lark-cli",
    "/Users/dong/.nvm/versions/node/v24.14.0/bin/lark-cli",
]


def find_lark_cli():
    """查找 lark-cli 可执行文件路径"""
    # 1. 检查已知路径
    for path in LARK_CLI_PATHS:
        expanded = os.path.expanduser(path)
        if os.path.isfile(expanded) and os.access(expanded, os.X_OK):
            return expanded
    # 2. 检查 PATH
    cli = shutil.which("lark-cli")
    if cli:
        return cli
    # 3. 通配符扫描 nvm 版本
    for pattern in [
        os.path.expanduser("~/.nvm/versions/node/*/bin/lark-cli"),
    ]:
        matches = glob_module.glob(pattern)
        if matches:
            return matches[0]
    return None


class FeishuBotListener:
    """飞书机器人消息监听器"""

    def __init__(self):
        self.config = self._load_config()
        self.chat_id = self.config.get("chat_id", "oc_599b2776ddd142e49fa2b22aac449c3b")
        self.running = True
        self.report_generator = DailyStrategyTradeReport(self.chat_id)
        self.lark_cli_path = find_lark_cli()
        self.sentiment_system = SentimentSystem()
        self._bot_open_id = None
        self._load_bot_info()

    def _load_bot_info(self):
        """获取机器人自身open_id用于过滤自消息"""
        try:
            import requests
            if not self.report_generator.feishu_bot.configured:
                return
            token = self.report_generator.feishu_bot._get_tenant_token()
            resp = requests.get(
                'https://open.feishu.cn/open-apis/bot/v3/info',
                headers={'Authorization': f'Bearer {token}'},
                timeout=10
            )
            data = resp.json()
            if data.get('code') == 0:
                self._bot_open_id = data.get('bot', {}).get('open_id')
                print(f"[INFO] 机器人 open_id: {self._bot_open_id}")
        except Exception as e:
            print(f"[WARN] 获取机器人信息失败: {e}")

    def _send_startup_report(self):
        """启动时发送真实策略状态报告"""
        print("[INFO] 生成启动策略状态报告...")
        try:
            data = self.report_generator.fetch_latest_data()
            if data is None or data.empty:
                self.send_message("🤖 策略监控机器人已上线，但数据获取失败\n\n输入 **帮助** 查看可用命令")
                return

            latest_price = data['close'].iloc[-1]
            results = self.report_generator.run_strategy_analysis(data)

            buy_strategies = [(k, v) for k, v in results.items() if v['signal'] == 1]
            sell_strategies = [(k, v) for k, v in results.items() if v['signal'] == -1]
            hold_count = sum(1 for r in results.values() if r['signal'] == 0)

            buy_strategies.sort(key=lambda x: x[1]['signal_strength'], reverse=True)
            sell_strategies.sort(key=lambda x: x[1]['signal_strength'], reverse=True)

            msg_lines = [
                f"🤖 **策略监控机器人已上线**\n"
                f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
                f"📊 **当前策略状态**\n"
                f"💰 比亚迪最新价: **{latest_price:.2f}** 元\n\n"
                f"🟢 买入信号: **{len(buy_strategies)}** 个策略"
            ]

            if buy_strategies[:3]:
                for k, v in buy_strategies[:3]:
                    bar = '▓' * int(v['signal_strength'] * 10) + '░' * (10 - int(v['signal_strength'] * 10))
                    msg_lines.append(f"  • {v['strategy_name']} {bar} {v['signal_strength']:.0%}")

            msg_lines.append(f"\n🔴 卖出信号: **{len(sell_strategies)}** 个策略")
            if sell_strategies[:3]:
                for k, v in sell_strategies[:3]:
                    bar = '▓' * int(v['signal_strength'] * 10) + '░' * (10 - int(v['signal_strength'] * 10))
                    msg_lines.append(f"  • {v['strategy_name']} {bar} {v['signal_strength']:.0%}")

            msg_lines.append(f"\n🟡 持有信号: **{hold_count}** 个策略")
            msg_lines.append(f"\n输入 **帮助** 查看全部命令")

            self.send_message("\n".join(msg_lines))
            print("[INFO] 启动报告已发送")
        except Exception as e:
            print(f"[ERROR] 启动报告生成失败: {e}")
            self.send_message(f"🤖 策略监控机器人已上线！\n\n输入 **帮助** 查看可用命令")

    def _load_config(self):
        config_file = Path(__file__).parent / 'feishu_config.json'
        if config_file.exists():
            with open(config_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    def _get_lark_env(self):
        """获取包含node路径的环境变量"""
        if not self.lark_cli_path:
            return None
        node_bin = os.path.dirname(self.lark_cli_path)
        node_env = os.environ.copy()
        node_env['PATH'] = node_bin + ':' + node_env.get('PATH', '')
        return node_env

    def send_message(self, content):
        """发送消息到飞书群"""
        lark_env = self._get_lark_env()
        if self.lark_cli_path and lark_env:
            try:
                result = subprocess.run(
                    [self.lark_cli_path, 'im', '+messages-send',
                     '--chat-id', self.chat_id,
                     '--markdown', content],
                    capture_output=True, text=True, timeout=30, env=lark_env
                )
                if result.returncode == 0:
                    print(f"[SEND] ✅ 消息发送成功 (via lark-cli)")
                    return True
                else:
                    err = result.stderr.strip()[:200]
                    print(f"[SEND] ⚠️ lark-cli 发送失败(code={result.returncode}): {err}")
            except FileNotFoundError:
                print("[SEND] lark-cli 可执行文件不存在")
            except subprocess.TimeoutExpired:
                print("[SEND] lark-cli 发送超时")
            except Exception as e:
                print(f"[SEND] lark-cli 异常: {e}")
        else:
            print("[SEND] lark-cli 未安装")

        # 备用：使用 FeishuBot API 直连
        if self.report_generator.feishu_bot.configured:
            success, result = self.report_generator.feishu_bot.send_message(
                self.chat_id, content, msg_type='post'
            )
            if success:
                print(f"[SEND] ✅ 消息发送成功 (via API)")
                return True
            else:
                print(f"[SEND] ❌ API 发送失败: {result}")
        else:
            print("[SEND] ❌ 飞书未配置(app_id/app_secret)，消息无法发送")

        return False

    def handle_message(self, text: str, chat_id: str, sender_name: str = ""):
        """处理接收到的消息"""
        if text.startswith('{'):
            try:
                content_obj = json.loads(text)
                text = content_obj.get('text', text)
            except (json.JSONDecodeError, TypeError):
                pass
        text = text.strip()
        print(f"\n[CMD] 收到消息 from={sender_name} chat={chat_id}: \"{text[:60]}\"")

        text_lower = text.lower()

        if text_lower in ['报告', 'report', '生成报告']:
            self.send_message("⏳ 正在生成策略报告，请稍候...")
            try:
                message, report = self.report_generator.generate_daily_report()
                if message:
                    summary = (
                        f"✅ 报告已生成并发送！\n\n"
                        f"今日操作：买入 {report.get('buy_count', 0)} 个，"
                        f"卖出 {report.get('sell_count', 0)} 个"
                    )
                    self.send_message(summary)
                else:
                    self.send_message("❌ 报告生成失败，请检查数据源")
            except Exception as e:
                self.send_message(f"❌ 生成报告失败: {str(e)[:200]}")

        elif text_lower in ['状态', 'status', '持仓状态']:
            self._send_status()

        elif text_lower in ['排名', 'rank', '收益排名']:
            self._send_ranking()

        elif text_lower in ['持仓', 'holdings', '当前持仓']:
            self._send_holdings()

        elif text_lower in ['舆情', 'sentiment', '舆情分析']:
            self._send_sentiment_analysis()

        elif text_lower in ['新闻', 'news', '最新新闻']:
            self._send_latest_news()

        elif text_lower in ['帮助', 'help', '命令', '?']:
            self._send_help()

        else:
            self.send_message(
                f"🤖 收到: \"{text[:50]}\"\n\n输入 **帮助** 查看可用命令"
            )

    def _send_status(self):
        """发送策略状态"""
        data = self.report_generator.fetch_latest_data()
        if data is None or data.empty:
            self.send_message("❌ 数据获取失败")
            return

        latest_price = data['close'].iloc[-1]
        results = self.report_generator.run_strategy_analysis(data)

        buy_count = sum(1 for r in results.values() if r['signal'] == 1)
        sell_count = sum(1 for r in results.values() if r['signal'] == -1)
        hold_count = sum(1 for r in results.values() if r['signal'] == 0)

        msg = (
            f"📊 **策略状态概览**\n"
            f"💰 比亚迪最新价: **{latest_price:.2f}** 元\n\n"
            f"🟢 买入信号: {buy_count} 个策略\n"
            f"🔴 卖出信号: {sell_count} 个策略\n"
            f"🟡 持有信号: {hold_count} 个策略\n\n"
            f"输入 **排名** 查看详细收益"
        )
        self.send_message(msg)

    def _send_ranking(self):
        """发送收益排名"""
        data = self.report_generator.fetch_latest_data()
        if data is None or data.empty:
            self.send_message("❌ 数据获取失败")
            return

        latest_price = data['close'].iloc[-1]
        results = self.report_generator.run_strategy_analysis(data)

        performance = []
        for strategy_key in self.report_generator.strategies_to_monitor:
            if strategy_key in self.report_generator.tracker.strategy_positions:
                pos = self.report_generator.tracker.strategy_positions[strategy_key]
                self.report_generator.tracker.update_position_value(strategy_key, latest_price)
                strategy_name = results.get(strategy_key, {}).get('strategy_name', strategy_key)
                performance.append({
                    'strategy': strategy_name,
                    'pnl_pct': pos.get('pnl_pct', 0),
                    'position': '持仓' if pos.get('position') == 1 else '空仓',
                })

        performance.sort(key=lambda x: x['pnl_pct'], reverse=True)

        msg = "📈 **策略收益排名**\n\n"
        if not performance:
            msg += "暂无数据\n"
        else:
            for i, p in enumerate(performance, 1):
                emoji = "🟢" if p['pnl_pct'] >= 0 else "🔴"
                msg += (
                    f"{emoji} {i:2d}. {p['strategy']:<12s}  "
                    f"收益:{p['pnl_pct']:+6.2f}%  {p['position']}\n"
                )
        self.send_message(msg)

    def _send_holdings(self):
        """发送持仓详情"""
        data = self.report_generator.fetch_latest_data()
        if data is None:
            self.send_message("❌ 数据获取失败")
            return

        latest_price = data['close'].iloc[-1]
        holdings = []

        for strategy_key in self.report_generator.strategies_to_monitor:
            if strategy_key in self.report_generator.tracker.strategy_positions:
                pos = self.report_generator.tracker.strategy_positions[strategy_key]
                self.report_generator.tracker.update_position_value(strategy_key, latest_price)
                if pos.get('position') == 1:
                    try:
                        from qlib_vnpy_platform.core.strategies import get_strategy
                        strategy_name = get_strategy(strategy_key).name
                    except Exception:
                        strategy_name = strategy_key
                    holdings.append({
                        'strategy': strategy_name,
                        'shares': pos.get('shares', 0),
                        'avg_price': pos.get('avg_price', 0),
                        'pnl_pct': pos.get('pnl_pct', 0),
                    })

        if not holdings:
            self.send_message("📋 **当前无持仓策略**\n所有策略均为空仓状态")
            return

        msg = f"📋 **当前持仓策略（共 {len(holdings)} 个）**\n\n"
        for h in holdings:
            emoji = "🟢" if h['pnl_pct'] >= 0 else "🔴"
            msg += (
                f"{emoji} **{h['strategy']}**\n"
                f"   持股: {h['shares']}股 @ {h['avg_price']:.2f}元  "
                f"盈亏: {h['pnl_pct']:+6.2f}%\n\n"
            )
        self.send_message(msg)

    def _send_help(self):
        """发送帮助信息"""
        msg = (
            "🤖 **策略监控助手 - 可用命令**\n\n"
            "📊 **报告**   — 立即生成策略报告\n"
            "📈 **排名**   — 查看策略收益排名\n"
            "📋 **持仓**   — 查看持仓策略详情\n"
            "📊 **状态**   — 查看策略信号统计\n"
            "📰 **舆情**   — 查看舆情分析报告\n"
            "📰 **新闻**   — 查看最新相关新闻\n"
            "❓ **帮助**   — 显示此帮助\n\n"
            "---\n"
            "⏰ 每天16:30自动发送日报\n"
            "💡 随时输入命令手动查询"
        )
        self.send_message(msg)

    def _send_sentiment_analysis(self):
        """发送舆情分析报告"""
        print("[CMD] 生成舆情分析报告...")
        self.send_message("⏳ 正在生成舆情分析报告，请稍候...")
        try:
            report = self.sentiment_system.run_daily_analysis()
            msg = self.sentiment_system.report_generator.format_report_for_feishu(report)
            self.send_message(msg)
        except Exception as e:
            self.send_message(f"❌ 舆情分析失败: {str(e)[:200]}")

    def _send_latest_news(self):
        """发送最新新闻"""
        print("[CMD] 获取最新新闻...")
        self.send_message("⏳ 正在获取最新新闻，请稍候...")
        try:
            news_list = self.sentiment_system.news_fetcher.fetch_stock_news('SZ002594', max_news=8)
            if not news_list:
                self.send_message("📰 暂无相关新闻")
                return
            
            msg = "📰 **比亚迪最新新闻**\n\n"
            for i, news in enumerate(news_list, 1):
                title = news.get('title', '无标题')[:60]
                pub_time = news.get('publish_time', '未知时间')
                source = news.get('source', '')
                msg += f"{i:2d}. {title}\n    📅 {pub_time}  🔗 {source}\n\n"
            
            msg += "\n输入 **舆情** 查看分析报告"
            self.send_message(msg)
        except Exception as e:
            self.send_message(f"❌ 获取新闻失败: {str(e)[:200]}")

    def run_with_lark_cli(self):
        """使用 lark-cli event consume 监听消息"""
        print("=" * 60)
        print("🤖 飞书策略监控机器人 v1.0")
        print("=" * 60)
        print(f"目标群 ChatID: {self.chat_id}")
        print(f"lark-cli 路径: {self.lark_cli_path}")
        print(f"监听方式: lark-cli event consume")
        print("=" * 60)

        # 发送启动真实策略状态报告
        self._send_startup_report()

        node_bin = os.path.dirname(self.lark_cli_path)
        node_env = os.environ.copy()
        node_env['PATH'] = node_bin + ':' + node_env.get('PATH', '')

        cmd = [
            self.lark_cli_path, 'event', 'consume', 'im.message.receive_v1',
            '--as', 'bot',
            '--jq', '{chat_id: .chat_id, text: .content, sender: .sender_id, sender_type: .sender_type, create_time: .create_time}'
        ]

        print(f"\n[INFO] 启动命令: {' '.join(cmd)}")
        print("[INFO] 等待消息...\n")

        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=node_env
        )

        # 读取 stderr（lark-cli 的日志/状态输出）
        def drain_stderr(p):
            for line in iter(p.stderr.readline, ''):
                line = line.strip()
                if line:
                    print(f"[lark-cli] {line}")

        stderr_thread = threading.Thread(target=drain_stderr, args=(proc,), daemon=True)
        stderr_thread.start()

        # 主循环 - 读取 stdout 事件流
        try:
            for line in iter(proc.stdout.readline, ''):
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                    chat_id = event.get('chat_id', '')
                    text = event.get('text', '')
                    sender = event.get('sender', '')
                    sender_type = event.get('sender_type', '')
                    if sender_type == 'bot':
                        continue
                    if self._bot_open_id and sender == self._bot_open_id:
                        continue
                    if chat_id and text:
                        self.handle_message(text, chat_id, sender)
                except json.JSONDecodeError:
                    print(f"[WARN] 无法解析事件: {line[:100]}")
                except Exception as e:
                    print(f"[ERROR] 处理事件异常: {e}")
        except KeyboardInterrupt:
            print("\n[INFO] 用户中断")
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
            print("[INFO] 监听器已停止")

    def start(self):
        """启动监听服务"""
        if self.lark_cli_path:
            self.run_with_lark_cli()
        else:
            print("=" * 60)
            print("🤖 飞书策略监控机器人")
            print("=" * 60)
            print("❌ lark-cli 未找到")
            print("请运行: npm install -g lark-cli")
            print("然后运行: lark-cli config init --new")
            print("=" * 60)


def main():
    listener = FeishuBotListener()
    listener.start()


if __name__ == "__main__":
    main()
