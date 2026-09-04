"""
南山科转通 · Multi-Runtime 前后端一键联调启动器（stdlib only）

同一份 uni-app 源码，多 Runtime 联调：

    uni-app (Vue3) ──┬── mp-weixin（微信开发者工具）──┐
                     └── H5（HBuilderX dev server）──┤
                                                    ├── FastAPI :8787 ── PostgreSQL
                                    Admin Web(未来) ─┘
                          frpc 隧道 ── 43.138.138.200:8076(API)/8077(H5)

用法：
  python start_dev.py                     # 默认全部拉起 = FastAPI + 微信 + H5 + frp 隧道（同 --all）
  python start_dev.py --all               # FastAPI + 微信 + H5 + 隧道（与默认相同）
  python start_dev.py --weixin            # FastAPI + 仅微信小程序 + 隧道
  python start_dev.py --h5                # FastAPI + 仅 H5 + 隧道
  python start_dev.py --no-tunnel         # 关闭 frp 外网隧道（纯本地联调）
  python start_dev.py --backend-only      # 仅 FastAPI（+ 隧道）
  python start_dev.py --frontend-only --weixin|h5|all   # 仅前端，不起后端
  python start_dev.py --h5 --lan          # H5 + FastAPI 局域网模式（输出 LAN 地址）
  python start_dev.py --doctor            # 环境诊断，只检测不启动
  python start_dev.py --status            # 查看运行状态，不启动
  python start_dev.py --build-h5          # H5 production build（不启动后端）
  python start_dev.py --demo              # 恢复演示模式后退出
  python start_dev.py --strict            # 严格模式：任何组件失败即退出非 0

说明：
  - HBuilderX CLI 运行 H5 / 微信均为「HBuilderX owned」进程，启动器不强制关闭它们；
    Ctrl+C 只 terminate 本启动器自己 spawn 的进程（FastAPI / frpc）。
  - 8787 已有健康的南山 FastAPI 时自动复用，退出启动器不会终止它。
  - 外网转发使用 frp（frpc.toml：serverAddr + 8076→8787 + 8077→5173），
    默认随启动器一起拉起 frpc 并做外网端到端健康验证（--no-tunnel 关闭）；
    frpc 目录检测顺序：FRPC_HOME 环境变量 > 桌面 frp* 扫描。
  - 启动器 spawn 的后端进程退出时（如崩溃）keep-alive 循环会自动重启。
"""

import argparse
import atexit
import importlib.util
import ipaddress
import json
import os
import re
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from enum import Enum
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "南山"
CONFIG_JS = FRONTEND_DIR / "common" / "config.js"
API_SERVER_DIR = ROOT.parent / "tech-transfer-service"
BACKEND_URL = "http://127.0.0.1:8787"
HEALTH_URL = BACKEND_URL + "/api/health"
API_ROOT = BACKEND_URL + "/api/tech-transfer/v1"
BACKEND_PORT = 8787
H5_PORT = 5173
H5_URL = f"http://127.0.0.1:{H5_PORT}"

HBX_CLI_DEFAULT = Path(r"D:\HBuilderX\HBuilderX.5.15.2026070915\HBuilderX\cli.exe")
HBX_ROOT_DIRS = [Path(r"D:\HBuilderX"), Path(r"C:\Program Files\HBuilderX")]
WECHAT_DEVTOOLS_DEFAULT = Path(r"D:\微信开发者工具\微信web开发者工具\cli.bat")

# frp 隧道（frpc.toml：serverAddr + [[proxies]] localPort→remotePort）
FRPC_SCAN_ROOTS = [Path.home() / "Desktop", Path("D:\\")]
TUNNEL_API_PORT = 8076   # 远端 API 入口（→ 本地 8787，实际以 frpc.toml 解析为准）
TUNNEL_H5_PORT = 8077    # 远端 H5 入口（→ 本地 5173，实际以 frpc.toml 解析为准）

DEMO_RE = re.compile(r"(USE_CAPITAL_DEMO\s*=\s*)(true|false)")


# ── 日志 ─────────────────────────────────────────────────────
def ok(msg):
    print(f"  [OK] {msg}")


def warn(msg):
    print(f"  [WARN] {msg}")


def error(msg):
    print(f"  [ERROR] {msg}")


def skip(msg):
    print(f"  [SKIP] {msg}")


# ── Runtime 模型 ─────────────────────────────────────────────
class FrontendRuntime(str, Enum):
    WEIXIN = "weixin"
    H5 = "h5"


# ── 进程生命周期 ──────────────────────────────────────────────
# 只记录「本启动器 spawn 并拥有」的进程；复用的 backend / HBuilderX GUI 不在其中
managed_processes = {}
# ask_demo_switch 修改 config.js 前保存的原值，退出时恢复
_config_js_backup = None


def register_process(key, proc):
    managed_processes[key] = proc


def restore_config_js():
    global _config_js_backup
    if _config_js_backup is None:
        return
    try:
        if CONFIG_JS.exists() and DEMO_RE.search(CONFIG_JS.read_text(encoding="utf-8")):
            return  # 用户中途手动改过，不覆盖
        CONFIG_JS.write_text(_config_js_backup, encoding="utf-8")
        print("  [OK] 已恢复 common/config.js 原始内容（USE_CAPITAL_DEMO 修改已还原）")
    except Exception as e:
        warn(f"恢复 config.js 失败：{e}")
    finally:
        _config_js_backup = None


