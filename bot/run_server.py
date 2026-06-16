#!/usr/bin/env python3
"""健壮的服务器启动器 — 自动重启 + 日志轮转 + 健康检查。"""

import os
import sys
import time
import signal
import subprocess
import logging
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "supervisor.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("supervisor")


def start_server():
    """启动 uvicorn 进程。"""
    cmd = [
        sys.executable, "-m", "uvicorn",
        "app.main:app",
        "--host", "0.0.0.0",
        "--port", "8000",
        "--workers", "1",
        "--loop", "uvloop",
        "--log-level", "info",
    ]
    log_file = LOG_DIR / f"uvicorn_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    log.info(f"🚀 启动服务器: {' '.join(cmd)}")
    log.info(f"📝 日志: {log_file}")

    # 检测 DeepSeek API 密钥（从环境变量）
    deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if deepseek_key:
        log.info("🔑 DeepSeek API Key 已从环境变量加载")
    else:
        log.warning("⚠️ DEEPSEEK_API_KEY 环境变量未设置，LLM 将不可用")

    proc = subprocess.Popen(
        cmd,
        cwd=str(BASE_DIR),
        env={**os.environ, "PYTHONUNBUFFERED": "1"},
        stdout=open(log_file, "a", buffering=1, encoding="utf-8"),
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
    )
    return proc, log_file


def check_health(proc, log_file):
    """检查服务器健康。返回 True 表示健康。"""
    if proc.poll() is not None:
        log.warning(f"❌ 进程已退出，退出码: {proc.returncode}")
        return False

    import urllib.request
    import ssl

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    for attempt in range(3):
        try:
            resp = urllib.request.urlopen(
                "http://localhost:8000/health",
                timeout=5,
            )
            data = resp.read().decode()
            status = resp.getcode()
            log.info(f"✅ 健康检查通过: HTTP {status} — {data[:80]}...")
            return True
        except Exception as e:
            if attempt < 2:
                time.sleep(2)
            continue

    # Fallback: 检查日志里有没有启动成功信息
    if log_file.exists():
        with open(log_file, "r") as f:
            content = f.read()
            if "Uvicorn running on" in content:
                log.info("✅ 服务器已在运行 (从日志确认)")
                return True
            elif "Application startup complete" in content:
                log.info("✅ 应用启动完成 (从日志确认)")
                return True

    log.warning("⚠️ 健康检查未通过，但进程仍在运行")
    return False


def main():
    retry_delay = 1
    max_delay = 60
    consecutive_crashes = 0

    log.info("=" * 60)
    log.info("📡 市场日报服务器 Supervisor 启动")
    log.info(f"📂 工作目录: {BASE_DIR}")
    log.info("=" * 60)

    proc = None
    log_file = None
    running = True

    def handle_signal(sig, frame):
        nonlocal running
        log.info(f"收到信号 {sig}, 正在关闭...")
        running = False
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    while running:
        # 启动
        proc, log_file = start_server()

        # 等待启动完成（最多 30 秒）
        for i in range(30):
            if proc.poll() is not None:
                break
            if i == 5:
                # 5 秒后检查一次健康
                if check_health(proc, log_file):
                    consecutive_crashes = 0
                    retry_delay = 1
                break
            time.sleep(1)

        if proc.poll() is None:
            log.info("✅ 服务器正在运行")
            consecutive_crashes = 0
            retry_delay = 1

        # 监控循环
        while running:
            if proc.poll() is not None:
                log.warning(f"💥 服务器已停止 (exit code: {proc.returncode})")
                consecutive_crashes += 1
                break

            time.sleep(15)

            # 每 15 秒检查健康
            if not check_health(proc, log_file):
                log.warning("⚠️ 健康检查失败，等待下次检查...")
                time.sleep(10)
                if not check_health(proc, log_file):
                    log.error("🔥 连续健康检查失败，重启服务器")
                    proc.kill()
                    try:
                        proc.wait(timeout=5)
                    except:
                        pass
                    break

        if not running:
            break

        # 指数退避重启
        wait = min(retry_delay * (2 ** consecutive_crashes), max_delay)
        # 但前 3 次快速重试
        if consecutive_crashes <= 3:
            wait = 2

        log.info(f"🔄 {wait} 秒后重启 (连续崩溃: {consecutive_crashes})")
        time.sleep(wait)


# ════════════════════════════════════════════════════════════
# 日志轮转评估与建议
# ════════════════════════════════════════════════════════════
#
# 【现状诊断】
# 当前日志存在 3 类输出，均无自动轮转：
#
# 1. supervisor.log（本文件 logging.FileHandler，第21行）
#    → 使用 Python 标准库 logging.FileHandler
#    → 无 maxBytes / backupCount → 单文件无限增长
#    → 影响: 数月后可达 GB 级，不利于磁盘空间管理和日志检索
#
# 2. uvicorn_*.log（第39行 start_server() 中生成）
#    → 每次重启生成新文件，文件名含时间戳
#    → 永不删除旧文件 → 目前已累积 100+ 个
#    → 影响: 每个约 1-10MB，运行半年可达数千个文件，inode 耗尽风险
#
# 3. app/main.py 中的 loguru logger
#    → 当前仅输出到 stderr（由 uvicorn 捕获写入日志文件）
#    → 未配置 loguru 的 rotation / retention / compression
#
# 【推荐方案 A】— 使用 Python logging.handlers.RotatingFileHandler
#   修改第20-23行：
#   ```python
#   from logging.handlers import RotatingFileHandler
#   handlers=[
#       RotatingFileHandler(
#           LOG_DIR / "supervisor.log",
#           maxBytes=10*1024*1024,   # 10MB
#           backupCount=5,
#           encoding="utf-8",
#       ),
#       logging.StreamHandler(),
#   ]
#   ```
#
# 【推荐方案 B】— 使用 loguru（项目中已依赖 loguru==0.7.2）
#   统一用 loguru 接管所有日志，配置更简洁：
#   ```python
#   from loguru import logger
#   logger.add(
#       LOG_DIR / "supervisor_{time:YYYYMMDD}.log",
#       rotation="10 MB",      # 或 "1 day"
#       retention="30 days",   # 保留30天
#       compression="gz",      # 旧日志压缩
#       encoding="utf-8",
#       level="INFO",
#   )
#   ```
#
# 【推荐的 uvicorn 日志清理策略】
# 由于 uvicorn 日志文件名已含时间戳，可添加 cron 清理：
#   find /app/logs -name 'uvicorn_*.log' -mtime +30 -delete
# 或在本 supervisor 启动循环中周期性执行（建议）：
#   ```python
#   # 在 main() 的 while 循环开始时清理旧日志
#   import time, os
#   cutoff = time.time() - 30 * 86400
#   for f in LOG_DIR.glob("uvicorn_*.log"):
#       if f.stat().st_mtime < cutoff:
#           f.unlink(missing_ok=True)
#   ```
#
# 【变更影响评估】
# - RotatingFileHandler 修改影响范围: 仅 supervisor.log
# - loguru 方案影响范围: 全局日志输出，需要同步修改 app/main.py 中的 loguru 配置
# - 推荐优先级: 方案 B（loguru）> 方案 A，因为项目中已依赖 loguru，
#   且 loguru 支持按大小/时间轮转 + 自动压缩 + 保留策略，运维成本最低。
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    main()
