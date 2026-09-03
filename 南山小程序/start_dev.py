"""
南山科转通 · Multi-Runtime 前后端一键联调启动器（stdlib only）

同一份 uni-app 源码，多 Runtime 联调：

    uni-app (Vue3) ──┬── mp-weixin（微信开发者工具）──┐
                     └── H5（HBuilderX dev server）──┤
                                                    ├── FastAPI :8787 ── MySQL
                                     Admin Web(未来) ─┘

用法：
  python start_dev.py                     # 默认 = FastAPI + 微信小程序
  python start_dev.py --weixin            # FastAPI + 微信小程序
  python start_dev.py --h5                # FastAPI + H5
  python start_dev.py --all               # FastAPI + 微信 + H5
  python start_dev.py --backend-only      # 仅 FastAPI
  python start_dev.py --frontend-only --weixin|h5|all   # 仅前端，不起后端
  python start_dev.py --h5 --lan          # H5 + FastAPI 局域网模式（输出 LAN 地址）
  python start_dev.py --doctor            # 环境诊断，只检测不启动
  python start_dev.py --status            # 查看运行状态，不启动
  python start_dev.py --build-h5          # H5 production build（不启动后端）
  python start_dev.py --demo              # 恢复演示模式后退出
  python start_dev.py --strict            # 严格模式：任何组件失败即退出非 0

说明：
  - HBuilderX CLI 运行 H5 / 微信均为「HBuilderX owned」进程，启动器不强制关闭它们；
    Ctrl+C 只 terminate 本启动器自己 spawn 的进程（FastAPI）。
  - 8787 已有健康的南山 FastAPI 时自动复用，退出启动器不会终止它。
  - 内网转发使用 frp：frp 服务端需转发 8787（API）与 5173（H5 dev），本启动器只负责本机。
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
DB_CONFIG = ROOT / "tools" / "szte-crawler" / "db_config.json"
BACKEND_URL = "http://127.0.0.1:8787"
HEALTH_URL = BACKEND_URL + "/api/health"
API_ROOT = BACKEND_URL + "/api/tech-transfer/v1"
BACKEND_PORT = 8787
H5_PORT = 5173
H5_URL = f"http://127.0.0.1:{H5_PORT}"

HBX_CLI_DEFAULT = Path(r"D:\HBuilderX\HBuilderX.5.15.2026070915\HBuilderX\cli.exe")
HBX_ROOT_DIRS = [Path(r"D:\HBuilderX"), Path(r"C:\Program Files\HBuilderX")]
WECHAT_DEVTOOLS_DEFAULT = Path(r"D:\微信开发者工具\微信web开发者工具\cli.bat")

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
    """轮询 /api/health，真正解析 JSON：区分 FastAPI Ready / MySQL Unavailable。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            sys.exit("[FATAL] 后端进程异常退出，请检查上方报错（常见原因：8787 端口被占用 / MySQL 未启动）")
        http_ok, body = fetch_health(timeout=2)
        if http_ok and body and isinstance(body.get("data"), dict):
            data = body["data"]
            if data.get("status") == "ok" and data.get("database") == "ok":
                ok(f"FastAPI Ready：{BACKEND_URL}")
                ok(f"MySQL Ready（appUsers={data.get('appUsers')}）")
                return True
            if data.get("database") == "unavailable":
                warn("FastAPI Ready，但 MySQL Unavailable：数据接口会报错")
                warn(f"  原因：{body.get('message', 'unknown')}")
                return True
        if http_ok and body is None:
            warn("FastAPI Ready（HTTP 非 200，health 异常）")
            return True
        time.sleep(0.5)
    warn(f"后端 {timeout}s 内未就绪，请手动访问 {HEALTH_URL} 确认")
    return False


def ensure_backend_deps():
    """检查 import 名（fastapi/uvicorn/pymysql/jwt），安装以 requirements.txt 为准。"""
    missing = [m for m in ("fastapi", "uvicorn", "pymysql", "jwt") if importlib.util.find_spec(m) is None]
    if not missing:
        ok("后端依赖已就绪（fastapi / uvicorn / pymysql / pyjwt）")
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
    if not DB_CONFIG.exists():
        warn("未找到 db_config.json，后端将无法查询 MySQL")
        return False
    cfg = json.loads(DB_CONFIG.read_text(encoding="utf-8"))
    if not cfg.get("user"):
        warn("db_config.json 中 user/password 仍为空（脱敏状态）")
        return False
    try:
        import pymysql

        conn = pymysql.connect(
            host=cfg.get("host", "127.0.0.1"),
            port=int(cfg.get("port", 3307)),
            user=cfg["user"],
            password=cfg.get("password", ""),
            database=cfg.get("database", "nanshan_capital"),
            connect_timeout=3,
        )
        conn.close()
        ok("MySQL 连接正常（nanshan_capital）")
        return True
    except Exception as e:
        warn(f"MySQL 连接失败：{e}")
        warn("    请确认 MySQL 服务已启动（后端仍会启动，但接口会报错）")
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
            ok(f"MySQL Ready（appUsers={body['data'].get('appUsers')}）")
        else:
            warn("MySQL Unavailable（现有后端）")
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


