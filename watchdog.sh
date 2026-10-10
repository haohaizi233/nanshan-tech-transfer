#!/usr/bin/env bash
# 南山科转通 服务守护进程
# 用法: ./watchdog.sh start|stop|status

set -euo pipefail

PROJECT_DIR="/Users/mac/Desktop/南山小程序"
PYTHON="/Users/mac/.pyenv/versions/py313/bin/python3"
BACKEND_PORT=8787
AI_AGENT_PORT=8001
CHECK_INTERVAL=10  # 秒
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"

# 进程PID文件
BACKEND_PID="$LOG_DIR/backend.pid"
AI_AGENT_PID="$LOG_DIR/ai-agent.pid"
WATCHDOG_PID="$LOG_DIR/watchdog.pid"

# 启动后端
start_backend() {
    if lsof -i :$BACKEND_PORT -t >/dev/null 2>&1; then
        echo "[$(date)] 后端已在运行 (port $BACKEND_PORT)"
        return
    fi
    echo "[$(date)] 启动后端..."
    cd "$PROJECT_DIR/tech-transfer-service"
    nohup $PYTHON -m uvicorn app:app --host 127.0.0.1 --port $BACKEND_PORT \
        > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$BACKEND_PID"
    echo "[$(date)] 后端已启动 PID=$!"
}

# 启动AI Agent
start_ai_agent() {
    if lsof -i :$AI_AGENT_PORT -t >/dev/null 2>&1; then
        echo "[$(date)] AI Agent已在运行 (port $AI_AGENT_PORT)"
        return
    fi
    echo "[$(date)] 启动AI Agent..."
    cd "$PROJECT_DIR/nanshan-ai-agent"
    nohup $PYTHON -m uvicorn app.main:app --host 127.0.0.1 --port $AI_AGENT_PORT \
        > "$LOG_DIR/ai-agent.log" 2>&1 &
    echo $! > "$AI_AGENT_PID"
    echo "[$(date)] AI Agent已启动 PID=$!"
}

# 健康检查
check_health() {
    local port=$1
    local name=$2
    local pid_file=$3
    
    # 检查端口
    if ! lsof -i :$port -t >/dev/null 2>&1; then
        echo "[$(date)] ⚠️  $name 端口 $port 无响应，重启中..."
        return 1
    fi
    
    # 检查HTTP
    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:$port/health" 2>/dev/null || echo "000")
    if [[ "$http_code" != "200" ]]; then
        echo "[$(date)] ⚠️  $name HTTP $http_code，重启中..."
        # 杀掉旧进程
        local old_pid
        old_pid=$(lsof -i :$port -t 2>/dev/null || true)
        [[ -n "$old_pid" ]] && kill $old_pid 2>/dev/null || true
        sleep 2
        return 1
    fi
    
    return 0
}

# 主循环
watchdog_loop() {
    echo "[$(date)] 🔍 守护进程启动 (间隔 ${CHECK_INTERVAL}s)"
    echo $$ > "$WATCHDOG_PID"
    
    while true; do
        # 检查后端
        if ! check_health $BACKEND_PORT "后端" "$BACKEND_PID"; then
            start_backend
        fi
        
        # 检查AI Agent
        if ! check_health $AI_AGENT_PORT "AI Agent" "$AI_AGENT_PID"; then
            start_ai_agent
        fi
        
        sleep $CHECK_INTERVAL
    done
}

# 状态
show_status() {
    echo "=== 南山科转通 服务状态 ==="
    echo ""
    if lsof -i :$BACKEND_PORT -t >/dev/null 2>&1; then
        echo "后端 (8787):    ✅ 运行中 (PID $(lsof -i :$BACKEND_PORT -t))"
    else
        echo "后端 (8787):    ❌ 未运行"
    fi
    
    if lsof -i :$AI_AGENT_PORT -t >/dev/null 2>&1; then
        echo "AI Agent (8001): ✅ 运行中 (PID $(lsof -i :$AI_AGENT_PORT -t))"
    else
        echo "AI Agent (8001): ❌ 未运行"
    fi
    
    if [[ -f "$WATCHDOG_PID" ]] && kill -0 "$(cat "$WATCHDOG_PID")" 2>/dev/null; then
        echo "守护进程:       ✅ 运行中 (PID $(cat "$WATCHDOG_PID"))"
    else
        echo "守护进程:       ❌ 未运行"
    fi
}

# 主入口
case "${1:-start}" in
    start)
        start_backend
        start_ai_agent
        watchdog_loop
        ;;
    stop)
        echo "[$(date)] 停止守护进程..."
        [[ -f "$WATCHDOG_PID" ]] && kill "$(cat "$WATCHDOG_PID")" 2>/dev/null || true
        echo "[$(date)] 守护进程已停止"
        ;;
    status)
        show_status
        ;;
    restart)
        $0 stop
        sleep 2
        $0 start
        ;;
    *)
        echo "用法: $0 {start|stop|status|restart}"
        exit 1
        ;;
esac