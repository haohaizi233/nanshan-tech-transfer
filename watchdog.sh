#!/bin/bash
set -eo pipefail

PYTHON="/Users/mac/.pyenv/versions/py313/bin/python3"
FRPC="/opt/homebrew/bin/frpc"
FRPC_CONF="/Users/mac/Desktop/frp_0.71.0_windows_amd64/frp_0.71.0_windows_amd64/frpc.toml"
PG_ISREADY="/opt/homebrew/bin/pg_isready"
CHECK_INTERVAL=10
EXTERNAL_CHECK_INTERVAL=300  # 5分钟
LOG_DIR="/Users/mac/nanshan-logs"
mkdir -p "$LOG_DIR"

# 服务列表：name|port|workdir|cmd|health_type
SERVICES="postgres|5432|/|pg_check|pg
nanshan-backend|8787|/Users/mac/Desktop/南山小程序/tech-transfer-service|$PYTHON -m uvicorn app:app --host 127.0.0.1 --port 8787|http
nanshan-ai|8001|/Users/mac/Desktop/南山小程序/nanshan-ai-agent|$PYTHON -m uvicorn app.main:app --host 127.0.0.1 --port 8001|http
stock-api|8007|/Users/mac/Desktop/ai_stock/ai_stock/stock_api|$PYTHON -m uvicorn main:app --host 127.0.0.1 --port 8007|http"

# 外部接口列表：name|url|check_type
EXTERNAL_SERVICES="patent-api|http://43.138.138.200:8081/docs|http
external-ai|http://43.138.138.200:8588/v1/models|http|x-api-key: 8588"

# 启动服务
start_service() {
    local name=$1 port=$2 workdir=$3 cmd=$4 health_type=$5
    
    if [[ "$name" == "postgres" ]]; then
        if ! $PG_ISREADY -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
            echo "[$(date)] 启动 PostgreSQL..."
            brew services start postgresql@18 2>/dev/null || true
            sleep 3
        fi
        return
    fi
    
    if lsof -i :$port -t >/dev/null 2>&1; then return; fi
    
    # 清理残留进程（防止端口冲突）
    local old_pid
    old_pid=$(lsof -i :$port -t 2>/dev/null || true)
    if [[ -n "$old_pid" ]]; then
        echo "[$(date)] 清理残留进程: $name (PID=$old_pid)"
        kill $old_pid 2>/dev/null || true
        sleep 2
    fi
    
    echo "[$(date)] 启动 $name (port $port)..."
    cd "$workdir"
    $cmd >> "$LOG_DIR/${name}.log" 2>&1 &
    echo $! > "$LOG_DIR/${name}.pid"
    # 记录启动时间（用于宽限期检查）
    date +%s > "$LOG_DIR/${name}_start_time"
}

# 启动frp（带锁防止重复启动）
start_frpc() {
    if pgrep -x frpc >/dev/null 2>&1; then return; fi
    
    # 检查锁文件（防止并发启动）
    local lock_file="$LOG_DIR/frpc.lock"
    if [[ -f "$lock_file" ]]; then
        local lock_pid=$(cat "$lock_file" 2>/dev/null)
        if [[ -n "$lock_pid" ]] && kill -0 "$lock_pid" 2>/dev/null; then
            return  # 有其他进程正在启动frp
        fi
    fi
    
    echo $$ > "$lock_file"
    echo "[$(date)] 启动frp隧道..."
    $FRPC -c "$FRPC_CONF" >> "$LOG_DIR/frpc.log" 2>&1 &
    echo $! > "$LOG_DIR/frpc.pid"
    
    # 等待启动完成
    sleep 2
    
    # 清理锁
    rm -f "$lock_file"
}
# 健康检查（本地服务）- 添加启动宽限期
SERVICE_START_TIME_FILE="$LOG_DIR/service_start_times"

