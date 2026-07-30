"""
全局配置模块
从 .env 文件加载所有 API 密钥和服务配置
"""
import os
from dotenv import load_dotenv


# 加载 .env 文件
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)


# ==========================================
# LLM 模型配置
# ==========================================
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "qwen3.6-flash")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))


# ==========================================
# DashScope (Embedding)
# ==========================================
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")


# ==========================================
# Qdrant 向量数据库
# ==========================================
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "lisa_knowledge")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_qdrant")


# ==========================================
# Redis 配置
# ==========================================
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"


# ==========================================
# 服务配置
# ==========================================
SERVER_HOST = "0.0.0.0" if os.path.exists("/.dockerenv") else "127.0.0.1"
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))


# ==========================================
# 内存与上下文配置
# ==========================================
MEMORY_TOKEN_LIMIT = int(os.getenv("MEMORY_TOKEN_LIMIT", "20000"))
MAX_CHECKPOINTS = int(os.getenv("MAX_CHECKPOINTS", "5"))


# ==========================================
# 认证配置
# ==========================================
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))


# ==========================================
# TTS 服务配置
# ==========================================
TTS_SERVER_URL = os.getenv("TTS_SERVER_URL", "http://127.0.0.1:9233/tts")
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "中文女")
TTS_TIMEOUT = int(os.getenv("TTS_TIMEOUT", "10"))
TTS_MAX_CONCURRENT = int(os.getenv("TTS_MAX_CONCURRENT", "3"))
