import os
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # LLM
    LLM_API_URL = os.getenv("LLM_API_URL")
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_MODEL = os.getenv("LLM_MODEL")

    # PostgreSQL —— 建议为 AI 服务单独建只读角色（最小权限原则），
    # 设置 AI_DB_USER/AI_DB_PASSWORD 后将使用该只读账号，未设置则回退主账号。
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("AI_DB_USER") or os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("AI_DB_PASSWORD") or os.getenv("DB_PASSWORD")
    # 连接池上限：AI 服务并发低，限制连接数避免与主服务争抢 PG max_connections
    DB_MAX_CONN = int(os.getenv("AI_DB_MAX_CONN", "3"))


settings = Settings()