check_health() {
    local name=$1 port=$2 workdir=$3 cmd=$4 health_type=$5
    
    # PostgreSQL检查
    if [[ "$health_type" == "pg" ]]; then
        if ! $PG_ISREADY -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
            echo "[$(date)] ⚠️  PostgreSQL挂了，重启中..."
            return 1
        fi
        return 0
    fi
    
    # 启动宽限期：60秒内不检查（防止误判）
    local start_time_file="$LOG_DIR/${name}_start_time"
    if [[ -f "$start_time_file" ]]; then
        local start_time=$(cat "$start_time_file" 2>/dev/null)
        local now=$(date +%s)
        local elapsed=$((now - start_time))
        if [[ $elapsed -lt 60 ]]; then
            return 0  # 启动宽限期内，跳过检查
        fi
    fi
    
    if ! lsof -i :$port -t >/dev/null 2>&1; then
        echo "[$(date)] ⚠️  $name 挂了 (port $port)，重启中..."
        return 1
    fi
    
    # 健康检查：增加超时和连续失败阈值
    local fail_count_file="$LOG_DIR/${name}_fail_count"
    local fail_count=0
    if [[ -f "$fail_count_file" ]]; then
        fail_count=$(cat "$fail_count_file" 2>/dev/null || echo 0)
    fi
    
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" --noproxy "*" --max-time 10 "http://127.0.0.1:$port/health" 2>/dev/null || echo "000")
    if [[ "$code" != "200" ]]; then
        fail_count=$((fail_count + 1))
        echo $fail_count > "$fail_count_file"
        
        # 连续3次失败才重启（防止误判）
        if [[ $fail_count -ge 3 ]]; then
            echo "[$(date)] ⚠️  $name HTTP $code（连续${fail_count}次失败），重启中..."
            local pid
            pid=$(lsof -i :$port -t 2>/dev/null || true)
            [[ -n "$pid" ]] && kill $pid 2>/dev/null || true
            sleep 2
            echo 0 > "$fail_count_file"
            return 1
        else
            echo "[$(date)] ⚠️  $name HTTP $code（第${fail_count}次，等待重试）"
            return 0
        fi
    else
        # 成功则重置计数
        echo 0 > "$fail_count_file"
    fi
}

# 外部接口检查
check_external() {
    local name=$1 url=$2 auth_header=$3
    
    # 添加重试机制（连续3次失败才算异常）
    local fail_count_file="$LOG_DIR/external_${name}_fail_count"
    local fail_count=0
    if [[ -f "$fail_count_file" ]]; then
        fail_count=$(cat "$fail_count_file" 2>/dev/null || echo 0)
    fi
    
    local code
    if [[ -n "$auth_header" ]]; then
        code=$(curl -s -o /dev/null -w "%{http_code}" --noproxy "*" --max-time 30 -H "$auth_header" "$url" 2>/dev/null || echo "000")
    else
        code=$(curl -s -o /dev/null -w "%{http_code}" --noproxy "*" --max-time 30 "$url" 2>/dev/null || echo "000")
    fi
    
    if [[ "$code" == "200" ]] || [[ "$code" == "201" ]] || [[ "$code" == "401" ]] || [[ "$code" == "403" ]]; then
        echo "[$(date)] ✅ $name 正常 (HTTP $code)" >> "$LOG_DIR/external-api.log"
        echo 0 > "$fail_count_file"
        return 0
    else
        fail_count=$((fail_count + 1))
        echo $fail_count > "$fail_count_file"
        
        # 连续3次失败才报异常
        if [[ $fail_count -ge 3 ]]; then
            echo "[$(date)] ⚠️  $name 异常 (HTTP $code，连续${fail_count}次失败)" >> "$LOG_DIR/external-api.log"
            echo 0 > "$fail_count_file"
            return 1
        else
            echo "[$(date)] ⚠️  $name 超时 (HTTP $code，第${fail_count}次，等待重试)" >> "$LOG_DIR/external-api.log"
            return 0
        fi
    fi
}

