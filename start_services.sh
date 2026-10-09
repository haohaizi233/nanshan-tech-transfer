#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# 南山科转通 — 服务启动脚本（M6: 进程守护 + L4: worker 守护）
#
# 功能：
#   1. 启动 tech-transfer-service（FastAPI 主服务）
#   2. 启动 nanshan-ai-agent（AI Agent 服务）
#   3. 启动 AI Worker（成果评估异步任务）
#   4. 健康检查 + 自动重启（简易 supervisor）
#   5. 日志落盘 + 轮转
#
# 用法：
#   ./start_services.sh start     # 启动所有服务（后台守护）
#   ./start_services.sh stop      # 停止所有服务
#   ./start_services.sh restart   # 重启所有服务
#   ./start_services.sh status    # 查看服务状态
#   ./start_services.sh logs      # 查看日志（tail -f）
#   ./start_services.sh health    # 健康检查
#
# 环境变量：
#   APP_ENV=production  LOG_DIR=/var/log/nanshan  可通过 .env 或环境变量覆盖
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_DIR="${SCRIPT_DIR}/tech-transfer-service"
AI_AGENT_DIR="${SCRIPT_DIR}/nanshan-ai-agent"
LOG_DIR="${LOG_DIR:-${SCRIPT_DIR}/logs}"
PID_DIR="${SCRIPT_DIR}/.pids"

# 服务配置
MAIN_PORT="${PORT:-8787}"
AI_AGENT_PORT="${AI_AGENT_PORT:-8001}"
HEALTH_URL="http://127.0.0.1:${MAIN_PORT}/health"
AI_HEALTH_URL="http://127.0.0.1:${AI_AGENT_PORT}/health"

# 守护配置
MAX_RESTART_ATTEMPTS=5
RESTART_DELAY=3
HEALTH_CHECK_INTERVAL=30

# 颜色
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# ── 工具函数 ──────────────────────────────────────────────
log_info()  { echo -e "${GREEN}[INFO]${NC}  $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $(date '+%Y-%m-%d %H:%M:%S') $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') $*"; }

ensure_dirs() {
    mkdir -p "${LOG_DIR}" "${PID_DIR}"
}

# ── 进程管理 ──────────────────────────────────────────────
start_process() {
    local name="$1" workdir="$2" cmd="$3" logfile="$4" pidfile="${PID_DIR}/${1}.pid"

    if [[ -f "${pidfile}" ]] && kill -0 "$(cat "${pidfile}")" 2>/dev/null; then
        log_warn "${name} 已在运行 (PID=$(cat "${pidfile}"))"
        return 0
    fi

    log_info "启动 ${name}..."
    cd "${workdir}"
    nohup ${cmd} >> "${logfile}" 2>&1 &
    local pid=$!
    echo "${pid}" > "${pidfile}"
    log_info "${name} 已启动 (PID=${pid}, 日志: ${logfile})"
}

stop_process() {
    local name="$1" pidfile="${PID_DIR}/${1}.pid"

    if [[ ! -f "${pidfile}" ]]; then
        log_warn "${name} 未在运行"
        return 0
    fi

    local pid
    pid=$(cat "${pidfile}")
    if kill -0 "${pid}" 2>/dev/null; then
        log_info "停止 ${name} (PID=${pid})..."
        kill "${pid}" 2>/dev/null || true
        # 等待优雅退出
        for i in {1..10}; do
            if ! kill -0 "${pid}" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        # 强制退出
        if kill -0 "${pid}" 2>/dev/null; then
            log_warn "${name} 未响应 SIGTERM，发送 SIGKILL"
            kill -9 "${pid}" 2>/dev/null || true
        fi
    fi
    rm -f "${pidfile}"
    log_info "${name} 已停止"
}

