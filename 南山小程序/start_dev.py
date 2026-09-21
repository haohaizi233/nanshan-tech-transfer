"""
南山科转通 · Multi-Runtime 前后端一键联调启动器（stdlib only）

同一份 uni-app 源码，多 Runtime 联调：

    uni-app (Vue3) ──┬── mp-weixin（微信开发者工具）──┐
                     └── H5（HBuilderX dev server）──┤
                                                    ├── FastAPI :8787 ── PostgreSQL
                                    Admin Web ──────┘
                          Caddy ── https://inanshan.sjhcip.com
                                    /health+/api → :8025（VPS；本机 start_dev 仍反代 :8787）
                                    /h5          → :5173
                                    其余         → FastAPI（后台 SPA）
                          frpc 隧道 ── 43.138.138.200:8076(API)/8077(H5)

用法：
  python start_dev.py                     # 默认 FastAPI + H5 + frp 隧道 + Caddy（不打开微信开发者工具）
  python start_dev.py --h5                # 与默认相同：FastAPI + 仅 H5
  python start_dev.py --weixin            # FastAPI + 微信小程序（会打开微信开发者工具）
  python start_dev.py --all               # FastAPI + 微信 + H5
  python start_dev.py --no-tunnel         # 关闭 frp 外网隧道（纯本地联调）
  python start_dev.py --no-caddy          # 不启动 Caddy（https://inanshan.sjhcip.com）
  python start_dev.py --backend-only      # 仅 FastAPI（+ 隧道 + Caddy）
  python start_dev.py --frontend-only --weixin|h5|all   # 仅前端，不起后端
  python start_dev.py --h5 --lan          # H5 + FastAPI 局域网模式（输出 LAN 地址）
  python start_dev.py --doctor            # 环境诊断，只检测不启动
  python start_dev.py --status            # 查看运行状态，不启动
  python start_dev.py --build-h5          # H5 production build（不启动后端）
  python start_dev.py --strict            # 严格模式：任何组件失败即退出非 0

说明：
  - HBuilderX CLI 运行 H5 / 微信均为「HBuilderX owned」进程，启动器不强制关闭它们；
    Ctrl+C 只 terminate 本启动器自己 spawn 的进程（FastAPI / frpc / caddy）。
  - 8787 已有健康的南山 FastAPI 时自动复用，退出启动器不会终止它；
    但若后端源码比监听进程新（如 git pull 之后），会先终止旧进程再重新启动，
    避免复用旧代码导致「前端拉到最新但接口还是旧行为」。
  - 外网转发使用 frp（frpc.toml：serverAddr + 8076→8787 + 8077→5173），
    默认随启动器一起拉起 frpc 并做外网端到端健康验证（--no-tunnel 关闭）；
    frpc 目录检测顺序：FRPC_HOME 环境变量 > 桌面 frp* 扫描。
  - Caddy 默认随启动器拉起（--no-caddy 关闭）：deploy/Caddyfile 把
    https://inanshan.sjhcip.com/health+/api 与后台 SPA 转到本机 8787，/h5 转到 5173；
    VPS 上未设 NS_API_UPSTREAM 时默认反代 127.0.0.1:8025；
    检测顺序：CADDY_HOME > PATH > 桌面 caddy*。
  - 启动器 spawn 的后端进程退出时（如崩溃）keep-alive 循环会自动重启。
"""

import argparse
import atexit
import hashlib
import http.client
import importlib.util
import ipaddress
import json
import os
import re
import signal
import socket
import ssl
import subprocess
import sys
import threading
import time
import tempfile
import urllib.error
import urllib.request
from enum import Enum
from pathlib import Path
from shutil import which

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "南山"
ADMIN_FRONTEND_DIR = ROOT.parent / "nanshan-frontend"
ADMIN_DIST_INDEX = ADMIN_FRONTEND_DIR / "dist" / "index.html"
API_SERVER_DIR = ROOT.parent / "tech-transfer-service"
AI_AGENT_DIR = ROOT.parent / "nanshan-ai-agent"
# 启动器常由系统 Python 调起；后端必须优先使用项目已验证的虚拟环境，
# 否则系统级 FastAPI/Pydantic 的版本漂移会在路由注册阶段导致启动失败。
BACKEND_VENV_PYTHON = ROOT.parent / ".venv" / "Scripts" / "python.exe"
BACKEND_PYTHON = str(BACKEND_VENV_PYTHON if BACKEND_VENV_PYTHON.is_file() else Path(sys.executable))
BACKEND_URL = "http://127.0.0.1:8787"
HEALTH_URL = BACKEND_URL + "/api/health"
API_ROOT = BACKEND_URL + "/api/tech-transfer/v1"
BACKEND_PORT = 8787
AI_AGENT_PORT = 8001
AI_AGENT_HEALTH_URL = f"http://127.0.0.1:{AI_AGENT_PORT}/health"
H5_PORT = 5173
H5_PUBLIC_PATH = "/h5/"
H5_URL = f"http://127.0.0.1:{H5_PORT}"
H5_PAGE_URL = f"{H5_URL}{H5_PUBLIC_PATH}"

HBX_CLI_DEFAULT = Path(r"D:\HBuilder X\cli.exe")
HBX_ROOT_DIRS = [
    Path(r"D:\HBuilder X"),
    Path(r"D:\HBuilderX"),
    Path(r"C:\Program Files\HBuilderX"),
]
WECHAT_DEVTOOLS_DEFAULT = Path(r"D:\微信web开发者工具\cli.bat")

# frp 隧道（frpc.toml：serverAddr + [[proxies]] localPort→remotePort）
FRPC_SCAN_ROOTS = [Path.home() / "Desktop", Path("D:\\")]
TUNNEL_API_PORT = 8076   # 远端 API 入口（→ 本地 8787，实际以 frpc.toml 解析为准）
TUNNEL_H5_PORT = 8077    # 远端 H5 入口（→ 本地 5173，实际以 frpc.toml 解析为准）