def shutdown_managed(kill_fallback=True):
    for key, proc in list(managed_processes.items()):
        if proc.poll() is not None:
            continue
        try:
            if os.name == "nt":
                # taskkill /T 连同子进程树（vite / node watcher）一起终止；
                # 微信开发者工具不是 cli.exe 的子进程，不会被误杀
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    capture_output=True, timeout=15,
                )
            else:
                proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if kill_fallback:
                    proc.kill()
                    proc.wait(timeout=5)
            print(f"  [OK] 已停止：{key}")
        except Exception as e:
            warn(f"停止 {key} 失败：{e}")
    managed_processes.clear()
    restore_config_js()


def _on_exit():
    shutdown_managed()


def _on_sigint(signum, frame):
    print("\n收到中断信号，正在退出 ...")
    shutdown_managed()
    sys.exit(0)


def install_lifecycle_handlers():
    atexit.register(_on_exit)
    signal.signal(signal.SIGINT, _on_sigint)
    if hasattr(signal, "SIGTERM"):
        try:
            signal.signal(signal.SIGTERM, _on_sigint)
        except (ValueError, OSError):
            pass


# ── HBuilderX CLI 检测 ────────────────────────────────────────
def find_hbx_cli():
    """检测顺序：HBX_CLI 环境变量 > 默认路径 > 安装根目录扫描 > PATH。返回 (path|None, 来源)。"""
    env_val = os.environ.get("HBX_CLI", "").strip('"')
    if env_val:
        p = Path(env_val)
        if p.is_file():
            return p, "环境变量 HBX_CLI"
        warn(f"HBX_CLI={env_val} 不存在，忽略")

    if HBX_CLI_DEFAULT.is_file():
        return HBX_CLI_DEFAULT, "默认配置路径"

    candidates = []
    for root_dir in HBX_ROOT_DIRS:
        if root_dir.is_dir():
            candidates.extend(sorted(root_dir.glob("HBuilderX*/HBuilderX/cli.exe"), reverse=True))
            candidates.extend(sorted(root_dir.glob("cli.exe")))
    if candidates:
        return candidates[0], f"扫描 {candidates[0].parent.parent.parent}"

    for name in ("cli.exe", "hbx.exe", "cli"):
        found = which(name)
        if found and "hbuilderx" in found.lower():
            return Path(found), "PATH"
    return None, ""