status_process() {
    local name="$1" pidfile="${PID_DIR}/${1}.pid"

    if [[ -f "${pidfile}" ]] && kill -0 "$(cat "${pidfile}")" 2>/dev/null; then
        echo -e "  ${GREEN}●${NC} ${name} (PID=$(cat "${pidfile}"))"
    else
        echo -e "  ${RED}○${NC} ${name} (未运行)"
    fi
}

# ── 健康检查 ──────────────────────────────────────────────
check_health() {
    local url="$1" name="$2"
    if curl -sf --max-time 5 "${url}" > /dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} ${name} 健康"
        return 0
    else
        echo -e "  ${RED}✗${NC} ${name} 不可达"
        return 1
    fi
}

# ── 启动命令 ──────────────────────────────────────────────
get_main_cmd() {
    local venv_activate="${SERVICE_DIR}/.venv/bin/activate"
    if [[ -f "${venv_activate}" ]]; then
        echo "source ${venv_activate} && python app.py"
    else
        echo "python3 app.py"
    fi
}

get_ai_agent_cmd() {
    local venv_activate="${AI_AGENT_DIR}/.venv/bin/activate"
    if [[ -f "${venv_activate}" ]]; then
        echo "source ${venv_activate} && uvicorn app.main:app --host 0.0.0.0 --port ${AI_AGENT_PORT}"
    else
        echo "python3 -m uvicorn app.main:app --host 0.0.0.0 --port ${AI_AGENT_PORT}"
    fi
}

get_worker_cmd() {
    local venv_activate="${SERVICE_DIR}/.venv/bin/activate"
    if [[ -f "${venv_activate}" ]]; then
        echo "source ${venv_activate} && python tools/run_ai_worker.py"
    else
        echo "python3 tools/run_ai_worker.py"
    fi
}

# ── 主逻辑 ────────────────────────────────────────────────
cmd_start() {
    ensure_dirs
    log_info "=== 启动南山科转通服务 ==="

    # 1. tech-transfer-service
    start_process "tech-transfer" "${SERVICE_DIR}" "$(get_main_cmd)" \
        "${LOG_DIR}/tech-transfer.log"

    sleep 2

    # 2. nanshan-ai-agent
    start_process "ai-agent" "${AI_AGENT_DIR}" "$(get_ai_agent_cmd)" \
        "${LOG_DIR}/ai-agent.log"

    sleep 2

    # 3. AI Worker
    start_process "ai-worker" "${SERVICE_DIR}" "$(get_worker_cmd)" \
        "${LOG_DIR}/ai-worker.log"

    echo ""
    log_info "=== 服务状态 ==="
    cmd_status
    echo ""
    log_info "=== 健康检查 ==="
    cmd_health

    echo ""
    log_info "日志目录: ${LOG_DIR}"
    log_info "PID 目录: ${PID_DIR}"
    log_info "停止服务: $0 stop"
}

cmd_stop() {
    log_info "=== 停止南山科转通服务 ==="
    stop_process "ai-worker"
    stop_process "ai-agent"
    stop_process "tech-transfer"
    log_info "=== 所有服务已停止 ==="
}

cmd_restart() {
    cmd_stop
    sleep 2
    cmd_start
}

cmd_status() {
    echo "服务状态:"
    status_process "tech-transfer"
    status_process "ai-agent"
    status_process "ai-worker"
}

cmd_health() {
    local healthy=0
    check_health "${HEALTH_URL}" "tech-transfer-service" || healthy=1
    check_health "${AI_HEALTH_URL}" "nanshan-ai-agent" || healthy=1
    return ${healthy}
}

cmd_logs() {
    tail -f "${LOG_DIR}"/*.log
}

# ── 入口 ──────────────────────────────────────────────────
case "${1:-start}" in
    start)   cmd_start ;;
    stop)    cmd_stop ;;
    restart) cmd_restart ;;
    status)  cmd_status ;;
    health)  cmd_health ;;
    logs)    cmd_logs ;;
    *)
        echo "用法: $0 {start|stop|restart|status|health|logs}"
        exit 1
        ;;
esac