# Caddy 反向代理（deploy/Caddyfile：VPS /health+/api+后台 → 8025，本机 start_dev 仍反代 8787；/h5 → 5173）
CADDY_SCAN_ROOTS = [Path.home() / "Desktop", Path("D:\\")]
CADDYFILE = ROOT.parent / "deploy" / "Caddyfile"
CADDY_HTTPS_PORT = 443
CADDY_SITE_DEFAULT = "inanshan.sjhcip.com"


# ── 前端构建新鲜度 ───────────────────────────────────────────
def output_is_stale(source_files, output_file):
    """产物缺失或任一源码比产物新时返回 True。"""
    if not output_file.is_file():
        return True
    try:
        output_mtime = output_file.stat().st_mtime_ns
    except OSError:
        return True
    for source in source_files:
        try:
            if source.is_file() and source.stat().st_mtime_ns > output_mtime:
                return True
        except OSError:
            continue
    return False


def _source_files(root, root_files=(), source_dirs=()):
    """收集会影响前端产物的源码，忽略构建产物和依赖目录。"""
    files = [root / name for name in root_files]
    ignored = {"node_modules", "dist", "unpackage", ".git", ".vite"}
    for relative_dir in source_dirs:
        directory = root / relative_dir
        if not directory.is_dir():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and not any(part in ignored for part in path.parts):
                files.append(path)
    return files


def h5_source_files():
    return _source_files(
        FRONTEND_DIR,
        root_files=("App.vue", "main.js", "manifest.json", "pages.json"),
        source_dirs=("pages", "subpackages", "components", "static", "host", "config"),
    )


def admin_source_files():
    return _source_files(
        ADMIN_FRONTEND_DIR,
        root_files=("index.html", "vite.config.js", "package.json", "package-lock.json"),
        source_dirs=("src", "public"),
    )


def backend_source_files():
    """后端运行时代码（app/config/db + core/modules/routes）；测试、工具脚本、迁移不参与过期判断。"""
    files = [API_SERVER_DIR / name for name in ("app.py", "config.py", "db.py")]
    for relative_dir in ("core", "modules", "routes"):
        directory = API_SERVER_DIR / relative_dir
        if directory.is_dir():
            files.extend(p for p in directory.rglob("*.py") if p.is_file())
    return files


def _h5_state_file():
    project_key = hashlib.sha1(str(FRONTEND_DIR).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / f"nanshan-h5-{project_key}.stamp"


def h5_needs_restart():
    """首次接管或源码比上次确认的 H5 运行版本新时，要求重启 watcher。"""
    return output_is_stale(h5_source_files(), _h5_state_file())


def mark_h5_current():
    _h5_state_file().write_text(str(time.time_ns()), encoding="utf-8")


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


def register_process(key, proc):
    managed_processes[key] = proc


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


def _decode_cli_output(raw):
    if not raw:
        return ""
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def hbx_supports_launch(hbx_cli):
    """HBuilderX 4.87 内置 CLI 没有 launch；5.x 才支持 cli launch web / mp-weixin。"""
    try:
        ret = subprocess.run(
            [str(hbx_cli)],
            capture_output=True, timeout=20,
        )
    except Exception:
        return False
    text = _decode_cli_output((ret.stdout or b"") + (ret.stderr or b""))
    return "launch web" in text.lower() or "launch mp-weixin" in text.lower()


_hbx_project_opened = False


def open_hbuilderx_project(hbx_cli):
    """4.87 无 launch 时：拉起 HBuilderX 并打开小程序工程，供 GUI 点运行。"""
    global _hbx_project_opened
    if _hbx_project_opened:
        return
    try:
        subprocess.Popen(
            [str(hbx_cli), "open"],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        subprocess.Popen(
            [str(hbx_cli), "project", "open", "--path", str(FRONTEND_DIR)],
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
        )
        _hbx_project_opened = True
    except Exception as e:
        warn(f"打开 HBuilderX 工程失败：{e}")


def open_wechat_devtools():
    exe = WECHAT_DEVTOOLS_DEFAULT.parent / "微信开发者工具.exe"
    if exe.is_file():
        subprocess.Popen(
            [str(exe)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )
        return True
    return False


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


def port_pids(port):
    """Windows：netstat 解析该端口全部监听 PID（去重）。

    uvicorn reload 模式下父子进程共享监听 socket，且可能残留历史孤儿进程，
    逐个 PID 终止时必须拿全量列表。
    """
    pids = set()
    try:
        out = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=10
        ).stdout
    except Exception:
        return []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and f":{port}" in parts[1]:
            try:
                pid = int(parts[4])
                if pid > 0:
                    pids.add(pid)
            except ValueError:
                pass
    return sorted(pids)


def _filetime_to_ns(raw):
    """FILETIME（1601 纪元起 100ns 计数）→ 1970 纪元纳秒。偏移 = 11644473600s × 10^7 tick/100ns。"""
    return (raw - 11644473600 * 10**7) * 100


def process_start_ns(pid):
    """Windows：ctypes 读进程创建时间，返回与 time.time_ns() 可比的纳秒值；失败返回 None。"""
    import ctypes

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    kernel32 = ctypes.windll.kernel32
    # 必须显式声明原型：默认 c_int 返回值会把 64 位句柄/结果截断成垃圾值（已实测踩坑）
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.GetProcessTimes.restype = ctypes.c_int
    kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p] + [ctypes.c_void_p] * 4
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return None
    try:
        creation, exit_time, kernel_t, user_t = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        if not kernel32.GetProcessTimes(
            handle, ctypes.byref(creation), ctypes.byref(exit_time),
            ctypes.byref(kernel_t), ctypes.byref(user_t),
        ):
            return None
        raw = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
        # FILETIME：1601 纪元起 100ns 计数；偏移 = 11644473600s × 10^7 tick/100ns
        return (raw - 11644473600 * 10**7) * 100
    finally:
        kernel32.CloseHandle(handle)


def _python_processes_with_cmdline():
    """[(pid, cmdline)]：python.exe / pythonw.exe 进程清单（PowerShell CIM，失败返回 []）。

    errors="replace"：控制台代码页与解码不一致时中文乱码无妨，ASCII 的
    parent_pid=<数字> 一定能读出来。
    """
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" "
             "| Select-Object ProcessId, CommandLine | ConvertTo-Json -Compress"],
            capture_output=True, text=True, errors="replace", timeout=20,
        ).stdout.strip()
    except Exception:
        return []
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        return []
    if isinstance(data, dict):  # 单进程时 ConvertTo-Json 输出对象而非数组
        data = [data]
    result = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            pid = int(item.get("ProcessId"))
        except (TypeError, ValueError):
            continue
        result.append((pid, item.get("CommandLine") or ""))
    return result


