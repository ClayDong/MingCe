#!/bin/bash
# 宏观市场日报机器人启动脚本
# 用法: ./start.sh [--production]

set -e

# 项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 日志目录
LOG_DIR="$SCRIPT_DIR/logs"
mkdir -p "$LOG_DIR"

# 日志文件
LOG_FILE="$LOG_DIR/market_daily_bot_$(date +%Y%m%d).log"
PID_FILE="$SCRIPT_DIR/.market_daily_bot.pid"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [INFO] $1" >> "$LOG_FILE"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [WARN] $1" >> "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [ERROR] $1" >> "$LOG_FILE"
}

# 检查 Python 版本
check_python() {
    log_info "检查 Python 版本..."
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    REQUIRED_VERSION="3.10"
    if [[ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]]; then
        log_error "需要 Python 3.10+，当前版本: $PYTHON_VERSION"
        exit 1
    fi
    log_info "Python 版本: $PYTHON_VERSION ✓"
}

# 检查虚拟环境
check_venv() {
    log_info "检查虚拟环境..."
    if [ ! -d "venv" ]; then
        log_info "创建虚拟环境..."
        python3 -m venv venv
    fi
    log_info "激活虚拟环境..."
    source venv/bin/activate
    log_info "虚拟环境准备完成 ✓"
}

# 安装依赖
install_deps() {
    log_info "检查依赖..."
    if [ -f "requirements.txt" ]; then
        # 检查是否需要安装
        pip show akshare > /dev/null 2>&1 || {
            log_info "安装依赖..."
            pip install -q -r requirements.txt
        }
        log_info "依赖检查完成 ✓"
    else
        log_error "requirements.txt 不存在"
        exit 1
    fi
}

# 检查配置文件
check_config() {
    log_info "检查配置文件..."
    
    # 检查 .env 文件
    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            log_warn ".env 文件不存在，复制 .env.example..."
            cp .env.example .env
            log_warn "请编辑 .env 文件配置飞书和 LLM 参数"
        else
            log_error ".env 文件不存在"
            exit 1
        fi
    fi
    
    # 检查关键配置
    source .env 2>/dev/null || true
    MISSING=""
    [ -z "$FEISHU_APP_ID" ] && MISSING="$MISSING FEISHU_APP_ID"
    [ -z "$FEISHU_APP_SECRET" ] && MISSING="$MISSING FEISHU_APP_SECRET"
    [ -z "$FEISHU_CHAT_ID" ] && MISSING="$MISSING FEISHU_CHAT_ID"
    
    if [ -n "$MISSING" ]; then
        log_warn "以下配置为空:$MISSING"
        log_warn "请确保在 .env 中配置完整"
    else
        log_info "配置文件检查完成 ✓"
    fi
}

# 清理旧日志
clean_old_logs() {
    log_info "清理旧日志（保留30天）..."
    find "$LOG_DIR" -name "market_daily_bot_*.log" -mtime +30 -delete 2>/dev/null || true
    log_info "日志清理完成"
}

# 停止旧进程
stop_old() {
    if [ -f "$PID_FILE" ]; then
        OLD_PID=$(cat "$PID_FILE")
        if kill -0 "$OLD_PID" 2>/dev/null; then
            log_info "停止旧进程 (PID: $OLD_PID)..."
            kill "$OLD_PID" 2>/dev/null || true
            sleep 2
            # 强制停止
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
        rm -f "$PID_FILE"
    fi
}

# 健康检查
health_check() {
    local max_attempts=30
    local attempt=1
    log_info "等待服务启动..."
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s http://localhost:8000/health > /dev/null 2>&1; then
            log_info "服务启动成功 ✓"
            return 0
        fi
        echo -n "."
        sleep 1
        attempt=$((attempt + 1))
    done
    
    log_error "服务启动超时"
    return 1
}

# 启动服务
start_service() {
    local production=$1
    
    log_info "=========================================="
    log_info "启动宏观市场日报机器人"
    log_info "=========================================="
    
    check_python
    check_venv
    install_deps
    check_config
    clean_old_logs
    stop_old
    
    log_info "启动 uvicorn 服务..."
    
    # 启动参数
    if [ "$production" = "--production" ]; then
        log_info "生产模式启动"
        nohup venv/bin/uvicorn app.main:app \
            --host 0.0.0.0 \
            --port 8000 \
            --workers 1 \
            >> "$LOG_FILE" 2>&1 &
    else
        log_info "开发模式启动"
        nohup venv/bin/uvicorn app.main:app \
            --host 0.0.0.0 \
            --port 8000 \
            --reload \
            >> "$LOG_FILE" 2>&1 &
    fi
    
    # 保存 PID
    echo $! > "$PID_FILE"
    log_info "服务 PID: $(cat $PID_FILE)"
    
    # 等待并检查
    sleep 3
    if health_check; then
        log_info "=========================================="
        log_info "服务已启动"
        log_info "API 地址: http://localhost:8000"
        log_info "API 文档: http://localhost:8000/docs"
        log_info "健康检查: http://localhost:8000/health"
        log_info "日志文件: $LOG_FILE"
        log_info "=========================================="
    else
        log_error "服务启动失败，请查看日志: $LOG_FILE"
        cat "$LOG_FILE" | tail -50
        exit 1
    fi
}

# 停止服务
stop_service() {
    log_info "停止服务..."
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            kill "$PID"
            sleep 2
            # 强制停止
            kill -9 "$PID" 2>/dev/null || true
            rm -f "$PID_FILE"
            log_info "服务已停止"
        else
            log_warn "进程不存在"
            rm -f "$PID_FILE"
        fi
    else
        log_warn "PID 文件不存在"
    fi
}

# 查看状态
status_service() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            log_info "服务运行中 (PID: $PID)"
            curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "无法获取健康状态"
        else
            log_warn "进程已停止，但 PID 文件存在"
            rm -f "$PID_FILE"
        fi
    else
        log_warn "服务未运行"
    fi
}

# 查看日志
view_logs() {
    if [ -n "$1" ]; then
        tail -f "$LOG_DIR/market_daily_bot_$1.log" 2>/dev/null || log_error "日志文件不存在: $1"
    else
        tail -f "$LOG_FILE"
    fi
}

# 主入口
case "${1:-start}" in
    start)
        start_service "$2"
        ;;
    stop)
        stop_service
        ;;
    restart)
        stop_service
        sleep 2
        start_service
        ;;
    status)
        status_service
        ;;
    logs)
        view_logs "$2"
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs}"
        echo ""
        echo "命令:"
        echo "  start         启动服务（开发模式）"
        echo "  start --production  启动服务（生产模式）"
        echo "  stop          停止服务"
        echo "  restart       重启服务"
        echo "  status        查看服务状态"
        echo "  logs [日期]   查看日志（默认今天）"
        exit 1
        ;;
esac