# ── 端口 / 网络 ───────────────────────────────────────────────
def port_listening(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def port_pid(port):
    """Windows：netstat 解析监听 PID；失败返回 None（不引第三方依赖）。"""
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and f":{port}" in parts[1]:
            try:
                pid = int(parts[4])
                if pid > 0:
                    return pid
            except ValueError:
                pass
    return None


def get_lan_ips():
    """返回真实活动网卡的 IPv4 候选列表，排除 loopback / link-local，私有网段优先。"""
    ips = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ips.append(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            ips.append(s.getsockname()[0])
    except OSError:
        pass

    seen, result = set(), []
    for ip in ips:
        if ip in seen:
            continue
        seen.add(ip)
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if addr.is_loopback or addr.is_link_local:
            continue
        result.append((ip, addr))

    def is_private(ip):
        try:
            return ipaddress.ip_address(ip).is_private
        except ValueError:
            return False

    result.sort(key=lambda item: 0 if is_private(item[0]) else 1)
    return [ip for ip, _ in result]


# ── Health / 依赖 ─────────────────────────────────────────────
def fetch_health(timeout=3):
    """返回 (http_ok, data_dict)。http_ok=False 表示端口上没有 HTTP 服务。"""
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return True, body
    except urllib.error.HTTPError:
        return True, None  # 有 HTTP 响应但非 200
    except Exception:
        return False, None


def wait_backend_ready(proc, timeout=30):
    """轮询 /api/health，真正解析 JSON：区分 FastAPI Ready / PostgreSQL Unavailable。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            sys.exit("[FATAL] 后端进程异常退出，请检查上方报错（常见原因：8787 端口被占用 / PostgreSQL 未启动）")
        http_ok, body = fetch_health(timeout=2)
        if http_ok and body and isinstance(body.get("data"), dict):
            data = body["data"]
            if data.get("status") == "ok" and data.get("database") == "ok":
                ok(f"FastAPI Ready：{BACKEND_URL}")
                ok(f"PostgreSQL Ready（appUsers={data.get('appUsers')}）")
                return True
            if data.get("database") == "unavailable":
                warn("FastAPI Ready，但 PostgreSQL Unavailable：数据接口会报错")
                warn(f"  原因：{body.get('message', 'unknown')}")
                return True
        if http_ok and body is None:
            warn("FastAPI Ready（HTTP 非 200，health 异常）")
            return True
        time.sleep(0.5)
    warn(f"后端 {timeout}s 内未就绪，请手动访问 {HEALTH_URL} 确认")
    return False


def ensure_backend_deps():
    """检查 import 名（fastapi/uvicorn/psycopg2/jwt），安装以 requirements.txt 为准。"""
    missing = [m for m in ("fastapi", "uvicorn", "psycopg2", "jwt") if importlib.util.find_spec(m) is None]
    if not missing:
        ok("后端依赖已就绪（fastapi / uvicorn / psycopg2 / pyjwt）")
        return True
    print(f"  检测到缺少依赖：{', '.join(missing)}，自动安装中（依据 requirements.txt）...")
    env = os.environ.copy()
    env.setdefault("NO_PROXY", "pypi.tuna.tsinghua.edu.cn")
    env.setdefault("no_proxy", "pypi.tuna.tsinghua.edu.cn")
    ret = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(API_SERVER_DIR / "requirements.txt")],
        env=env,
    )
    if ret.returncode != 0:
        error(f"依赖安装失败，请手动执行：pip install -r {API_SERVER_DIR / 'requirements.txt'}")
        return False
    ok("依赖安装完成")
    return True


def check_db_config():
    """PostgreSQL 连通性检查（tech_transfer，与后端 config.py 同源：DB_* 环境变量 + 同默认值）。"""
    cfg = {
        "host": os.environ.get("DB_HOST", "127.0.0.1"),
        "port": int(os.environ.get("DB_PORT", "5432")),
        "user": os.environ.get("DB_USER", "postgres"),
        "password": os.environ.get("DB_PASSWORD", "postgres123"),
        "dbname": os.environ.get("DB_NAME", "tech_transfer"),
    }
    try:
        import psycopg2

        conn = psycopg2.connect(connect_timeout=3, **cfg)
        conn.close()
        ok(f"PostgreSQL 连接正常（{cfg['dbname']}@{cfg['host']}:{cfg['port']}）")
        return True
    except ImportError:
        warn("psycopg2 未安装（启动器无法预检数据库；后端启动时会再次校验）")
        return False
    except Exception as e:
        warn(f"PostgreSQL 连接失败：{e}")
        warn("    请确认 postgresql-x64-17 服务已启动（后端仍会启动，但接口会报错）")
        return False


# ── 8787 端口三分支 ───────────────────────────────────────────
def resolve_backend(lan):
    """返回 (proc|None)。proc=None 表示复用已有后端。"""
    if not port_listening(BACKEND_PORT):
        return start_backend(lan)

    http_ok, body = fetch_health()
    if http_ok and body and isinstance(body.get("data"), dict) and body["data"].get("status") in ("ok", "degraded"):
        ok(f"检测到现有 FastAPI :{BACKEND_PORT}，直接复用")
        if body["data"].get("database") == "ok":
            ok(f"PostgreSQL Ready（appUsers={body['data'].get('appUsers')}）")
        else:
            warn("PostgreSQL Unavailable（现有后端）")
        return None

    pid = port_pid(BACKEND_PORT)
    pid_desc = f"（PID={pid}）" if pid else "（PID 未知）"
    error(f"端口 {BACKEND_PORT} 已被非南山后端进程占用 {pid_desc}")
    error(f"  health 探测未返回南山 FastAPI 特征（{HEALTH_URL}）")
    error("  请手动排查：netstat -ano | findstr :8787")
    sys.exit(1)


def start_backend(lan):
    host = "0.0.0.0" if lan else "127.0.0.1"
    print(f"  启动中：FastAPI（uvicorn）→ http://{host}:{BACKEND_PORT}")
    env = os.environ.copy()
    env.setdefault("APP_ENV", "local")
    env.setdefault("HOST_MODE", "local")
    env.setdefault("AUTH_PROVIDER", "mock")
    proc = subprocess.Popen([sys.executable, "-u", "app.py"], cwd=API_SERVER_DIR, env=env)
    register_process("backend", proc)
    if not wait_backend_ready(proc):
        error("后端未就绪")
        sys.exit(1)
    return proc


# ── config.js（Demo 开关） ────────────────────────────────────
def read_config_js():
    return CONFIG_JS.read_text(encoding="utf-8")


def set_demo_flag(text, value):
    return DEMO_RE.sub(lambda m: m.group(1) + value, text, count=1)


def get_demo_flag():
    m = DEMO_RE.search(read_config_js())
    return m.group(2) == "true" if m else None


def ask_demo_switch():
    """USE_CAPITAL_DEMO 只影响资本对接模块（common/capital.js 消费），不改其它接口行为。"""
    if get_demo_flag() is not True:
        ok("前端已处于联调模式（USE_CAPITAL_DEMO = false）")
        return
    print("  [WARN] 当前为演示模式（USE_CAPITAL_DEMO = true），资本对接模块不会请求后端")
    try:
        ans = input("  是否自动改为 false 进行前后端联调？[y/N] ").strip().lower()
    except EOFError:
        ans = ""
    if ans == "y":
        global _config_js_backup
        _config_js_backup = read_config_js()
        CONFIG_JS.write_text(set_demo_flag(read_config_js(), "false"), encoding="utf-8")
        print("  [OK] 已改为联调模式（退出启动器时自动恢复原值；恢复演示模式：python start_dev.py --demo）")
    else:
        print("  保留演示模式：本次后端仍会启动，但资本对接读的是本地演示数据")


# ── CLI watch 进程派生（launch 命令均为阻塞式 watch 模式） ────
def spawn_cli_watch(args_list, ready_markers):
    """Popen HBuilderX CLI 并回显输出；返回 (proc, ready_event, reader_thread)。

    cli launch web / mp-weixin 都是 watch 模式：进程会一直驻留（热编译），
    必须用 Popen 派生而非阻塞 subprocess.run，启动器才能继续执行后续步骤。
    """
    proc = subprocess.Popen(
        args_list,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    ready = threading.Event()

    def reader():
        try:
            for line in proc.stdout:
                print(line, end="")
                if any(m in line for m in ready_markers):
                    ready.set()
        except Exception:
            pass

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    return proc, ready, thread


# ── 微信 Runtime ─────────────────────────────────────────────
def run_weixin(hbx_cli):
    print("  调用 HBuilderX 编译并运行到微信开发者工具 ...")
    proc, ready, _ = spawn_cli_watch(
        [str(hbx_cli), "launch", "mp-weixin", "--project", str(FRONTEND_DIR)],
        ready_markers=["微信开发者工具已启动", "ready in"],
    )
    register_process("weixin", proc)
    if ready.wait(timeout=180):
        ok("微信小程序 Runtime 已启动（微信开发者工具，watch 模式热编译）")
        return True
    if proc.poll() is not None:
        error("HBuilderX 编译失败（微信 Runtime），请检查上方输出")
        error("      常见原因：微信开发者工具未开启「服务端口」（设置 → 安全设置）")
        return False
    warn("微信 Runtime 180s 内未观测到「已启动」标志，请查看微信开发者工具窗口确认")
    return True


# ── H5 Runtime ───────────────────────────────────────────────
def run_h5(hbx_cli, lan):
    print("  调用 HBuilderX 编译并运行 H5 dev server ...")
    print(f"  H5 dev 端口：{H5_PORT}（manifest.json h5.devServer.port）")
    if port_listening(H5_PORT):
        ok(f"检测到 {H5_URL} 已在运行，复用现有 H5 dev server")
        return True

    proc, _, _ = spawn_cli_watch(
        [str(hbx_cli), "launch", "web", "--project", str(FRONTEND_DIR)],
        ready_markers=[],
    )
    register_process("h5", proc)

    if not wait_h5_ready():
        if proc.poll() is not None:
            error("HBuilderX H5 启动失败（进程已退出），请检查上方输出")
        else:
            error(f"H5 dev server 在 {H5_URL} 上未就绪（进程可能仍在编译，请手动访问确认）")
        return False

    ok(f"H5 已就绪：{H5_URL}")
    lan_ips = get_lan_ips()
    if lan:
        print("  局域网访问：")
        for ip in lan_ips[:3]:
            print(f"    http://{ip}:{H5_PORT}")
    elif lan_ips:
        print(f"  局域网访问：http://{lan_ips[0]}:{H5_PORT}（完整列表用 --lan 查看）")
    return True


def wait_h5_ready(timeout=300):
    """轮询 H5 dev server 首页直到 HTTP 200（process started ≠ service ready）。

    首次冷编译（HBuilderX 全量 build）实测可达 1-3 分钟，超时必须远大于此，
    否则会误杀仍在编译的 watch 进程（热编译后再次启动仅数秒）。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_listening(H5_PORT):
            try:
                with urllib.request.urlopen(H5_URL, timeout=2) as resp:
                    if resp.status == 200:
                        return True
            except urllib.error.HTTPError:
                return True  # 有 HTTP 响应即可（dev server 对 / 可能返回非 200）
            except Exception:
                pass
        time.sleep(1)
    return False


# ── frp 隧道（--tunnel） ─────────────────────────────────────
def find_frpc():
    """检测 frpc 目录（须含 frpc.exe + frpc.toml）。

    顺序：FRPC_HOME 环境变量 > 桌面/D 盘 frp* 目录扫描（两层嵌套均尝试）。
    返回 (frpc_exe|None, frpc_toml|None, 来源)。
    """
    env_val = os.environ.get("FRPC_HOME", "").strip('"')
    if env_val:
        root = Path(env_val)
        if (root / "frpc.exe").is_file() and (root / "frpc.toml").is_file():
            return root / "frpc.exe", root / "frpc.toml", "环境变量 FRPC_HOME"
        warn(f"FRPC_HOME={env_val} 缺少 frpc.exe / frpc.toml，忽略")

    for scan_root in FRPC_SCAN_ROOTS:
        if not scan_root.is_dir():
            continue
        for d in sorted(scan_root.glob("frp*")):
            for sub in [d] + list(d.glob("frp*")):
                if (sub / "frpc.exe").is_file() and (sub / "frpc.toml").is_file():
                    return sub / "frpc.exe", sub / "frpc.toml", f"扫描 {sub}"
    return None, None, ""


def parse_frpc_config(toml_path):
    """极简解析 frpc.toml（只取 serverAddr 与 proxies 的 localPort→remotePort 映射）。

    返回 (server_addr|None, {local_port: remote_port})。
    """
    text = toml_path.read_text(encoding="utf-8")
    m = re.search(r'serverAddr\s*=\s*"([^"]+)"', text)
    server = m.group(1) if m else None
    pairs = {}
    for block in re.finditer(r"\[\[proxies\]\](.*?)(?=\n\[\[|\Z)", text, re.S):
        lp = re.search(r"localPort\s*=\s*(\d+)", block.group(1))
        rp = re.search(r"remotePort\s*=\s*(\d+)", block.group(1))
        if lp and rp:
            pairs[int(lp.group(1))] = int(rp.group(1))
    return server, pairs


def _no_proxy_opener():
    """外网请求绕过系统代理（Clash 会拦截直连 IP 的 HTTP）。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_url_status(url, timeout=4):
    """返回 (reachable, http_status)。reachable=False 表示连不上/被重置。"""
    try:
        with _no_proxy_opener().open(url, timeout=timeout) as resp:
            return True, resp.status
    except urllib.error.HTTPError as e:
        return True, e.code
    except Exception:
        return False, None


def tunnel_api_healthy(server, api_remote_port, timeout=4):
    """通过外网隧道请求 /api/health，返回 (healthy, body)。"""
    url = f"http://{server}:{api_remote_port}/api/health"
    try:
        with _no_proxy_opener().open(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("code") == 0, body
    except Exception:
        return False, None


def frpc_process_running():
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq frpc.exe"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return False
    return "frpc.exe" in out.lower()


def spawn_frpc(frpc_exe, frpc_toml):
    """拉起 frpc 并注册为启动器托管进程（Ctrl+C 时一并终止）。

    frpc 须直连 frps（43.138.138.200:7000），不能走本机系统代理（mihomo / clash-verge
    等），否则代理节点/规则一变隧道即中断。这里清除代理环境变量，确保 frpc 直连。
    """
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    proc = subprocess.Popen(
        [str(frpc_exe), "-c", str(frpc_toml)],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        env=env,
    )
    register_process("tunnel", proc)
    return proc


def run_tunnel():
    """启动 frpc 并做外网端到端验证。返回 (True/False, tunnel_info|None)。

    复用条件：隧道 API 入口已健康（无论 frpc 是谁启动的）。
    验证标准：GET http://{server}:{api_remote}/api/health 返回 code=0。
    frpc 已在运行但隧道暂不健康时（本地后端刚启动/未启动）等待恢复，不重复拉起。
    """
    frpc_exe, frpc_toml, source = find_frpc()
    if frpc_exe is None:
        error("未找到 frpc（需含 frpc.exe + frpc.toml 的目录；可设置 FRPC_HOME 环境变量）")
        return False, None
    ok(f"frpc：{frpc_exe}（{source}）")

    server, pairs = parse_frpc_config(frpc_toml)
    if not server or BACKEND_PORT not in pairs:
        error(f"frpc.toml 缺少 serverAddr 或 {BACKEND_PORT} 的代理映射，无法建隧道")
        return False, None
    api_remote = pairs[BACKEND_PORT]
    h5_remote = pairs.get(H5_PORT)
    api_tunnel = f"http://{server}:{api_remote}"
    h5_tunnel = f"http://{server}:{h5_remote}" if h5_remote else None
    info = {"server": server, "pairs": pairs, "frpc_exe": frpc_exe,
            "frpc_toml": frpc_toml, "api_tunnel": api_tunnel, "h5_tunnel": h5_tunnel}

    healthy, body = tunnel_api_healthy(server, api_remote)
    if healthy:
        ok(f"检测到隧道已就绪，复用现有 frpc：{api_tunnel}")
        if h5_tunnel:
            print(f"  H5 外网入口：{h5_tunnel}")
        return True, info

    if frpc_process_running():
        # frpc 在跑但隧道暂不健康：多半是本地后端未就绪，等待恢复而非重复拉起
        for _ in range(10):
            healthy, _body = tunnel_api_healthy(server, api_remote)
            if healthy:
                ok(f"隧道已恢复健康，复用现有 frpc：{api_tunnel}")
                if h5_tunnel:
                    print(f"  H5 外网入口：{h5_tunnel}")
                return True, info
            time.sleep(1)
        warn(f"frpc 进程在运行但 {api_tunnel} 10s 内未恢复健康（本地后端未启动？），跳过隧道")
        return False, None

    mappings = f"{BACKEND_PORT}→{api_remote}"
    if h5_remote:
        mappings += f"，{H5_PORT}→{h5_remote}"
    print(f"  启动 frpc（{server}）：{mappings}")
    spawn_frpc(frpc_exe, frpc_toml)

    deadline = time.time() + 30
    while time.time() < deadline:
        proc = managed_processes.get("tunnel")
        if proc is not None and proc.poll() is not None:
            error("frpc 进程异常退出（常见原因：auth.token 失效 / 服务器不可达 / 远端端口被占）")
            return False, None
        healthy, body = tunnel_api_healthy(server, api_remote)
        if healthy:
            ok(f"隧道已就绪：{api_tunnel}/api/health")
            if h5_tunnel:
                print(f"  H5 外网入口：{h5_tunnel}（需 H5 dev server 运行中）")
            return True, info
        time.sleep(1)
    error(f"frpc 已启动但 {api_tunnel} 30s 内未通过健康检查")
    return False, None


# ── Doctor / Status ───────────────────────────────────────────
def run_doctor():
    print("=" * 60)
    print(" Doctor 模式（只检测，不启动）")
    print("=" * 60)
    results = []

    def check(name, passed, detail="", fatal=False):
        tag = "PASS" if passed else ("FAIL" if fatal else "WARN")
        results.append((tag, name))
        print(f"  [{tag}] {name}" + (f" — {detail}" if detail else ""))

    check("Python", sys.version_info >= (3, 10), sys.version.split()[0], fatal=True)

    for mod, pkg in (("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("psycopg2", "psycopg2-binary"), ("jwt", "PyJWT")):
        has = importlib.util.find_spec(mod) is not None
        check(f"后端依赖 {pkg}", has, "" if has else f"import {mod} 失败（pip install {pkg}）")

    for f in ("manifest.json", "pages.json", "common/config.js", "main.js", "App.vue"):
        check(f"前端 {f}", (FRONTEND_DIR / f).exists(), str(FRONTEND_DIR / f))
    manifest = FRONTEND_DIR / "manifest.json"
    if manifest.exists():
        text = manifest.read_text(encoding="utf-8")
        check("manifest h5.devServer.port", f'"port" : {H5_PORT}' in text, f"应为 {H5_PORT}")

    hbx, source = find_hbx_cli()
    check("HBuilderX CLI", hbx is not None, f"{hbx}（{source}）" if hbx else "未找到，请设置 HBX_CLI 环境变量")
    check("H5 构建方式", True, "纯 HBuilderX 工程（无 package.json），H5 dev server 由 HBuilderX 内置提供")

    check("微信开发者工具 CLI", WECHAT_DEVTOOLS_DEFAULT.exists(), str(WECHAT_DEVTOOLS_DEFAULT))

    frpc_exe, frpc_toml, frpc_source = find_frpc()
    check("frpc（外网隧道）", frpc_exe is not None,
          f"{frpc_toml}（{frpc_source}）" if frpc_exe else "未找到（不影响本地联调，仅外网隧道需要）")
    if frpc_toml:
        server, pairs = parse_frpc_config(frpc_toml)
        mapping_detail = "缺少 serverAddr / 8787 映射"
        if server and pairs:
            mapping_detail = f"{server}，" + "，".join(f"{lp}→{rp}" for lp, rp in sorted(pairs.items()))
        check("frpc.toml 代理映射", bool(server) and BACKEND_PORT in pairs, mapping_detail)

    try:
        import psycopg2

        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DB_PORT", "5432")),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres123"),
            dbname=os.environ.get("DB_NAME", "tech_transfer"),
            connect_timeout=3,
        )
        conn.close()
        check("PostgreSQL 连通", True, "tech_transfer")
    except Exception as e:
        check("PostgreSQL 连通", False, str(e))

    listening = port_listening(BACKEND_PORT)
    health_ok, body = fetch_health(timeout=2)
    if listening and health_ok and body and isinstance(body.get("data"), dict):
        check(f"端口 {BACKEND_PORT}", True, f"健康后端占用（复用，status={body['data'].get('status')}）")
    elif listening:
        check(f"端口 {BACKEND_PORT}", False, f"被未知进程占用（PID={port_pid(BACKEND_PORT)}）", fatal=True)
    else:
        check(f"端口 {BACKEND_PORT}", True, "空闲")

    check(f"H5 端口 {H5_PORT}", not port_listening(H5_PORT),
          "空闲" if not port_listening(H5_PORT) else "已被占用（启动时将复用）")

    if health_ok and body and isinstance(body.get("data"), dict):
        check("FastAPI /api/health", True, f"status={body['data'].get('status')}, database={body['data'].get('database')}")
    else:
        check("FastAPI /api/health", False, f"未运行（{HEALTH_URL}）")

    print()
    fails = [r for r in results if r[0] == "FAIL"]
    warns = [r for r in results if r[0] == "WARN"]
    print(f"结果：{len(results) - len(fails) - len(warns)} PASS / {len(warns)} WARN / {len(fails)} FAIL")
    return len(fails) == 0


def run_status():
    print("=" * 60)
    print(" Status 模式（只查看，不启动）")
    print("=" * 60)
    http_ok, body = fetch_health(timeout=2)
    if http_ok and body and isinstance(body.get("data"), dict):
        d = body["data"]
        print(f"  FastAPI     RUNNING  {BACKEND_URL}（status={d.get('status')}, database={d.get('database')}）")
    elif port_listening(BACKEND_PORT):
        print(f"  FastAPI     UNKNOWN  {BACKEND_PORT} 被占用但非南山后端（PID={port_pid(BACKEND_PORT)}）")
    else:
        print(f"  FastAPI     STOPPED  {BACKEND_URL}")

    if port_listening(H5_PORT):
        try:
            with urllib.request.urlopen(H5_URL, timeout=2) as resp:
                print(f"  H5          RUNNING  {H5_URL}（HTTP {resp.status}）")
        except Exception:
            print(f"  H5          RUNNING  {H5_URL}（端口监听中）")
    else:
        print(f"  H5          STOPPED  {H5_URL}")

    try:
        import psycopg2

        conn = psycopg2.connect(
            host=os.environ.get("DB_HOST", "127.0.0.1"),
            port=int(os.environ.get("DB_PORT", "5432")),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres123"),
            dbname=os.environ.get("DB_NAME", "tech_transfer"),
            connect_timeout=3,
        )
        conn.close()
        print("  PostgreSQL  RUNNING  tech_transfer 可连接")
    except Exception as e:
        print(f"  PostgreSQL  DOWN     {e}")

    frpc_exe, frpc_toml, _ = find_frpc()
    if frpc_exe is None:
        print("  Tunnel      N/A      未找到 frpc（--tunnel 不可用）")
        return True
    server, pairs = parse_frpc_config(frpc_toml)
    if not server or BACKEND_PORT not in pairs:
        print("  Tunnel      N/A      frpc.toml 解析失败（缺 serverAddr / 8787 映射）")
        return True
    api_tunnel = f"http://{server}:{pairs[BACKEND_PORT]}"
    healthy, _body = tunnel_api_healthy(server, pairs[BACKEND_PORT], timeout=4)
    if healthy:
        print(f"  Tunnel      RUNNING  {api_tunnel}（外网 API 入口健康）")
    elif frpc_process_running():
        print(f"  Tunnel      DEGRADED frpc 进程在跑但 {api_tunnel} 不健康（本地后端未启动？）")
    else:
        print("  Tunnel      STOPPED  frpc 未运行（start_dev.py 默认随启动器拉起）")
    if H5_PORT in pairs:
        h5_tunnel = f"http://{server}:{pairs[H5_PORT]}"
        reachable, st = fetch_url_status(h5_tunnel, timeout=4)
        if reachable and st == 200:
            print(f"  Tunnel(H5)  RUNNING  {h5_tunnel}")
        else:
            print(f"  Tunnel(H5)  OFF      {h5_tunnel}（需 H5 dev server + 隧道运行中）")
    return True


# ── H5 生产构建 ───────────────────────────────────────────────
def run_build_h5(hbx_cli):
    print("  执行 H5 production build（HBuilderX publish web）...")
    ret = subprocess.run(
        [str(hbx_cli), "publish", "web", "--project", str(FRONTEND_DIR)]
    )
    if ret.returncode != 0:
        error("H5 production build 失败，请检查上方输出")
        return False

    dist_candidates = [
        FRONTEND_DIR / "unpackage" / "dist" / "build" / "h5",
        FRONTEND_DIR / "unpackage" / "build" / "h5",
    ]
    dist = next((d for d in dist_candidates if d.is_dir()), None)
    if dist is None or not (dist / "index.html").exists():
        error("未找到 H5 构建输出（预期含 index.html 的 dist/build/h5）")
        for d in dist_candidates:
            print(f"      检查过：{d}")
        return False
    ok("H5 Production Build 完成")
    print(f"  Output:\n    {dist}")
    print(f"    index.html: {'存在' if (dist / 'index.html').is_file() else '缺失'}")
    return (dist / "index.html").is_file()


# ── 汇总面板 ──────────────────────────────────────────────────
def print_summary(runtimes, lan, tunnel_urls=None):
    lan_ips = get_lan_ips()
    print()
    print("=" * 60)
    print(" 南山科转通 · Multi-Runtime Dev Launcher")
    print("=" * 60)
    print("Environment")
    print(f"  APP_ENV       {os.environ.get('APP_ENV', 'local')}")
    print(f"  HOST_MODE     {os.environ.get('HOST_MODE', 'local')}")
    print(f"  AUTH_PROVIDER {os.environ.get('AUTH_PROVIDER', 'mock')}")
    print()
    print("Backend")
    print(f"  FastAPI       {BACKEND_URL}")
    print(f"  Health        {HEALTH_URL}")
    print(f"  API Root      {API_ROOT}")
    if lan and lan_ips:
        print(f"  FastAPI (LAN) http://{lan_ips[0]}:{BACKEND_PORT}")
    print()
    print("Frontend")
    print(f"  Source        {FRONTEND_DIR}")
    print()
    print("Runtime")
    print(f"  WeChat        {'ENABLED' if FrontendRuntime.WEIXIN in runtimes else 'OFF'}")
    print(f"  H5            {'ENABLED' if FrontendRuntime.H5 in runtimes else 'OFF'}")
    if FrontendRuntime.H5 in runtimes:
        print()
        print("H5")
        print(f"  Local         {H5_URL}")
        if lan_ips:
            print(f"  LAN           http://{lan_ips[0]}:{H5_PORT}")
    if tunnel_urls:
        print()
        print("Tunnel（外网入口，经 frp 转发本机）")
        for label, url in tunnel_urls:
            print(f"  {label:13} {url}")
    print()
    print("真机调试（微信小程序，改 config/local.env.js 的 API_BASE）：")
    print("  模拟器/本地  http://127.0.0.1:8787（默认，无需修改）")
    if lan_ips:
        print(f"  同一 WiFi    http://{lan_ips[0]}:{BACKEND_PORT}")
    api_tunnel_url = next((u for label, u in tunnel_urls if label == "API"), None) if tunnel_urls else None
    if api_tunnel_url:
        print(f"  外网（frp）  {api_tunnel_url}")
    print("=" * 60)


# ── 主流程 ────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="南山科转通 Multi-Runtime 前后端一键联调启动器")
    parser.add_argument("--backend-only", action="store_true", help="只启动 FastAPI 后端")
    parser.add_argument("--frontend-only", action="store_true", help="只启动前端 Runtime（配合 --weixin/--h5/--all）")
    parser.add_argument("--weixin", action="store_true", help="FastAPI + 微信小程序 Runtime")
    parser.add_argument("--h5", action="store_true", help="FastAPI + H5 Runtime")
    parser.add_argument("--all", action="store_true", help="FastAPI + 微信 + H5")
    parser.add_argument("--tunnel", dest="tunnel", action="store_true", default=True,
                        help="启动 frpc 外网隧道（默认开启；frpc.toml：8076→8787 / 8077→5173）并做端到端健康验证")
    parser.add_argument("--no-tunnel", dest="tunnel", action="store_false",
                        help="不启动 frp 外网隧道（纯本地联调）")
    parser.add_argument("--lan", action="store_true", help="局域网模式：FastAPI 绑定 0.0.0.0，输出 LAN 地址")
    parser.add_argument("--doctor", action="store_true", help="环境诊断，只检测不启动")
    parser.add_argument("--status", action="store_true", help="查看当前运行状态，不启动")
    parser.add_argument("--build-h5", action="store_true", help="H5 production build（不启动 FastAPI）")
    parser.add_argument("--demo", action="store_true", help="恢复演示模式(USE_CAPITAL_DEMO=true)后退出")
    parser.add_argument("--strict", action="store_true", help="严格模式：任何组件失败即退出非 0")
    return parser.parse_args()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

    args = parse_args()

    if args.demo:
        CONFIG_JS.write_text(set_demo_flag(read_config_js(), "true"), encoding="utf-8")
        print("[OK] 已恢复演示模式（USE_CAPITAL_DEMO = true）")
        return 0

    if args.doctor:
        return 0 if run_doctor() else 1

    if args.status:
        run_status()
        return 0

    if args.build_h5:
        hbx_cli, source = find_hbx_cli()
        if hbx_cli is None:
            error("未找到 HBuilderX CLI（可设置 HBX_CLI 环境变量）")
            return 1
        ok(f"HBuilderX CLI：{hbx_cli}（{source}）")
        return 0 if run_build_h5(hbx_cli) else 1

    install_lifecycle_handlers()

    # 解析 Runtime 目标（默认全部拉起：FastAPI + 微信 + H5 + 隧道）
    runtimes = set()
    if args.backend_only:
        runtimes = set()
    elif args.all:
        runtimes = {FrontendRuntime.WEIXIN, FrontendRuntime.H5}
    elif args.weixin and not args.h5:
        runtimes = {FrontendRuntime.WEIXIN}
    elif args.h5 and not args.weixin:
        runtimes = {FrontendRuntime.H5}
    else:
        # 无参数（默认）或 --weixin --h5 同时给：等价 --all
        runtimes = {FrontendRuntime.WEIXIN, FrontendRuntime.H5}

    need_backend = not args.frontend_only

    print("=" * 60)
    print(" 南山科转通 · Multi-Runtime 前后端一键联调")
    print("=" * 60)

    # [1/6] HBuilderX CLI
    print("[1/6] 检查 HBuilderX CLI")
    hbx_cli, source = None, ""
    if runtimes:
        hbx_cli, source = find_hbx_cli()
        if hbx_cli is None:
            warn("未找到 HBuilderX cli.exe（可设置 HBX_CLI 环境变量）")
        else:
            ok(f"{hbx_cli}（{source}）")
    else:
        skip("无前端 Runtime 目标")

    # [2/6] Demo 开关
    print("[2/6] 检查前端联调开关（common/config.js）")
    if runtimes:
        ask_demo_switch()
    else:
        skip("无前端 Runtime 目标")

    # [3/6] 后端环境
    print("[3/6] 检查后端环境（依赖 / PostgreSQL）")
    if need_backend:
        deps_ok = ensure_backend_deps()
        if not deps_ok and args.strict:
            return 1
        check_db_config()
    else:
        skip("跳过后端（--frontend-only）")

    # [4/6] 启动 FastAPI（唯一实例，8787 三分支）
    print("[4/6] 启动 FastAPI 后端")
    backend_proc = None
    if need_backend:
        backend_proc = resolve_backend(lan=args.lan)
    else:
        skip("跳过后端（--frontend-only）")

    # [5/6] 启动前端 Runtime
    print("[5/6] 启动前端 Runtime")
    status = {"backend": "READY" if (backend_proc is not None or fetch_health()[0]) else "OFF",
              "weixin": "OFF", "h5": "OFF", "tunnel": "OFF"}

    if FrontendRuntime.WEIXIN in runtimes:
        if hbx_cli is None:
            error("微信 Runtime 启动失败（无 HBuilderX CLI）")
            status["weixin"] = "FAIL"
        elif run_weixin(hbx_cli):
            status["weixin"] = "READY"
        else:
            status["weixin"] = "FAIL"

    if FrontendRuntime.H5 in runtimes:
        if hbx_cli is None:
            error("H5 Runtime 启动失败（无 HBuilderX CLI）")
            status["h5"] = "FAIL"
        elif run_h5(hbx_cli, args.lan):
            status["h5"] = "READY"
        else:
            status["h5"] = "FAIL"

    # [6/6] frp 外网隧道（默认开启，--no-tunnel 关闭）
    tunnel_urls = None
    tunnel_info = None
    print("[6/6] frp 外网隧道")
    if args.tunnel:
        if not need_backend and not fetch_health()[0]:
            warn("后端未运行（--frontend-only），隧道 API 端点将不可用")
        tunnel_ok, tunnel_info = run_tunnel()
        if tunnel_ok:
            status["tunnel"] = "READY"
            tunnel_urls = []
            if tunnel_info["pairs"].get(BACKEND_PORT):
                tunnel_urls.append(("API", tunnel_info["api_tunnel"]))
            if tunnel_info["pairs"].get(H5_PORT):
                tunnel_urls.append(("H5", tunnel_info["h5_tunnel"]))
        else:
            status["tunnel"] = "FAIL"
    else:
        skip("已关闭（--no-tunnel）")

    print_summary(runtimes, args.lan, tunnel_urls)

    # 结果判定：核心组件失败即退出；仅隧道失败不影响本地联调（--strict 除外）
    failed = [k for k, v in status.items() if v == "FAIL"]
    if failed:
        core_failed = [k for k in failed if k != "tunnel"]
        if core_failed:
            error(f"启动失败：{', '.join(core_failed)}")
            return 1
        if args.strict:
            error(f"严格模式：{', '.join(failed)} 失败")
            return 1
        print(f"  状态：PARTIAL（{', '.join(failed)} 失败，本地联调不受影响）")

    print("READY")
    print()
    print("  按 Ctrl+C 停止（仅终止本启动器启动的进程；复用的后端 / HBuilderX GUI 不受影响）")
    if status.get("tunnel") == "READY":
        print("  外网访问需保持本启动器运行（frpc 由其托管）")

    tunnel_restarts = 0
    try:
        while True:
            time.sleep(5)
            # 后端 watchdog：仅看护本启动器 spawn 的后端（复用的不接管）
            if backend_proc is not None and backend_proc.poll() is not None:
                warn("检测到后端进程退出，5s 后自动重启 ...")
                time.sleep(5)
                try:
                    backend_proc = start_backend(lan=args.lan)
                except SystemExit as e:
                    error(f"后端重启失败：{e}")
                    return 1
            # frpc watchdog：仅看护本启动器 spawn 的 frpc，最多重启 3 次
            tproc = managed_processes.get("tunnel")
            if tproc is not None and tproc.poll() is not None and tunnel_info is not None:
                if tunnel_restarts >= 3:
                    warn("frpc 反复退出，不再自动重启（外网入口不可用，本地联调不受影响）")
                    managed_processes.pop("tunnel", None)
                else:
                    tunnel_restarts += 1
                    warn(f"检测到 frpc 进程退出，5s 后自动重启（第 {tunnel_restarts}/3 次）...")
                    time.sleep(5)
                    try:
                        new_proc = spawn_frpc(tunnel_info["frpc_exe"], tunnel_info["frpc_toml"])
                        ok(f"frpc 已重启（PID {new_proc.pid}）")
                    except Exception as e:
                        warn(f"frpc 重启失败：{e}")
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_managed()
        print("\n[OK] 启动器已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
