"""
南山科转通 · 前后端一键联调启动器（PyCharm 中右键运行本文件即可）

启动内容：
  1. FastAPI 后端    tech-transfer-service/app.py  →  http://127.0.0.1:8787
  2. 小程序前端      调用 HBuilderX CLI 编译 → 自动拉起微信开发者工具（改源码自动热编译）

用法：
  python start_dev.py                 # 前后端全部启动（默认）
  python start_dev.py --backend-only  # 只起后端
  python start_dev.py --frontend-only # 只编译并运行前端
  python start_dev.py --demo          # 恢复演示模式(USE_CAPITAL_DEMO=true)后退出

前置条件（首次使用请确认）：
  - MySQL 已导入 tools/nanshan_capital_backup.sql
  - tools/szte-crawler/db_config.json 已填写 user / password
  - 微信开发者工具：设置 → 安全设置 → 开启「服务端口」
  - 微信开发者工具：详情 → 本地设置 → 勾选「不校验合法域名」
"""

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "南山"
CONFIG_JS = FRONTEND_DIR / "common" / "config.js"
API_SERVER_DIR = ROOT.parent / "tech-transfer-service"
DB_CONFIG = ROOT / "tools" / "szte-crawler" / "db_config.json"
BACKEND_URL = "http://127.0.0.1:8787"
HBX_CLI_DEFAULT = Path(r"D:\HBuilderX\HBuilderX.5.15.2026070915\HBuilderX\cli.exe")

DEMO_RE = re.compile(r"(USE_CAPITAL_DEMO\s*=\s*)(true|false)")


def find_hbx_cli():
    if HBX_CLI_DEFAULT.exists():
        return HBX_CLI_DEFAULT
    for p in sorted(Path(r"D:\HBuilderX").glob("HBuilderX*/HBuilderX/cli.exe")):
        return p
    return None


def read_config_js():
    return CONFIG_JS.read_text(encoding="utf-8")


def set_demo_flag(text, value):
    return DEMO_RE.sub(lambda m: m.group(1) + value, text, count=1)


def get_demo_flag():
    m = DEMO_RE.search(read_config_js())
    return m.group(2) == "true" if m else None


def check_db_config():
    if not DB_CONFIG.exists():
        print("  [!] 未找到 db_config.json，后端将无法查询 MySQL")
        return
    cfg = json.loads(DB_CONFIG.read_text(encoding="utf-8"))
    if not cfg.get("user"):
        print("  [!] db_config.json 中 user/password 仍为空（脱敏状态）")
        print("      后端能启动，但接口会返回「数据库查询失败」；请先填写并导入 nanshan_capital_backup.sql")
        return
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
        print("  [OK] MySQL 连接正常")
    except Exception as e:
        print(f"  [!] MySQL 连接失败：{e}")
        print("      请确认 MySQL 服务已启动（后端仍会启动，但接口会报错）")


def ensure_backend_deps():
    missing = [m for m in ("fastapi", "uvicorn", "pymysql", "jwt") if importlib.util.find_spec(m) is None]
    if not missing:
        print("  [OK] 后端依赖已就绪")
        return
    print(f"  检测到缺少依赖：{', '.join(missing)}，自动安装中 ...")
    env = os.environ.copy()
    env.setdefault("NO_PROXY", "pypi.tuna.tsinghua.edu.cn")
    env.setdefault("no_proxy", "pypi.tuna.tsinghua.edu.cn")
    ret = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(API_SERVER_DIR / "requirements.txt")],
        env=env,
    )
    if ret.returncode != 0:
        sys.exit(f"依赖安装失败，请手动执行：pip install -r {API_SERVER_DIR / 'requirements.txt'}")
    print("  [OK] 依赖安装完成")


def ask_demo_switch():
    if get_demo_flag() is not True:
        print("  [OK] 前端已处于联调模式（USE_CAPITAL_DEMO = false）")
        return
    print("  [!] 当前为演示模式（USE_CAPITAL_DEMO = true），小程序不会请求后端")
    try:
        ans = input("  是否自动改为 false 进行前后端联调？[y/N] ").strip().lower()
    except EOFError:
        ans = ""
    if ans == "y":
        CONFIG_JS.write_text(set_demo_flag(read_config_js(), "false"), encoding="utf-8")
        print("  [OK] 已改为联调模式（恢复演示模式可运行：python start_dev.py --demo）")
    else:
        print("  保留演示模式：本次后端仍会启动，但小程序读的是本地演示数据")


