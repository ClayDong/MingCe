#!/usr/bin/env python3
"""MakingMoney 整合系统 — 一键维护入口"""

import sys
import subprocess
from pathlib import Path

BASE = Path(__file__).parent
VENV = BASE / "venv" / "bin" / "python"
RELAY_API = "http://localhost:8000/api/send_message"

def cmd(*args, **kwargs):
    """运行命令并打印输出"""
    print(f"$ {' '.join(str(a) for a in args)}")
    result = subprocess.run(args, capture_output=True, text=True, cwd=str(BASE), **kwargs)
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr, file=sys.stderr)
    return result.returncode

def status():
    """查看系统状态"""
    print("=" * 50)
    print("📊 MakingMoney 系统状态")
    print("=" * 50)
    
    # 飞书通知
    import json
    try:
        import requests
        r = requests.get("http://localhost:8000/health", timeout=5)
        print(f"✅ market-daily-bot 服务器: {r.json().get('status')}")
        r2 = requests.post(RELAY_API, json={"msg_type": "text", "content": "🏥 MakingMoney 健康检查"}, timeout=10)
        print(f"✅ 飞书通知: {'正常' if r2.json().get('sent') else '失败'}")
    except Exception as e:
        print(f"❌ 飞书通知: {e}")

    # 定时任务
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
    for line in r.stdout.split("\n"):
        if "makingmoney" in line.lower():
            print(f"✅ {line.strip()}")
    
    # QLib
    r = subprocess.run([str(VENV), "-c", "from qlib_vnpy_platform.core.qlib_predictor import QLibPredictor; p=QLibPredictor(); print(f'QLib模式: {p.get_mode_name()}')"], 
                       capture_output=True, text=True, cwd=str(BASE))
    if r.returncode == 0:
        print(f"✅ {r.stdout.strip().split(chr(10))[-1]}")
    else:
        print(f"❌ QLib: {r.stderr[:100]}")

def test():
    """运行测试"""
    print("运行单元测试...")
    return cmd(str(VENV), "-m", "pytest", "tests/", "-v")

def send_report(version="close"):
    """手动推送日报"""
    print(f"手动推送 {version} 日报...")
    import requests
    r = requests.post(f"http://localhost:8000/api/report?version={version}", timeout=60)
    print(f"结果: {r.json()}")

def send_signals():
    """手动推送策略信号"""
    print("手动推送策略信号...")
    import requests
    r = requests.post(f"http://localhost:8000/api/strategy-signals/push", timeout=30)
    print(f"结果: {r.json()}")

def install():
    """安装依赖"""
    print("安装依赖...")
    return cmd(str(VENV), "-m", "pip", "install", "-r", "requirements.txt", "--timeout=30")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"用法: python {sys.argv[0]} [status|test|report|signals|install]")
        sys.exit(1)
    
    actions = {
        "status": status,
        "test": test,
        "report": lambda: send_report(sys.argv[2] if len(sys.argv) > 2 else "close"),
        "signals": send_signals,
        "install": install,
    }
    
    action = sys.argv[1]
    if action in actions:
        actions[action]()
    else:
        print(f"未知操作: {action}")
        sys.exit(1)