# 外部接口监控（每5分钟）
check_external_services() {
    echo "$EXTERNAL_SERVICES" | while IFS='|' read -r name url check_type auth_header; do
        check_external "$name" "$url" "$auth_header"
    done
}

check_frpc() {
    if ! pgrep -x frpc >/dev/null 2>&1; then
        echo "[$(date)] ⚠️  frp隧道挂了，重启中..."
        return 1
    fi
}

show_status() {
    echo "=== 全部服务状态 ==="
    echo ""
    
    # PostgreSQL
    if $PG_ISREADY -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
        echo "  PostgreSQL (5432): ✅"
    else
        echo "  PostgreSQL (5432): ❌"
    fi
    
    # 本地服务
    echo "$SERVICES" | tail -n +2 | while IFS='|' read -r name port workdir cmd health_type; do
        if lsof -i :$port -t >/dev/null 2>&1; then
            echo "  $name ($port): ✅ PID=$(lsof -i :$port -t)"
        else
            echo "  $name ($port): ❌"
        fi
    done
    
    # 外部接口
    echo ""
    echo "  --- 外部接口 ---"
    echo "$EXTERNAL_SERVICES" | while IFS='|' read -r name url check_type; do
        local code
        code=$(curl -s -o /dev/null -w "%{http_code}" --noproxy "*" --max-time 5 "$url" 2>/dev/null || echo "000")
        if [[ "$code" == "200" ]] || [[ "$code" == "201" ]] || [[ "$code" == "401" ]] || [[ "$code" == "403" ]]; then
            echo "  $name: ✅ (HTTP $code)"
        else
            echo "  $name: ❌ (HTTP $code)"
        fi
    done
    
    if pgrep -x frpc >/dev/null 2>&1; then
        echo "  frp隧道: ✅"
    else
        echo "  frp隧道: ❌"
    fi
    
    if [[ -f "$LOG_DIR/watchdog.pid" ]] && kill -0 "$(cat "$LOG_DIR/watchdog.pid")" 2>/dev/null; then
        echo "  守护进程: ✅ PID=$(cat "$LOG_DIR/watchdog.pid")"
    else
        echo "  守护进程: ❌"
    fi
}

case "${1:-start}" in
    start)
        echo "[$(date)] 🔍 守护进程启动（PostgreSQL+3个服务+frp+2个外部接口）"
        echo $$ > "$LOG_DIR/watchdog.pid"
        
        # 启动所有本地服务
        echo "$SERVICES" | while IFS='|' read -r name port workdir cmd health_type; do
            start_service "$name" "$port" "$workdir" "$cmd" "$health_type"
        done
        start_frpc
        
        # 等待服务启动完成（防止误判）
        echo "[$(date)] ⏳ 等待服务启动..."
        sleep 10
        
        # 初始外部接口检查
        check_external_services
        
        external_counter=0
        
        # 监控循环
        while true; do
            # 本地服务检查（每10秒）
            echo "$SERVICES" | while IFS='|' read -r name port workdir cmd health_type; do
                check_health "$name" "$port" "$workdir" "$cmd" "$health_type" || start_service "$name" "$port" "$workdir" "$cmd" "$health_type"
            done
            check_frpc || start_frpc
            
            # 外部接口检查（每5分钟）
            external_counter=$((external_counter + 1))
            if [[ $((external_counter % 30)) -eq 0 ]]; then
                check_external_services
            fi
            
            sleep $CHECK_INTERVAL
        done
        ;;
    stop)
        echo "[$(date)] 停止守护进程..."
        [[ -f "$LOG_DIR/watchdog.pid" ]] && kill "$(cat "$LOG_DIR/watchdog.pid")" 2>/dev/null || true
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
# MySQL检查（通过brew services）
check_mysql() {
    if ! brew services list | grep mysql | grep -q "started"; then
        echo "[$(date)] ⚠️  MySQL挂了，重启中..."
        brew services start mysql 2>/dev/null || true
        return 1
    fi
    return 0
}