def wait_h5_ready(timeout=60):
    """轮询 H5 dev server 首页直到 HTTP 200（process started ≠ service ready）。"""
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

    for mod, pkg in (("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("pymysql", "pymysql"), ("jwt", "PyJWT")):
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

    if DB_CONFIG.exists():
        cfg = json.loads(DB_CONFIG.read_text(encoding="utf-8"))
        check("db_config.json 已配置", bool(cfg.get("user")), str(DB_CONFIG))
        try:
            import pymysql

            conn = pymysql.connect(
                host=cfg.get("host", "127.0.0.1"), port=int(cfg.get("port", 3307)),
                user=cfg.get("user", ""), password=cfg.get("password", ""),
                database=cfg.get("database", "nanshan_capital"), connect_timeout=3,
            )
            conn.close()
            check("MySQL 连通", True, "nanshan_capital")
        except Exception as e:
            check("MySQL 连通", False, str(e))
    else:
        check("db_config.json", False, str(DB_CONFIG))

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
        import pymysql

        cfg = json.loads(DB_CONFIG.read_text(encoding="utf-8"))
        conn = pymysql.connect(
            host=cfg.get("host", "127.0.0.1"), port=int(cfg.get("port", 3307)),
            user=cfg.get("user", ""), password=cfg.get("password", ""),
            database=cfg.get("database", "nanshan_capital"), connect_timeout=3,
        )
        conn.close()
        print("  MySQL       RUNNING  nanshan_capital 可连接")
    except Exception as e:
        print(f"  MySQL       DOWN     {e}")
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
def print_summary(runtimes, lan):
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
    print()
    print("真机调试（微信小程序）：")
    if lan_ips:
        print(f"  需将 common/config.js 的 API_BASE 改为 http://{lan_ips[0]}:{BACKEND_PORT}（模拟器用 127.0.0.1）")
    print("=" * 60)


# ── 主流程 ────────────────────────────────────────────────────
def parse_args():
    parser = argparse.ArgumentParser(description="南山科转通 Multi-Runtime 前后端一键联调启动器")
    parser.add_argument("--backend-only", action="store_true", help="只启动 FastAPI 后端")
    parser.add_argument("--frontend-only", action="store_true", help="只启动前端 Runtime（配合 --weixin/--h5/--all）")
    parser.add_argument("--weixin", action="store_true", help="FastAPI + 微信小程序 Runtime")
    parser.add_argument("--h5", action="store_true", help="FastAPI + H5 Runtime")
    parser.add_argument("--all", action="store_true", help="FastAPI + 微信 + H5")
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

    # 解析 Runtime 目标（默认保持既有习惯：FastAPI + 微信）
    runtimes = set()
    if args.backend_only:
        runtimes = set()
    elif args.all:
        runtimes = {FrontendRuntime.WEIXIN, FrontendRuntime.H5}
    elif args.weixin:
        runtimes = {FrontendRuntime.WEIXIN}
    elif args.h5:
        runtimes = {FrontendRuntime.H5}
    elif not args.frontend_only:
        runtimes = {FrontendRuntime.WEIXIN}
    else:
        runtimes = {FrontendRuntime.WEIXIN}  # --frontend-only 不带 runtime 参数时默认微信

    need_backend = not args.frontend_only

    print("=" * 60)
    print(" 南山科转通 · Multi-Runtime 前后端一键联调")
    print("=" * 60)

    # [1/5] HBuilderX CLI
    print("[1/5] 检查 HBuilderX CLI")
    hbx_cli, source = None, ""
    if runtimes:
        hbx_cli, source = find_hbx_cli()
        if hbx_cli is None:
            warn("未找到 HBuilderX cli.exe（可设置 HBX_CLI 环境变量）")
        else:
            ok(f"{hbx_cli}（{source}）")
    else:
        skip("无前端 Runtime 目标")

    # [2/5] Demo 开关
    print("[2/5] 检查前端联调开关（common/config.js）")
    if runtimes:
        ask_demo_switch()
    else:
        skip("无前端 Runtime 目标")

    # [3/5] 后端环境
    print("[3/5] 检查后端环境（依赖 / MySQL）")
    if need_backend:
        deps_ok = ensure_backend_deps()
        if not deps_ok and args.strict:
            return 1
        check_db_config()
    else:
        skip("跳过后端（--frontend-only）")

    # [4/5] 启动 FastAPI（唯一实例，8787 三分支）
    print("[4/5] 启动 FastAPI 后端")
    backend_proc = None
    if need_backend:
        backend_proc = resolve_backend(lan=args.lan)
    else:
        skip("跳过后端（--frontend-only）")

    # [5/5] 启动前端 Runtime
    print("[5/5] 启动前端 Runtime")
    status = {"backend": "READY" if (backend_proc is not None or fetch_health()[0]) else "OFF",
              "weixin": "OFF", "h5": "OFF"}

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

    print_summary(runtimes, args.lan)

    # 结果判定
    failed = [k for k, v in status.items() if v == "FAIL"]
    if failed:
        if args.all and not args.strict:
            print(f"  状态：PARTIAL（{', '.join(failed)} 失败，其余就绪）")
        else:
            error(f"启动失败：{', '.join(failed)}")
            return 1

    print("READY")
    print()
    print("  按 Ctrl+C 停止（仅终止本启动器启动的进程；复用的后端 / HBuilderX GUI 不受影响）")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_managed()
        print("\n[OK] 启动器已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
