@echo off
REM 本地启动 nanshan-ai-agent（demo）
REM - DB 指向本机 tech_transfer 库（覆盖 .env 里的 192.168.2.79）
REM - LLM 仍走远端 43.138.138.200:8588（.env 里已配）
REM - LLM_MODEL 在 .env 里已切到可用的 Qwen3.8-27B-4bit
REM 用法：在 nanshan-ai-agent 目录下双击或命令行运行 run_local.bat
set DB_HOST=127.0.0.1
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