def start_backend():
    print("  启动中：python app.py（http://0.0.0.0:8787）")
    env = os.environ.copy()
    env.setdefault("APP_ENV", "local")
    env.setdefault("HOST_MODE", "local")
    env.setdefault("AUTH_PROVIDER", "mock")
    return subprocess.Popen([sys.executable, "-u", "app.py"], cwd=API_SERVER_DIR, env=env)


def wait_backend_ready(proc):
    for _ in range(60):
        if proc.poll() is not None:
            sys.exit("后端进程异常退出，请检查上方报错（常见原因：8787 端口被占用 / MySQL 未启动）")
        try:
            with urllib.request.urlopen(BACKEND_URL + "/api/health", timeout=2):
                print("  [OK] 后端已就绪：http://127.0.0.1:8787/api/health")
                return
        except urllib.error.HTTPError:
            print("  [OK] 后端已就绪（注意：数据库未连通，接口会报错）")
            return
        except Exception:
            time.sleep(0.5)
    print("  [!] 后端 30 秒内未就绪，请手动访问 http://127.0.0.1:8787/api/health 确认")


def run_frontend(hbx_cli):
    print(f"  调用 HBuilderX 编译并运行到微信开发者工具 ...")
    ret = subprocess.run(
        [str(hbx_cli), "launch", "mp-weixin", "--project", str(FRONTEND_DIR)]
    )
    if ret.returncode != 0:
        print("  [!] HBuilderX 编译失败，请检查上方输出")
        print("      常见原因：微信开发者工具未开启「服务端口」（设置 → 安全设置）")
        return False
    print("  [OK] 编译完成，微信开发者工具应已自动打开小程序")
    print("      后续修改 南山/ 目录下的源码会自动热编译")
    return True


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="南山科转通前后端一键联调启动器")
    parser.add_argument("--backend-only", action="store_true", help="只启动 FastAPI 后端")
    parser.add_argument("--frontend-only", action="store_true", help="只编译并运行小程序前端")
    parser.add_argument("--demo", action="store_true", help="恢复演示模式(USE_CAPITAL_DEMO=true)后退出")
    args = parser.parse_args()

    if args.demo:
        CONFIG_JS.write_text(set_demo_flag(read_config_js(), "true"), encoding="utf-8")
        print("[OK] 已恢复演示模式（USE_CAPITAL_DEMO = true）")
        return

    hbx_cli = find_hbx_cli()

    print("=" * 56)
    print(" 南山科转通 · 前后端一键联调")
    print("=" * 56)

    print("[1/4] 检查 HBuilderX CLI")
    if args.backend_only:
        print("  跳过（--backend-only）")
    elif hbx_cli is None:
        print("  [!] 未找到 HBuilderX cli.exe，请修改脚本顶部 HBX_CLI_DEFAULT 路径")
        if args.frontend_only:
            sys.exit(1)
        print("      将只启动后端")
    else:
        print(f"  [OK] {hbx_cli}")

    print("[2/4] 检查前端联调开关（common/config.js）")
    if args.frontend_only:
        print("  跳过（--frontend-only）")
    else:
        ask_demo_switch()

    print("[3/4] 检查后端环境（依赖 / MySQL）")
    if args.frontend_only:
        print("  跳过（--frontend-only）")
    else:
        ensure_backend_deps()
        check_db_config()

    backend_proc = None
    print("[4/4] 启动服务")
    if not args.frontend_only:
        backend_proc = start_backend()
        wait_backend_ready(backend_proc)
    else:
        print("  跳过后端（--frontend-only）")

    if not args.backend_only and hbx_cli is not None:
        run_frontend(hbx_cli)

    print()
    print("=" * 56)
    if backend_proc is not None:
        print(" 联调就绪：小程序中操作「资本对接」等模块即走后端接口")
        print("   后端接口：http://127.0.0.1:8787/api/health")
        print("   真机调试：config.js 的 API_BASE 改为电脑局域网 IP（ipconfig 查询）")
        print(" 按 Ctrl+C 停止后端（微信开发者工具 / HBuilderX 不受影响）")
        print("=" * 56)
        try:
            backend_proc.wait()
        except KeyboardInterrupt:
            pass
        finally:
            backend_proc.terminate()
            print("\n[OK] 后端已停止")
    else:
        print(" 前端已启动，结束。")
        print("=" * 56)


if __name__ == "__main__":
    main()