def _spawn_child_pids(parent_pids):
    """multiprocessing spawn 子进程（uvicorn reload worker）的 PID。

    spawn 子进程命令形如：python -c "from multiprocessing.spawn import spawn_main;
    spawn_main(parent_pid=30584, pipe_handle=504)" —— 自带父 PID，可精确匹配不误伤。
    它持有继承的监听 socket：netstat 只显示创建者、taskkill /T 实测也会漏杀，
    必须单独枚举（2026-09-07 实弹踩坑：杀掉 netstat 两个 PID 后端口仍被占）。
    """
    wanted = {str(p) for p in parent_pids}
    found = []
    for pid, cmdline in _python_processes_with_cmdline():
        m = re.search(r"parent_pid=(\d+)", cmdline)
        if m and m.group(1) in wanted and pid not in wanted:
            found.append(pid)
    return found


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
def _localhost_request(url, timeout=3):
    """本机探活不走系统代理（避免 7890 等对 127.0.0.1 返回 502）。"""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return opener.open(url, timeout=timeout)


def fetch_health(timeout=3):
    """返回 (http_ok, data_dict)。http_ok=False 表示端口上没有 HTTP 服务。"""
    try:
        with _localhost_request(HEALTH_URL, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return True, body
    except urllib.error.HTTPError:
        return True, None  # 有 HTTP 响应但非 200
    except Exception:
        return False, None


def fetch_ai_agent_health(timeout=3):
    try:
        with _localhost_request(AI_AGENT_HEALTH_URL, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return resp.status == 200 and body.get("status") == "ok", body
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
    """检查 import 名，安装以 requirements.txt 为准。"""
    required = ("fastapi", "uvicorn", "psycopg2", "jwt", "pypdfium2", "PIL", "opencc")
    probe = subprocess.run(
        [BACKEND_PYTHON, "-c", "import importlib.util,sys; missing=[m for m in sys.argv[1:] if importlib.util.find_spec(m) is None]; print(','.join(missing))", *required],
        capture_output=True, text=True,
    )
    missing = [m for m in probe.stdout.strip().split(",") if m] if probe.returncode == 0 else list(required)
    if not missing:
        ok(f"后端依赖已就绪（{BACKEND_PYTHON}）")
        return True
    print(f"  检测到缺少依赖：{', '.join(missing)}，自动安装中（依据 requirements.txt）...")
    env = os.environ.copy()
    env.setdefault("NO_PROXY", "pypi.tuna.tsinghua.edu.cn")
    env.setdefault("no_proxy", "pypi.tuna.tsinghua.edu.cn")
    ret = subprocess.run(
        [BACKEND_PYTHON, "-m", "pip", "install", "-r", str(API_SERVER_DIR / "requirements.txt")],
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
def backend_is_stale():
    """复用前检查：任一后端进程启动后，后端源码又更新过（git pull / 本地修改）。

    「后端进程」= netstat 监听者 + 其 multiprocessing spawn 子进程（uvicorn reload
    worker 持有继承的 socket，netstat 不显示、taskkill /T 也会漏杀）。
    返回 True 表示旧进程已清理、端口已释放，调用方应重新启动后端。
    拿不到进程启动时间时不误杀，维持旧复用行为。
    """
    owners = port_pids(BACKEND_PORT)
    if not owners:
        return False
    procs = owners + [p for p in _spawn_child_pids(owners) if p not in owners]
    starts = [(pid, process_start_ns(pid)) for pid in procs]
    known_starts = [s for _, s in starts if s]
    if not known_starts:
        warn(f"无法读取现有后端进程（PID={','.join(map(str, procs))}）启动时间，直接复用")
        return False
    oldest_start = min(known_starts)  # 多进程（reload 父子/孤儿）按最老者判断
    grace_ns = 2_000_000_000  # 2s 容差：进程启动瞬间落盘的同秒文件不算过期
    stale_files = [
        f for f in backend_source_files()
        if f.is_file() and f.stat().st_mtime_ns > oldest_start + grace_ns
    ]
    if not stale_files:
        return False
    newest = max(stale_files, key=lambda f: f.stat().st_mtime_ns)
    warn(
        f"现有后端（PID={','.join(map(str, procs))}）启动早于代码更新"
        f"（{len(stale_files)} 个源文件已变更，最新 {newest.name}），重启以加载新代码"
    )
    for pid in procs:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
    for _ in range(20):
        if not port_listening(BACKEND_PORT):
            break
        time.sleep(0.5)
    if port_listening(BACKEND_PORT):
        # 理论上不应到达：所有已知持有者都已终止。可能句柄被更隐蔽的进程复制。
        error(f"旧后端进程已终止，但端口 {BACKEND_PORT} 仍被占用（socket 句柄被隐藏进程持有）")
        error("  请手动排查：netstat -ano | findstr :8787，或重启电脑后重试")
        sys.exit(1)
    return True


def resolve_backend(lan):
    """返回 (proc|None)。proc=None 表示复用已有后端。"""
    if not port_listening(BACKEND_PORT):
        return start_backend(lan)

    http_ok, body = fetch_health()
    if http_ok and body and isinstance(body.get("data"), dict) and body["data"].get("status") in ("ok", "degraded"):
        if backend_is_stale():
            return start_backend(lan)
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
    proc = subprocess.Popen([BACKEND_PYTHON, "-u", "app.py"], cwd=API_SERVER_DIR, env=env)
    register_process("backend", proc)
    if not wait_backend_ready(proc):
        error("后端未就绪")
        sys.exit(1)
    return proc


def wait_ai_agent_ready(proc, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            error("nanshan-ai-agent 进程异常退出，请检查上方报错；后端/H5 仍会继续启动")
            return False
        healthy, _body = fetch_ai_agent_health(timeout=2)
        if healthy:
            ok(f"nanshan-ai-agent Ready：http://127.0.0.1:{AI_AGENT_PORT}")
            return True
        time.sleep(0.5)
    warn(f"AI Agent {timeout}s 内未就绪，/ai/chat 将返回 503")
    return False


def start_ai_agent():
    if not AI_AGENT_DIR.is_dir():
        warn(f"未找到 nanshan-ai-agent 目录：{AI_AGENT_DIR}，跳过 AI 助手启动")
        return None
    print(f"  启动中：nanshan-ai-agent（uvicorn）→ http://127.0.0.1:{AI_AGENT_PORT}")
    env = os.environ.copy()
    env.setdefault("APP_ENV", "local")
    env.setdefault("DB_HOST", os.environ.get("DB_HOST", "127.0.0.1"))
    env.setdefault("DB_PORT", os.environ.get("DB_PORT", "5432"))
    env.setdefault("DB_NAME", os.environ.get("DB_NAME", "tech_transfer"))
    env.setdefault("DB_USER", os.environ.get("DB_USER", "postgres"))
    env.setdefault("DB_PASSWORD", os.environ.get("DB_PASSWORD", "postgres123"))
    proc = subprocess.Popen(
        [
            BACKEND_PYTHON, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(AI_AGENT_PORT),
        ],
        cwd=AI_AGENT_DIR,
        env=env,
    )
    register_process("ai-agent", proc)
    wait_ai_agent_ready(proc)
    return proc


def resolve_ai_agent():
    """返回 (proc|None)。proc=None 表示复用已有 ai-agent。"""
    if not AI_AGENT_DIR.is_dir():
        skip("未找到 nanshan-ai-agent，跳过 AI 助手")
        return None
    healthy, _body = fetch_ai_agent_health()
    if healthy:
        ok(f"检测到现有 nanshan-ai-agent :{AI_AGENT_PORT}，直接复用")
        return None
    if port_listening(AI_AGENT_PORT):
        warn(f"端口 {AI_AGENT_PORT} 已被占用但 health 异常，/ai/chat 可能 503")
        return None
    return start_ai_agent()


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
    if not hbx_supports_launch(hbx_cli):
        warn("当前 HBuilderX CLI 不支持 launch（4.87），改为打开工程与微信开发者工具")
        open_hbuilderx_project(hbx_cli)
        if open_wechat_devtools():
            ok("已打开 HBuilderX 工程与微信开发者工具；请在 HBuilderX 点「运行到小程序」")
        else:
            ok("已打开 HBuilderX 工程；请手动打开微信开发者工具并运行到小程序")
        return True
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
def stop_h5_server():
    """停止绑定本项目专用 H5 端口的 watcher，给最新源码的编译留出端口。"""
    pid = port_pid(H5_PORT)
    if not pid:
        return True
    print(f"  检测到旧 H5 watcher（PID={pid}），正在重启以加载最新源码 ...")
    try:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=15)
    except Exception as e:
        error(f"停止旧 H5 watcher 失败：{e}")
        return False
    deadline = time.time() + 15
    while time.time() < deadline:
        if not port_listening(H5_PORT):
            return True
        time.sleep(0.5)
    error(f"旧 H5 watcher（PID={pid}）未在 15s 内释放端口 {H5_PORT}")
    return False


def run_h5(hbx_cli, lan):
    print("  调用 HBuilderX 编译并运行 H5 dev server ...")
    print(f"  H5 dev 端口：{H5_PORT}（manifest.json h5.devServer.port）")
    if port_listening(H5_PORT):
        if not h5_needs_restart():
            ok(f"检测到 {H5_URL} 已运行，源码未变化，复用现有 H5 dev server")
            return True
        warn("检测到小程序 H5 源码更新，重新编译 H5 dev server")
        if not stop_h5_server():
            return False

    if not hbx_supports_launch(hbx_cli):
        npm = which("npm.cmd") or which("npm")
        hx_npm = Path(r"D:\HBuilder X\plugins\npm\npm.cmd")
        hx_node = Path(r"D:\HBuilder X\plugins\node")
        if hx_npm.is_file() and not npm:
            npm = str(hx_npm)
        if (FRONTEND_DIR / "package.json").is_file() and npm:
            print("  HBuilderX 4.87 无 launch，改用 Vite uni H5（:5173）")
            env = os.environ.copy()
            # 与 vite.config.js 一致：按 HBuilderX 根目录编译，避免 /main.js 不被 mount
            env["UNI_INPUT_DIR"] = str(FRONTEND_DIR)
            if hx_node.is_dir():
                env["PATH"] = str(hx_node) + os.pathsep + env.get("PATH", "")
            proc = subprocess.Popen(
                [npm, "run", "dev:h5"],
                cwd=FRONTEND_DIR,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            register_process("h5", proc)
            if wait_h5_ready(proc, timeout=120):
                ok(f"H5 已就绪：{H5_PAGE_URL}")
                mark_h5_current()
                return True
            error("Vite uni H5 未在 120s 内监听 5173")
            return False
        warn("当前 HBuilderX CLI 不支持 launch web（4.87），且无法启动 Vite H5")
        open_hbuilderx_project(hbx_cli)
        ok("已打开 HBuilderX 工程；请点「运行到浏览器」以启动 H5 :5173")
        return True

    proc, _, _ = spawn_cli_watch(
        [str(hbx_cli), "launch", "web", "--project", str(FRONTEND_DIR)],
        ready_markers=[],
    )
    register_process("h5", proc)

    if not wait_h5_ready(proc):
        if proc.poll() is not None:
            error("HBuilderX H5 启动失败（进程已退出），请检查上方输出")
        else:
            error(f"H5 dev server 在 {H5_URL} 上未就绪（进程可能仍在编译，请手动访问确认）")
        return False

    ok(f"H5 已就绪：{H5_PAGE_URL}")
    mark_h5_current()
    lan_ips = get_lan_ips()
    if lan:
        print("  局域网访问：")
        for ip in lan_ips[:3]:
            print(f"    http://{ip}:{H5_PORT}{H5_PUBLIC_PATH}")
    elif lan_ips:
        print(f"  局域网访问：http://{lan_ips[0]}:{H5_PORT}{H5_PUBLIC_PATH}（完整列表用 --lan 查看）")
    return True


def wait_h5_ready(proc=None, timeout=300):
    """轮询 H5 dev server 首页直到 HTTP 200（process started ≠ service ready）。

    首次冷编译（HBuilderX 全量 build）实测可达 1-3 分钟，超时必须远大于此，
    否则会误杀仍在编译的 watch 进程（热编译后再次启动仅数秒）。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return False
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


# ── 后台管理 H5（静态构建）──────────────────────────────────
def ensure_admin_h5_current():
    """后台公网页由 FastAPI 托管 dist，源码变更时必须先重新 vite build。"""
    print("  检查后台管理 H5 构建产物（nanshan-frontend/dist）...")
    if not output_is_stale(admin_source_files(), ADMIN_DIST_INDEX):
        ok("后台管理 H5 构建产物为最新，复用 dist")
        return True

    npm = which("npm.cmd") or which("npm")
    if not npm:
        error("后台管理 H5 需要 npm，但未在 PATH 中找到 npm")
        return False
    warn("检测到后台管理 H5 源码更新，正在执行 npm run build ...")
    try:
        ret = subprocess.run([npm, "run", "build"], cwd=ADMIN_FRONTEND_DIR, timeout=300)
    except Exception as e:
        error(f"后台管理 H5 构建失败：{e}")
        return False
    if ret.returncode != 0 or not ADMIN_DIST_INDEX.is_file():
        error("后台管理 H5 构建失败，未替换现有 dist")
        return False
    ok("后台管理 H5 已重新构建；公网 /admin/* 将读取最新 dist")
    return True


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


# ── Caddy 反向代理 ────────────────────────────────────────────
def caddy_site():
    return os.environ.get("NS_SITE", CADDY_SITE_DEFAULT).strip() or CADDY_SITE_DEFAULT


def find_caddy():
    """检测 caddy.exe。顺序：CADDY_HOME > PATH > 桌面/D 盘 caddy* 扫描。

    返回 (caddy_exe|None, 来源)。
    """
    names = ("caddy.exe", "caddy") if os.name == "nt" else ("caddy",)

    env_val = os.environ.get("CADDY_HOME", "").strip('"')
    if env_val:
        root = Path(env_val)
        if root.is_file() and root.name.lower().startswith("caddy"):
            return root, "环境变量 CADDY_HOME"
        for name in names:
            candidate = root / name
            if candidate.is_file():
                return candidate, "环境变量 CADDY_HOME"
        warn(f"CADDY_HOME={env_val} 缺少 caddy.exe，忽略")

    for name in names:
        found = which(name)
        if found:
            return Path(found), "PATH"

    for scan_root in CADDY_SCAN_ROOTS:
        if not scan_root.is_dir():
            continue
        for d in sorted(scan_root.glob("caddy*"), reverse=True):
            if d.is_file() and d.name.lower() in ("caddy.exe", "caddy"):
                return d, f"扫描 {d}"
            if not d.is_dir():
                continue
            for sub in [d] + list(d.glob("caddy*")):
                for name in names:
                    candidate = sub / name if sub.is_dir() else None
                    if candidate is not None and candidate.is_file():
                        return candidate, f"扫描 {sub}"
    return None, ""


def caddy_process_running():
    try:
        image = "caddy.exe" if os.name == "nt" else "caddy"
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}"],
            capture_output=True, text=True, timeout=10,
        ).stdout
    except Exception:
        return False
    return "caddy" in out.lower()


def caddy_listening():
    return port_listening(CADDY_HTTPS_PORT)


def caddy_api_healthy(timeout=4):
    """本机 :443 + SNI/Host 域名请求 /api/health。返回 (healthy, body)。

    不走 80：证书校验关闭（连的是 127.0.0.1），SNI 仍用站点名让 Caddy 选对证书。
    本机失败再试公网 https://域名/api/health。
    """
    site = caddy_site()
    conn = None
    sock = None
    try:
        ctx = ssl._create_unverified_context()
        sock = socket.create_connection(("127.0.0.1", CADDY_HTTPS_PORT), timeout=timeout)
        ssock = ctx.wrap_socket(sock, server_hostname=site)
        conn = http.client.HTTPSConnection("127.0.0.1", CADDY_HTTPS_PORT, timeout=timeout, context=ctx)
        conn.sock = ssock
        conn.request("GET", "/api/health", headers={"Host": site})
        resp = conn.getresponse()
        raw = resp.read().decode("utf-8")
        status = resp.status
        if status in (301, 302, 307, 308):
            return _caddy_public_https_healthy(site, timeout)
        if status == 200:
            body = json.loads(raw)
            return body.get("code") == 0, body
    except Exception:
        pass
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
        elif sock is not None:
            try:
                sock.close()
            except OSError:
                pass
    return _caddy_public_https_healthy(site, timeout)


def _caddy_public_https_healthy(site, timeout=4):
    url = f"https://{site}/api/health"
    try:
        with _no_proxy_opener().open(url, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("code") == 0, body
    except Exception:
        return False, None


def _caddy_log_path():
    return Path(tempfile.gettempdir()) / "nanshan-caddy.log"


_caddy_log_handle = None


def spawn_caddy(caddy_exe, caddyfile):
    """拉起 caddy 并注册为启动器托管进程（Ctrl+C 时一并终止）。

    ACME 签证书不能走系统代理（Clash 会劫持 Let's Encrypt），这里清掉代理变量。
    """
    global _caddy_log_handle
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                "http_proxy", "https_proxy", "all_proxy"):
        env.pop(key, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    env.setdefault("NS_SITE", caddy_site())
    env.setdefault("NS_API_UPSTREAM", "127.0.0.1:8787")
    env.setdefault("NS_H5_UPSTREAM", "127.0.0.1:5173")
    # 域名解析在 VPS，本机 ACME 签不出证书，握手会 TLS internal error，反代看起来像后端挂了
    env.setdefault("NS_TLS_SNIPPET", "tls-local.caddy")
    if _caddy_log_handle is not None:
        try:
            _caddy_log_handle.close()
        except OSError:
            pass
    _caddy_log_handle = open(_caddy_log_path(), "ab", buffering=0)
    proc = subprocess.Popen(
        [str(caddy_exe), "run", "--config", str(caddyfile), "--adapter", "caddyfile"],
        stdout=_caddy_log_handle, stderr=subprocess.STDOUT,
        env=env, cwd=str(caddyfile.parent),
    )
    register_process("caddy", proc)
    return proc


def _caddy_log_tail(n=20):
    path = _caddy_log_path()
    if not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except OSError:
        return ""


def run_caddy():
    """启动 Caddy 并做本机端到端验证。返回 (True/False, info|None)。

    复用条件：本机 :443 已在听且 /api/health 经 Caddy 返回 code=0。
    """
    site = caddy_site()
    public_url = f"https://{site}"
    info = {"site": site, "caddyfile": CADDYFILE, "public_url": public_url,
            "health_url": f"{public_url}/api/health", "caddy_exe": None}

    if not CADDYFILE.is_file():
        error(f"未找到 Caddyfile：{CADDYFILE}")
        return False, None

    caddy_exe, source = find_caddy()
    if caddy_exe is None:
        error("未找到 caddy.exe（可设置 CADDY_HOME，或把 caddy 目录加入 PATH）")
        return False, None
    info["caddy_exe"] = caddy_exe
    ok(f"caddy：{caddy_exe}（{source}）")
    print(f"  站点：{public_url} → 127.0.0.1:{BACKEND_PORT}")

    healthy, _body = caddy_api_healthy()
    if healthy:
        ok(f"检测到 Caddy 已就绪，复用现有进程：{public_url}")
        return True, info

    if caddy_process_running() or caddy_listening():
        for _ in range(10):
            healthy, _body = caddy_api_healthy()
            if healthy:
                ok(f"Caddy 已恢复健康，复用现有进程：{public_url}")
                return True, info
            time.sleep(1)
        if caddy_listening() and not caddy_process_running():
            error(f"端口 {CADDY_HTTPS_PORT} 已被其他进程占用"
                  f"（PID={port_pid(CADDY_HTTPS_PORT)}），无法启动 Caddy")
            return False, None
        warn(f"caddy 在运行但 {public_url}/api/health 10s 内未恢复（本地后端未启动？），跳过 Caddy")
        return False, None

    print(f"  启动 caddy（{CADDYFILE.name}）")
    spawn_caddy(caddy_exe, CADDYFILE)

    deadline = time.time() + 30
    while time.time() < deadline:
        proc = managed_processes.get("caddy")
        if proc is not None and proc.poll() is not None:
            tail = _caddy_log_tail()
            error("caddy 进程异常退出（常见原因：443 被占 / Caddyfile 语法错误 / ACME 失败）")
            if tail:
                print(tail)
            return False, None
        healthy, _body = caddy_api_healthy()
        if healthy:
            ok(f"Caddy 已就绪：{public_url}/api/health")
            return True, info
        time.sleep(1)
    error(f"caddy 已启动但 {public_url}/api/health 30s 内未通过健康检查")
    tail = _caddy_log_tail()
    if tail:
        print(tail)
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
    check("后端 Python", Path(BACKEND_PYTHON).is_file(), BACKEND_PYTHON, fatal=True)

    for mod, pkg in (
        ("fastapi", "fastapi"),
        ("uvicorn", "uvicorn"),
        ("psycopg2", "psycopg2-binary"),
        ("jwt", "PyJWT"),
        ("pypdfium2", "pypdfium2"),
        ("PIL", "Pillow"),
        ("opencc", "opencc-python-reimplemented"),
    ):
        probe = subprocess.run(
            [BACKEND_PYTHON, "-c", "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec(sys.argv[1]) else 1)", mod],
            capture_output=True,
        )
        has = probe.returncode == 0
        check(f"后端依赖 {pkg}", has, "" if has else f"import {mod} 失败（pip install {pkg}）")

    for f in ("manifest.json", "pages.json", "main.js", "App.vue", "config/local.env.js", "host/host-bridge.js"):
        check(f"前端 {f}", (FRONTEND_DIR / f).exists(), str(FRONTEND_DIR / f))
    manifest = FRONTEND_DIR / "manifest.json"
    if manifest.exists():
        text = manifest.read_text(encoding="utf-8")
        check("manifest h5.devServer.port", f'"port" : {H5_PORT}' in text, f"应为 {H5_PORT}")

    hbx, source = find_hbx_cli()
    check("HBuilderX CLI", hbx is not None, f"{hbx}（{source}）" if hbx else "未找到，请设置 HBX_CLI 环境变量")
    if hbx is not None:
        launch_ok = hbx_supports_launch(hbx)
        check("HBuilderX launch", launch_ok,
              "cli launch web / mp-weixin" if launch_ok else "4.87 无 launch，将打开 GUI 工程")
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

    caddy_exe, caddy_source = find_caddy()
    check("caddy（HTTPS 反代）", caddy_exe is not None,
          f"{caddy_exe}（{caddy_source}）" if caddy_exe else "未找到（可设置 CADDY_HOME；不影响本地 :8787）")
    check("Caddyfile", CADDYFILE.is_file(), str(CADDYFILE))
    if CADDYFILE.is_file():
        text = CADDYFILE.read_text(encoding="utf-8")
        check("Caddyfile 站点", CADDY_SITE_DEFAULT in text or "NS_SITE" in text, caddy_site())
        if caddy_exe:
            try:
                ret = subprocess.run(
                    [str(caddy_exe), "validate", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
                    capture_output=True, text=True, timeout=15, cwd=str(CADDYFILE.parent),
                )
                detail = "validate ok" if ret.returncode == 0 else (ret.stderr or ret.stdout).strip()[:200]
                check("Caddyfile 语法", ret.returncode == 0, detail)
            except Exception as e:
                check("Caddyfile 语法", False, str(e))

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
    else:
        server, pairs = parse_frpc_config(frpc_toml)
        if not server or BACKEND_PORT not in pairs:
            print("  Tunnel      N/A      frpc.toml 解析失败（缺 serverAddr / 8787 映射）")
        else:
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

    site = caddy_site()
    public_url = f"https://{site}"
    if not CADDYFILE.is_file():
        print(f"  Caddy       N/A      未找到 {CADDYFILE}")
        return True
    caddy_exe, _ = find_caddy()
    if caddy_exe is None:
        print("  Caddy       N/A      未找到 caddy.exe（--caddy 不可用）")
        return True
    healthy, _body = caddy_api_healthy(timeout=4)
    if healthy:
        print(f"  Caddy       RUNNING  {public_url}（/api/health 经反代健康）")
    elif caddy_process_running() or caddy_listening():
        print(f"  Caddy       DEGRADED 进程/端口在但 {public_url}/api/health 不健康")
    else:
        print(f"  Caddy       STOPPED  {public_url}（start_dev.py 默认随启动器拉起）")
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
def print_summary(runtimes, lan, tunnel_urls=None, caddy_info=None):
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
    ai_ok, _ = fetch_ai_agent_health(timeout=2)
    print(f"  AI Agent      http://127.0.0.1:{AI_AGENT_PORT}  ({'READY' if ai_ok else 'OFF'})")
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
        print(f"  Local         {H5_PAGE_URL}")
        if lan_ips:
            print(f"  LAN           http://{lan_ips[0]}:{H5_PORT}{H5_PUBLIC_PATH}")
    if tunnel_urls:
        print()
        print("Tunnel（外网入口，经 frp 转发本机）")
        for label, url in tunnel_urls:
            print(f"  {label:13} {url}")
    if caddy_info:
        print()
        print("Caddy（HTTPS 反代）")
        print(f"  Site          {caddy_info['public_url']}")
        print(f"  Admin         {caddy_info['public_url']}/login")
        print(f"  H5            {caddy_info['public_url']}{H5_PUBLIC_PATH}")
        print(f"  API           {caddy_info['public_url']}/api/")
        print(f"  Health        {caddy_info['health_url']}")
    print()
    print("真机调试（微信小程序）：")
    if FrontendRuntime.WEIXIN not in runtimes:
        print("  本次未打开微信开发者工具。需要时请用：python start_dev.py --weixin")
    print("  开发者工具 / 扫码  走 https://inanshan.sjhcip.com（config/local.env.js API_BASE_WEIXIN）")
    print("  请在小程序后台把 request 合法域名配成该 HTTPS 域名；开发版可先勾选「不校验合法域名」")
    api_tunnel_url = next((u for label, u in tunnel_urls if label == "API"), None) if tunnel_urls else None
    if api_tunnel_url:
        print(f"  外网（frp）  {api_tunnel_url}")
    if caddy_info:
        print(f"  外网（Caddy） {caddy_info['public_url']}")
    print("=" * 60)


# ── 主流程 ────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="南山科转通 Multi-Runtime 前后端一键联调启动器")
    parser.add_argument("--backend-only", action="store_true", help="只启动 FastAPI 后端")
    parser.add_argument("--frontend-only", action="store_true", help="只启动前端 Runtime（配合 --weixin/--h5/--all）")
    parser.add_argument("--weixin", action="store_true",
                        help="启动微信小程序 Runtime（会打开微信开发者工具）")
    parser.add_argument("--h5", action="store_true", help="启动 H5 Runtime（默认已开启，不必再传）")
    parser.add_argument("--all", action="store_true", help="同时启动微信小程序 + H5（会打开微信开发者工具）")
    parser.add_argument("--tunnel", dest="tunnel", action="store_true", default=True,
                        help="启动 frpc 外网隧道（默认开启；frpc.toml：8076→8787 / 8077→5173）并做端到端健康验证")
    parser.add_argument("--no-tunnel", dest="tunnel", action="store_false",
                        help="不启动 frp 外网隧道（纯本地联调）")
    parser.add_argument("--caddy", dest="caddy", action="store_true", default=True,
                        help="启动 Caddy（默认开启；deploy/Caddyfile：https://inanshan.sjhcip.com /health+/api+/admin → 本机 8787 或 VPS 8025，/h5 → 5173）")
    parser.add_argument("--no-caddy", dest="caddy", action="store_false",
                        help="不启动 Caddy 反向代理")
    parser.add_argument("--lan", action="store_true", help="局域网模式：FastAPI 绑定 0.0.0.0，输出 LAN 地址")
    parser.add_argument("--doctor", action="store_true", help="环境诊断，只检测不启动")
    parser.add_argument("--status", action="store_true", help="查看当前运行状态，不启动")
    parser.add_argument("--build-h5", action="store_true", help="H5 production build（不启动 FastAPI）")
    parser.add_argument("--strict", action="store_true", help="严格模式：任何组件失败即退出非 0")
    return parser.parse_args()


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

    args = parse_args()

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

    # 解析 Runtime 目标：默认只起 H5，避免每次 start 都弹出微信开发者工具
    runtimes = set()
    if args.backend_only:
        runtimes = set()
    elif args.all or (args.weixin and args.h5):
        runtimes = {FrontendRuntime.WEIXIN, FrontendRuntime.H5}
    elif args.weixin:
        runtimes = {FrontendRuntime.WEIXIN}
    else:
        # 无参数 / 仅 --h5：FastAPI + H5
        runtimes = {FrontendRuntime.H5}

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

    # [2/6] 后端环境
    print("[2/6] 检查后端环境（依赖 / PostgreSQL）")
    if need_backend:
        deps_ok = ensure_backend_deps()
        if not deps_ok and args.strict:
            return 1
        check_db_config()
    else:
        skip("跳过后端（--frontend-only）")

    # 公网后台由 FastAPI 静态托管 nanshan-frontend/dist；构建必须在后端启动前完成。
    print("[3/6] 检查后台管理 H5")
    if not ensure_admin_h5_current():
        return 1

    # [4/6] 启动 FastAPI（唯一实例，8787 三分支）
    print("[4/6] 启动 FastAPI 后端")
    backend_proc = None
    if need_backend:
        backend_proc = resolve_backend(lan=args.lan)
    else:
        skip("跳过后端（--frontend-only）")

    # [5/6] 启动 nanshan-ai-agent（/ai/chat 代理目标，默认 8001）
    print("[5/6] 启动 AI Agent")
    ai_agent_proc = None
    if need_backend:
        ai_agent_proc = resolve_ai_agent()
    else:
        skip("跳过 AI Agent（--frontend-only）")

    # [6/6] 启动前端 Runtime
    print("[6/6] 启动前端 Runtime")
    status = {"backend": "READY" if (backend_proc is not None or fetch_health()[0]) else "OFF",
              "weixin": "OFF", "h5": "OFF", "tunnel": "OFF", "caddy": "OFF"}

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

    # frp 外网隧道（默认开启，--no-tunnel 关闭）
    tunnel_urls = None
    tunnel_info = None
    print("frp 外网隧道")
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

    # Caddy HTTPS 反代（默认开启，--no-caddy 关闭）
    caddy_info = None
    print("Caddy 反向代理")
    if args.caddy:
        if not need_backend and not fetch_health()[0]:
            warn("后端未运行（--frontend-only），Caddy /api 将返回 502")
        caddy_ok, caddy_info = run_caddy()
        if caddy_ok:
            status["caddy"] = "READY"
        else:
            status["caddy"] = "FAIL"
            caddy_info = None
    else:
        skip("已关闭（--no-caddy）")

    print_summary(runtimes, args.lan, tunnel_urls, caddy_info)

    # 结果判定：核心组件失败即退出；仅隧道/Caddy 失败不影响本地联调（--strict 除外）
    failed = [k for k, v in status.items() if v == "FAIL"]
    if failed:
        core_failed = [k for k in failed if k not in ("tunnel", "caddy")]
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
    if status.get("caddy") == "READY":
        print("  HTTPS 入口需保持本启动器运行（caddy 由其托管）")

    tunnel_restarts = 0
    caddy_restarts = 0
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
            aproc = managed_processes.get("ai-agent")
            if aproc is not None and aproc.poll() is not None:
                warn("检测到 nanshan-ai-agent 进程退出，5s 后自动重启 ...")
                time.sleep(5)
                try:
                    ai_agent_proc = start_ai_agent()
                except SystemExit as e:
                    warn(f"AI Agent 重启失败：{e}")
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
            # caddy watchdog：仅看护本启动器 spawn 的 caddy，最多重启 3 次
            cproc = managed_processes.get("caddy")
            if cproc is not None and cproc.poll() is not None and caddy_info is not None:
                if caddy_restarts >= 3:
                    warn("caddy 反复退出，不再自动重启（HTTPS 入口不可用，本地联调不受影响）")
                    managed_processes.pop("caddy", None)
                else:
                    caddy_restarts += 1
                    warn(f"检测到 caddy 进程退出，5s 后自动重启（第 {caddy_restarts}/3 次）...")
                    time.sleep(5)
                    try:
                        new_proc = spawn_caddy(caddy_info["caddy_exe"], caddy_info["caddyfile"])
                        ok(f"caddy 已重启（PID {new_proc.pid}）")
                    except Exception as e:
                        warn(f"caddy 重启失败：{e}")
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_managed()
        print("\n[OK] 启动器已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
