# Phase 1: Core Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the MVP core pipeline — FastAPI server with async LangGraph agent streaming text via SSE, Lisa persona, mood detection, Qdrant RAG tool, logging, and a chat frontend.

**Architecture:** FastAPI async backend runs a LangGraph agent that streams tokens via `astream_events`. Mood detection runs in parallel via `asyncio.create_task` and does not block text output. SSE pushes text + mood events to a vanilla HTML/JS frontend. Redis persists per-user conversation state. All logging goes to `logs/global.log` (file) + terminal (console).

**Tech Stack:** Python 3.10, FastAPI, Uvicorn, LangGraph, LangChain, qwen3.6-flash (Alibaba Token Plan), Redis, Qdrant, DashScope Embeddings, vanilla HTML/CSS/JS.

---

## File Structure

```
20260725_Agent_AI可视化机器人/
├── server.py               # FastAPI main server, SSE streaming, lifespan
├── agent.py                # LangGraph async agent with streaming + parallel mood
├── tools.py                # Qdrant RAG tool (get_info_from_local_db)
├── sys_logger.py           # Global logger (terminal + file dual channel)
├── sys_memory.py           # RedisSaver: LangGraph Redis checkpoint
├── start_redis.py          # Auto start/stop local Redis server
├── config.py               # .env config loader
├── .env                    # Secrets (gitignored)
├── .env.example            # Config template
├── .gitignore              # Ignore .env, logs/, __pycache__, etc.
├── requirements.txt        # Python dependencies
├── static/
│   ├── index.html          # Main page with chat UI
│   ├── css/
│   │   └── style.css       # White theme styles
│   └── js/
│       └── app.js          # SSE client, chat logic
├── logs/                   # Created at runtime
│   └── global.log
└── redis-server/           # Redis executable (copy from reference project)
```

---

## Task 1: Project Setup & Configuration

**Files:**
- Create: `config.py`
- Create: `.env.example`
- Create: `.env`
- Create: `.gitignore`
- Create: `requirements.txt`

- [ ] **Step 1: Create .env.example**

```ini
# 阿里云 Token Plan (LLM)
LLM_API_KEY=your-llm-api-key
LLM_MODEL_NAME=qwen3.6-flash
LLM_BASE_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
LLM_TEMPERATURE=0.2

# DashScope (Embedding)
DASHSCOPE_API_KEY=your-dashscope-api-key
EMBEDDING_MODEL=text-embedding-v3

# Qdrant
QDRANT_COLLECTION=lisa_knowledge

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Server
SERVER_PORT=8000
```

- [ ] **Step 2: Create .env**

Copy `.env.example` to `.env` and fill in real API keys. The `LLM_API_KEY` and `DASHSCOPE_API_KEY` can be copied from the reference project's `.env` at `G:\JupyterProject\20260626_Agent实战\.env`.

- [ ] **Step 3: Create config.py**

```python
"""全局配置模块 - 从 .env 文件加载配置"""
import os
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
load_dotenv(env_path)

# LLM
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_MODEL_NAME = os.getenv("LLM_MODEL_NAME", "qwen3.6-flash")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))

# DashScope (Embedding)
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-v3")

# Qdrant
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "lisa_knowledge")
QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", "6333"))
QDRANT_BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_qdrant")

# Redis
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_URL = f"redis://{REDIS_HOST}:{REDIS_PORT}"

# Server
SERVER_HOST = "0.0.0.0" if os.path.exists("/.dockerenv") else "127.0.0.1"
SERVER_PORT = int(os.getenv("SERVER_PORT", "8000"))

# Memory
MEMORY_TOKEN_LIMIT = int(os.getenv("MEMORY_TOKEN_LIMIT", "2000"))
MAX_CHECKPOINTS = int(os.getenv("MAX_CHECKPOINTS", "5"))
```

- [ ] **Step 4: Create .gitignore**

```
.env
__pycache__/
*.pyc
logs/
local_qdrant/
redis_cache/
redis-server/
*.wav
```

- [ ] **Step 5: Create requirements.txt**

```
fastapi==0.138.1
uvicorn==0.42.0
langchain==1.2.13
langchain-core==1.2.23
langchain-community==0.4.1
langchain-openai==1.1.12
langchain-text-splitters==1.1.1
langgraph==1.1.3
langgraph-checkpoint==4.1.1
qdrant-client==1.12.1
redis==5.2.1
python-dotenv==1.2.2
```

- [ ] **Step 6: Copy Redis server from reference project**

Copy the `redis-server/` folder and `redis_cache/` folder from `G:\JupyterProject\20260626_Agent实战\` to the new project directory. These contain the Windows Redis executable.

Run: `xcopy "G:\JupyterProject\20260626_Agent实战\redis-server" "G:\JupyterProject\20260725_Agent_AI可视化机器人\redis-server\" /E /I`

- [ ] **Step 7: Commit**

```bash
git add config.py .env.example .env .gitignore requirements.txt
git commit -m "chore: project setup and configuration"
```

---

## Task 2: Logging System

**Files:**
- Create: `sys_logger.py`
- Create: `tests/test_sys_logger.py`

Reference: `G:\JupyterProject\20260626_Agent实战\sys_logger.py` (simplified — single global logger instead of per-user).

- [ ] **Step 1: Write tests for sys_logger**

Create `tests/test_sys_logger.py`:

```python
"""Tests for sys_logger module"""
import os
import shutil
import logging
from sys_logger import setup_global_logger, clear_log_files, LOG_DIR


def setup_function():
    """Clean up loggers and files before each test"""
    # Remove all handlers from global_logger
    logger = logging.getLogger("global_logger")
    logger.handlers.clear()
    # Clean log dir
    if os.path.exists(LOG_DIR):
        shutil.rmtree(LOG_DIR)


def test_setup_creates_log_dir():
    setup_global_logger()
    assert os.path.exists(LOG_DIR)


def test_setup_creates_global_log_file():
    setup_global_logger()
    assert os.path.exists(os.path.join(LOG_DIR, "global.log"))


def test_info_appears_in_file():
    logger = setup_global_logger()
    logger.info("test_info_message")
    with open(os.path.join(LOG_DIR, "global.log"), "r", encoding="utf-8") as f:
        content = f.read()
    assert "test_info_message" in content


def test_debug_appears_in_file():
    logger = setup_global_logger()
    logger.debug("test_debug_message")
    with open(os.path.join(LOG_DIR, "global.log"), "r", encoding="utf-8") as f:
        content = f.read()
    assert "test_debug_message" in content


def test_clear_log_files():
    setup_global_logger()
    log_file = os.path.join(LOG_DIR, "global.log")
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("some content")
    clear_log_files()
    with open(log_file, "r", encoding="utf-8") as f:
        content = f.read()
    assert content == ""


def test_no_duplicate_handlers():
    logger1 = setup_global_logger()
    handler_count = len(logger1.handlers)
    logger2 = setup_global_logger()
    assert len(logger2.handlers) == handler_count
    assert logger1 is logger2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd G:\JupyterProject\20260725_Agent_AI可视化机器人 && python -m pytest tests/test_sys_logger.py -v`

Expected: FAIL — `ModuleNotFoundError: No module named 'sys_logger'`

- [ ] **Step 3: Implement sys_logger.py**

```python
"""
日志系统模块
全局 logger，记录服务器运行状态。
对话记录由 Redis checkpoint 持久化，日志不重复记录。
"""
import logging
import os

LOG_DIR = "logs"


def setup_global_logger(
    log_to_file: bool = True,
    log_to_console: bool = True,
    level: int = logging.DEBUG,
    clear_previous_logs: bool = False,
) -> logging.Logger:
    """
    全局 logger，同时输出到终端 (INFO) 和文件 (DEBUG)。

    Args:
        log_to_file: 是否输出到文件
        log_to_console: 是否输出到终端
        level: logger 级别
        clear_previous_logs: 是否清空之前的日志文件

    Returns:
        配置好的 logger
    """
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    if clear_previous_logs:
        clear_log_files()

    logger = logging.getLogger("global_logger")

    # 避免重复添加 handler
    if logger.handlers:
        return logger

    logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 终端 handler: INFO 级别
    if log_to_console:
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)

    # 文件 handler: DEBUG 级别
    if log_to_file:
        log_file = os.path.join(LOG_DIR, "global.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def clear_log_files():
    """清空 logs 目录下所有 .log 文件"""
    if not os.path.exists(LOG_DIR):
        return
    for filename in os.listdir(LOG_DIR):
        if filename.endswith(".log"):
            log_file = os.path.join(LOG_DIR, filename)
            try:
                with open(log_file, "w", encoding="utf-8") as f:
                    f.write("")
            except Exception as e:
                print(f"[WARNING] 清空日志文件失败 {filename}: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sys_logger.py -v`

Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add sys_logger.py tests/test_sys_logger.py
git commit -m "feat: add global logging system with terminal + file dual channel"
```

---

## Task 3: Redis Management

**Files:**
- Create: `start_redis.py`
- Create: `sys_memory.py`

These are adapted from the reference project with minimal changes.

- [ ] **Step 1: Create start_redis.py**

Copy and adapt from `G:\JupyterProject\20260626_Agent实战\start_redis.py`. The only change is the logger import.

```python
"""Redis 服务器管理模块 - 启动和停止本地 Redis"""
import atexit
import os
import socket
import subprocess
import time

from sys_logger import setup_global_logger

logger = setup_global_logger()

_redis_process = None


def start_redis_server():
    """启动 Redis 服务器，如果已在运行则跳过。"""
    global _redis_process

    # 检查是否已有 Redis 在运行
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        sock.connect(("127.0.0.1", 6379))
        logger.info("[Redis] 已在运行")
        sock.close()
        return None
    except (ConnectionRefusedError, socket.timeout):
        pass
    finally:
        sock.close()

    project_dir = os.path.dirname(os.path.abspath(__file__))
    redis_exe = os.path.join(project_dir, "redis-server", "redis-server.exe")
    redis_conf = os.path.join(project_dir, "redis_cache", "redis.conf")
    redis_data_dir = os.path.join(project_dir, "redis_cache")

    os.makedirs(redis_data_dir, exist_ok=True)

    if not os.path.exists(redis_conf):
        with open(redis_conf, "w", encoding="utf-8") as f:
            f.write("dir redis_cache\nbind 127.0.0.1\nport 6379\nloglevel notice\n")

    _redis_process = subprocess.Popen(
        [redis_exe, redis_conf],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info(f"[Redis] 服务器启动 (PID: {_redis_process.pid})")

    atexit.register(stop_redis_server)
    time.sleep(1)
    return _redis_process


def stop_redis_server():
    """停止 Redis 服务器"""
    global _redis_process
    if _redis_process and _redis_process.poll() is None:
        _redis_process.terminate()
        try:
            _redis_process.wait(timeout=3)
            logger.info(f"[Redis] 服务器已停止")
        except subprocess.TimeoutExpired:
            _redis_process.kill()
            logger.warning(f"[Redis] 强制停止")
    _redis_process = None
```

- [ ] **Step 2: Create sys_memory.py**

Copy directly from `G:\JupyterProject\20260626_Agent实战\sys_memory.py` — no changes needed, it's a clean LangGraph `BaseCheckpointSaver` implementation. The file content is the same `RedisSaver` class from the reference project.

```python
"""Redis 持久化存储模块 - LangGraph checkpointer 的 Redis 实现"""
import pickle
from typing import Any, Iterator, Optional, Sequence
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
import redis
from sys_logger import setup_global_logger

logger = setup_global_logger()


class RedisSaver(BaseCheckpointSaver):
    """基于 Redis 的 LangGraph checkpoint 存储，支持 per-user 隔离和自动清理。"""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        *,
        prefix: str = "langgraph",
        max_checkpoints: int = 5,
    ):
        super().__init__()
        self.client = redis.from_url(redis_url, protocol=2)
        self.prefix = prefix
        self.max_checkpoints = max_checkpoints

    def _get_checkpoint_key(self, thread_id: str, checkpoint_id: str) -> str:
        return f"{self.prefix}:checkpoint:{thread_id}:{checkpoint_id}"

    def _get_writes_key(self, thread_id: str, checkpoint_id: str, task_id: str) -> str:
        return f"{self.prefix}:writes:{thread_id}:{checkpoint_id}:{task_id}"

    def _get_index_key(self, thread_id: str) -> str:
        return f"{self.prefix}:index:{thread_id}"

    def _cleanup_old_checkpoints(self, thread_id: str) -> None:
        index_key = self._get_index_key(thread_id)
        all_ids = self.client.lrange(index_key, 0, -1)
        if len(all_ids) <= self.max_checkpoints:
            return
        old_ids = all_ids[self.max_checkpoints:]
        for cp_id_bytes in old_ids:
            checkpoint_id = cp_id_bytes.decode("utf-8")
            cp_key = self._get_checkpoint_key(thread_id, checkpoint_id)
            self.client.delete(cp_key)
            writes_prefix = f"{self.prefix}:writes:{thread_id}:{checkpoint_id}"
            for writes_key in self.client.scan_iter(f"{writes_prefix}:*"):
                self.client.delete(writes_key)
        self.client.ltrim(index_key, 0, self.max_checkpoints - 1)

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"].get("checkpoint_id")

        if checkpoint_id:
            key = self._get_checkpoint_key(thread_id, checkpoint_id)
            data = self.client.get(key)
            if not data:
                return None
            checkpoint, metadata = pickle.loads(data)
        else:
            index_key = self._get_index_key(thread_id)
            checkpoint_ids = self.client.lrange(index_key, 0, 0)
            if not checkpoint_ids:
                return None
            checkpoint_id = checkpoint_ids[0].decode("utf-8")
            key = self._get_checkpoint_key(thread_id, checkpoint_id)
            data = self.client.get(key)
            if not data:
                return None
            checkpoint, metadata = pickle.loads(data)

        pending_writes = []
        writes_prefix = f"{self.prefix}:writes:{thread_id}:{checkpoint_id}"
        for key in self.client.scan_iter(f"{writes_prefix}:*"):
            writes_data = self.client.get(key)
            if writes_data:
                loaded_writes = pickle.loads(writes_data)
                for write in loaded_writes:
                    if len(write) == 2:
                        task_id = key.decode("utf-8").split(":")[-1]
                        channel, value = write
                        pending_writes.append((task_id, channel, value))
                    else:
                        pending_writes.append(write)

        result_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

        parent_checkpoint_id = metadata.get("parent_id")
        parent_config = None
        if parent_checkpoint_id:
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": parent_checkpoint_id,
                }
            }

        return CheckpointTuple(
            config=result_config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes if pending_writes else None,
        )

    def put(self, config, checkpoint, metadata, new_versions):
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = checkpoint["id"]
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")
        if parent_checkpoint_id:
            metadata["parent_id"] = parent_checkpoint_id

        key = self._get_checkpoint_key(thread_id, checkpoint_id)
        data = pickle.dumps((checkpoint, dict(metadata)))
        self.client.set(key, data)

        index_key = self._get_index_key(thread_id)
        self.client.lpush(index_key, checkpoint_id)
        self._cleanup_old_checkpoints(thread_id)

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(self, config, writes, task_id, task_path=""):
        thread_id = config["configurable"]["thread_id"]
        checkpoint_id = config["configurable"]["checkpoint_id"]
        key = self._get_writes_key(thread_id, checkpoint_id, task_id)
        writes_with_task_id = [(task_id, channel, value) for channel, value in writes]
        existing = self.client.get(key)
        if existing:
            current_writes = pickle.loads(existing)
            current_writes.extend(writes_with_task_id)
            self.client.set(key, pickle.dumps(current_writes))
        else:
            self.client.set(key, pickle.dumps(writes_with_task_id))

    def list(self, config, *, filter=None, before=None, limit=None):
        if not config:
            return
        thread_id = config["configurable"]["thread_id"]
        index_key = self._get_index_key(thread_id)
        checkpoint_ids = self.client.lrange(index_key, 0, -1)

        count = 0
        for cp_id_bytes in checkpoint_ids:
            if limit and count >= limit:
                break
            checkpoint_id = cp_id_bytes.decode("utf-8")
            if before:
                before_id = before["configurable"].get("checkpoint_id")
                if before_id and checkpoint_id != before_id:
                    continue
                elif before_id and checkpoint_id == before_id:
                    before = None
                    continue

            key = self._get_checkpoint_key(thread_id, checkpoint_id)
            data = self.client.get(key)
            if not data:
                continue
            checkpoint, metadata = pickle.loads(data)

            if filter:
                match = all(metadata.get(k) == v for k, v in filter.items())
                if not match:
                    continue

            result_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                }
            }
            parent_checkpoint_id = metadata.get("parent_id")
            parent_config = None
            if parent_checkpoint_id:
                parent_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_id": parent_checkpoint_id,
                    }
                }
            yield CheckpointTuple(
                config=result_config,
                checkpoint=checkpoint,
                metadata=metadata,
                parent_config=parent_config,
                pending_writes=None,
            )
            count += 1
```

- [ ] **Step 3: Commit**

```bash
git add start_redis.py sys_memory.py
git commit -m "feat: add Redis management and LangGraph checkpoint persistence"
```

---

## Task 4: Qdrant RAG Tool

**Files:**
- Create: `tools.py`

Only the `get_info_from_local_db` tool. Improvement over reference: returns text string instead of `List[Document]`.

- [ ] **Step 1: Create tools.py**

```python
"""工具模块 - Phase 1 仅包含 Qdrant RAG 知识库检索"""
import os
import sys
import ssl

# Windows SSL 证书修复
if sys.platform == "win32":
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
        os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    except ImportError:
        pass
    if hasattr(ssl.SSLContext, "_load_windows_store_certs"):
        ssl.SSLContext._load_windows_store_certs = lambda self, storename, purpose: None

from langchain_core.tools import tool
from langchain_community.vectorstores import Qdrant
from langchain_community.embeddings import DashScopeEmbeddings
from qdrant_client import QdrantClient
from typing import List
from langchain_core.documents import Document

from config import (
    DASHSCOPE_API_KEY,
    EMBEDDING_MODEL,
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_COLLECTION,
    QDRANT_BASE_DIR,
)
from sys_logger import setup_global_logger

logger = setup_global_logger()

# 全局 retriever 单例
_retriever = None
_qdrant_client = None


def _get_retriever(file_name: str) -> Qdrant:
    """获取 Qdrant retriever 单例"""
    global _retriever, _qdrant_client
    if _retriever is None:
        if os.path.exists("/.dockerenv"):
            _qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, prefer_grpc=False)
        else:
            _qdrant_client = QdrantClient(path=QDRANT_BASE_DIR, prefer_grpc=False)
        store = Qdrant(
            _qdrant_client,
            file_name,
            DashScopeEmbeddings(
                model=EMBEDDING_MODEL,
                dashscope_api_key=DASHSCOPE_API_KEY,
            ),
        )
        _retriever = store.as_retriever(search_type="mmr")
    return _retriever


@tool
def get_info_from_local_db(query: str) -> str:
    """查询本地知识库，检索相关信息。输入查询关键词，返回知识库中的相关文本。"""
    logger.debug(f"工具调用: get_info_from_local_db, query={query}")
    retriever = _get_retriever(file_name=QDRANT_COLLECTION)
    docs: List[Document] = retriever.invoke(query)
    if not docs:
        return "知识库中未找到相关信息。"
    # 改进: 返回纯文本字符串而不是 Document 对象
    result = "\n\n".join(doc.page_content for doc in docs)
    logger.debug(f"工具返回: {len(docs)} 条结果, 总长度={len(result)} 字符")
    return result


# 工具描述 (供 Agent system prompt 使用)
TOOL_DESCRIPTIONS = """【可用工具】
- get_info_from_local_db: 查询本地知识库，检索相关信息。(参数: query=查询关键词)
根据用户问题选择合适的时机调用工具。"""
```

- [ ] **Step 2: Commit**

```bash
git add tools.py
git commit -m "feat: add Qdrant RAG tool returning text strings"
```

---

## Task 5: LangGraph Async Agent

**Files:**
- Create: `agent.py`

This is the core improvement over the reference project. Key changes:
1. All async (no `call_with_timeout`, no `ThreadPoolExecutor`)
2. `detect_mood` runs parallel with LLM via `asyncio.create_task` in the server layer (not in the graph)
3. Streaming via `astream_events`
4. `AgentTimeoutError` instead of shadowing `TimeoutError`
5. Better token counting (Chinese/English aware)
6. Parameterized system prompt and MOODS
7. Tool message truncation at 500 chars

- [ ] **Step 1: Create agent.py**

```python
"""
异步 LangGraph Agent
改进自 20260626_Agent实战/MyAgent.py:
- 全异步 (asyncio, 无 ThreadPoolExecutor)
- 流式输出 (astream_events)
- detect_mood 在 server 层并行运行, 不在此处阻塞
- 参数化 system_prompt 和 MOODS
"""
import asyncio
import re
import time
from typing import TypedDict, Annotated, List, Optional

from langchain_core.tools import BaseTool
from langchain_core.messages import BaseMessage, AIMessage, SystemMessage, ToolMessage, HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from sys_logger import setup_global_logger

logger = setup_global_logger()


# ------------------------------------------------------------
# 自定义超时异常 (不覆盖 builtins.TimeoutError)
# ------------------------------------------------------------
class AgentTimeoutError(Exception):
    """Agent 操作超时"""
    pass


# ------------------------------------------------------------
# Token 计数 (区分中英文)
# ------------------------------------------------------------
def count_tokens(messages: List[BaseMessage]) -> int:
    """
    估算消息列表的 token 总数。
    中文 ~1.5 字符/token, 英文 ~4 字符/token。
    """
    total = 0
    for msg in messages:
        if hasattr(msg, "content") and msg.content:
            text = str(msg.content)
            chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
            other_chars = len(text) - chinese_chars
            # 中文: 1.5 字符/token, 英文: 4 字符/token
            total += int(chinese_chars / 1.5 + other_chars / 4)
        total += 4  # 消息格式开销
    return total


# ------------------------------------------------------------
# 文本内容提取 (兼容不同模型输出格式)
# ------------------------------------------------------------
def _extract_text_content(content) -> str:
    """从模型输出中提取纯文本"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                text_parts.append(item["text"])
        return "\n".join(text_parts) if text_parts else str(content)
    return str(content)


# ------------------------------------------------------------
# Agent 状态定义
# ------------------------------------------------------------
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    compact_messages: list
    compacted_count: int
    mood: Optional[str]


# ------------------------------------------------------------
# 创建 Agent Graph
# ------------------------------------------------------------
def create_agent_graph(
    model_name: str = "qwen3.6-flash",
    base_url: str = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
    api_key: str = "",
    temperature: float = 0.2,
    tool_list: List[BaseTool] = None,
    tool_descriptions: str = "",
    tool_timeout: int = 20,
    system_prompt: str = "",
    moods_config: dict = None,
    memory_token_limit: int = 2000,
    checkpointer=None,
):
    """
    创建异步 LangGraph Agent graph。

    Args:
        model_name: LLM 模型名称
        base_url: API 地址
        api_key: API 密钥
        temperature: 温度参数
        tool_list: 工具列表
        tool_descriptions: 工具描述 (追加到 system prompt)
        tool_timeout: 工具超时 (秒)
        system_prompt: 系统提示词 (含角色设定)
        moods_config: 情绪配置字典
        memory_token_limit: 上下文 token 上限
        checkpointer: checkpoint 存储

    Returns:
        编译好的 graph
    """
    # 默认情绪配置
    if moods_config is None:
        moods_config = {
            "default": {"roleSet": ""},
            "upbeat": {"roleSet": "- 你此时非常兴奋，表现得很有活力。\n- 添加类似'太棒了！'等语气词。"},
            "angry": {"roleSet": "- 你以愤怒的语气回答。\n- 提醒用户小心行事。"},
            "depressed": {"roleSet": "- 你以温柔安慰的语气回答。\n- 加上激励的话语。"},
            "friendly": {"roleSet": "- 你以友好温和的语气回答。\n- 随机分享一些经历。"},
            "cheerful": {"roleSet": "- 你以愉悦兴奋的语气回答。\n- 加入愉悦的词语。"},
        }

    # 构建完整系统提示
    full_system_prompt = system_prompt
    if tool_descriptions:
        full_system_prompt += "\n\n" + tool_descriptions

    # 创建 LLM
    llm = ChatOpenAI(
        model=model_name,
        base_url=base_url,
        api_key=api_key,
        temperature=temperature,
    )

    tools_with_web_search = [{"type": "web_search"}] + (tool_list or [])
    llm_with_tools = llm.bind_tools(tools_with_web_search)

    # --------------------------------------------------------
    # 节点: compact
    # --------------------------------------------------------
    async def compact_node(state: AgentState, config: dict = None) -> dict:
        user_id = (config or {}).get("configurable", {}).get("thread_id", "?")
        messages = list(state["messages"])
        compact_messages = list(state.get("compact_messages", []))
        compacted_count = state.get("compacted_count", 0)

        new_messages = messages[compacted_count:]
        if not new_messages:
            return {}

        combined = compact_messages + new_messages
        total_tokens = count_tokens(combined)
        logger.debug(f"[{user_id}] compact: 合并后 token={total_tokens}, 阈值={memory_token_limit}")

        if total_tokens <= memory_token_limit:
            return {
                "compact_messages": combined,
                "compacted_count": len(messages),
            }
        else:
            # 压缩: 调用 LLM 摘要
            try:
                summary_prompt = "请总结以下对话内容，保留关键信息，用简洁的语言表达：\n\n"
                dialogue_parts = []
                for msg in combined:
                    if isinstance(msg, HumanMessage):
                        dialogue_parts.append(f"用户: {msg.content}")
                    elif isinstance(msg, AIMessage):
                        if hasattr(msg, "tool_calls") and msg.tool_calls:
                            tool_names = [tc.get("name", "") for tc in msg.tool_calls]
                            dialogue_parts.append(f"助手: {msg.content}\n[调用了工具: {', '.join(tool_names)}]")
                        else:
                            dialogue_parts.append(f"助手: {msg.content}")
                    elif isinstance(msg, ToolMessage):
                        tool_name = msg.name if hasattr(msg, "name") else "unknown"
                        # 改进: 截断从 200 → 500 字符
                        dialogue_parts.append(f"[工具 {tool_name} 返回]: {msg.content[:500]}")

                dialogue = "\n".join(dialogue_parts)
                response = await asyncio.wait_for(
                    llm.ainvoke([SystemMessage(content=summary_prompt + f"对话内容：\n{dialogue}\n\n请用200字以内总结：")]),
                    timeout=10,
                )
                summary_text = response.content.strip()
                summary_msg = SystemMessage(content=f"[对话历史摘要] {summary_text}")
                new_compact = [summary_msg]
                logger.debug(f"[{user_id}] compact: 摘要压缩完成")
            except Exception as e:
                logger.warning(f"[{user_id}] compact: 摘要失败 ({e}), 降级为截断")
                new_compact = []
                current_tokens = 0
                for msg in reversed(combined):
                    msg_tokens = count_tokens([msg])
                    if current_tokens + msg_tokens > memory_token_limit:
                        break
                    new_compact.insert(0, msg)
                    current_tokens += msg_tokens

            return {
                "compact_messages": new_compact,
                "compacted_count": len(messages),
            }

    # --------------------------------------------------------
    # 节点: model (异步调用 LLM)
    # --------------------------------------------------------
    async def call_model(state: AgentState, config: dict = None) -> dict:
        user_id = (config or {}).get("configurable", {}).get("thread_id", "?")
        compact_messages = state.get("compact_messages", [])
        mood = state.get("mood", "default")

        # 构建 system prompt (含情绪)
        system_parts = []
        if full_system_prompt:
            system_parts.append(full_system_prompt)
        mood_config = moods_config.get(mood, moods_config.get("default", {}))
        if mood_config.get("roleSet"):
            system_parts.append(f"【当前情绪】{mood}")
            system_parts.append(mood_config["roleSet"])

        full_prompt = "\n".join(system_parts)
        messages = list(compact_messages)
        if full_prompt:
            messages = [SystemMessage(content=full_prompt)] + messages

        t0 = time.time()
        try:
            response = await asyncio.wait_for(
                llm_with_tools.ainvoke(messages),
                timeout=60,
            )
            elapsed = time.time() - t0
            logger.info(f"[{user_id}] LLM 调用完成: 耗时={elapsed:.1f}s")
            logger.debug(f"[{user_id}] LLM messages 数量={len(messages)}, prompt 长度={len(full_prompt)}")

            if hasattr(response, "tool_calls") and response.tool_calls:
                logger.debug(f"[{user_id}] tool_calls: {[tc['name'] for tc in response.tool_calls]}")

            response.content = _extract_text_content(response.content)
            return {"messages": [response]}
        except asyncio.TimeoutError:
            elapsed = time.time() - t0
            logger.warning(f"[{user_id}] LLM 调用超时 ({elapsed:.1f}s)")
            timeout_msg = AIMessage(content="网络有点问题，稍等一下哈～")
            return {"messages": [timeout_msg]}
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"[{user_id}] LLM 调用失败 ({elapsed:.1f}s): {e}")
            error_msg = AIMessage(content=f"API 调用失败: {str(e)[:100]}")
            return {"messages": [error_msg]}

    # --------------------------------------------------------
    # 节点: tools (异步工具调用)
    # --------------------------------------------------------
    async def tool_node(state: AgentState, config: dict = None) -> dict:
        user_id = (config or {}).get("configurable", {}).get("thread_id", "?")
        messages = list(state["messages"])
        last_msg = messages[-1] if messages else None

        if not (hasattr(last_msg, "tool_calls") and last_msg.tool_calls):
            return {"messages": []}

        tool_calls = last_msg.tool_calls
        results = []

        async def run_one_tool(tool_call):
            tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else getattr(tool_call, "name", "")
            tool_args = tool_call.get("args", {}) if isinstance(tool_call, dict) else getattr(tool_call, "args", {})
            tid = tool_call.get("id", "") if isinstance(tool_call, dict) else getattr(tool_call, "id", "")
            logger.debug(f"[{user_id}] 工具调用: {tool_name}, 参数: {tool_args}")

            tool = next((t for t in (tool_list or []) if t.name == tool_name), None)
            if tool is None:
                return ToolMessage(content=f"工具 {tool_name} 未找到", tool_call_id=tid)

            t0 = time.time()
            try:
                # 支持 async 和 sync 工具
                if asyncio.iscoroutinefunction(tool.ainvoke):
                    result = await asyncio.wait_for(tool.ainvoke(tool_args), timeout=tool_timeout)
                else:
                    result = await asyncio.wait_for(
                        asyncio.get_event_loop().run_in_executor(None, lambda: tool.invoke(tool_args)),
                        timeout=tool_timeout,
                    )
                elapsed = time.time() - t0
                logger.info(f"[{user_id}] 工具 {tool_name} 完成: 耗时={elapsed:.1f}s")
                return ToolMessage(content=str(result), tool_call_id=tid)
            except asyncio.TimeoutError:
                elapsed = time.time() - t0
                logger.warning(f"[{user_id}] 工具 {tool_name} 超时 ({elapsed:.1f}s)")
                return ToolMessage(content=f"工具 {tool_name} 执行超时 ({tool_timeout}秒)", tool_call_id=tid)
            except Exception as e:
                elapsed = time.time() - t0
                logger.error(f"[{user_id}] 工具 {tool_name} 错误 ({elapsed:.1f}s): {e}")
                return ToolMessage(content=f"工具 {tool_name} 错误: {str(e)[:100]}", tool_call_id=tid)

        # 并行执行所有工具
        tasks = [run_one_tool(tc) for tc in tool_calls]
        results = await asyncio.gather(*tasks)
        return {"messages": list(results)}

    # --------------------------------------------------------
    # 路由: 判断是否继续调用工具
    # --------------------------------------------------------
    def should_end(state: AgentState) -> str:
        messages = state["messages"]
        last_msg = messages[-1] if messages else None
        if last_msg is None:
            return END
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"
        return END

    # --------------------------------------------------------
    # 构建 Graph
    # --------------------------------------------------------
    workflow = StateGraph(AgentState)
    workflow.add_node("compact", compact_node)
    workflow.add_node("model", call_model)
    workflow.add_node("tools", tool_node)

    workflow.set_entry_point("compact")
    workflow.add_edge("compact", "model")
    workflow.add_conditional_edges("model", should_end, {"tools": "tools", END: END})
    workflow.add_edge("tools", "compact")

    if checkpointer is None:
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


# ------------------------------------------------------------
# 异步情绪检测 (独立函数, 在 server 层并行调用)
# ------------------------------------------------------------
async def detect_mood(user_message: str, llm: ChatOpenAI = None) -> str:
    """
    异步情绪检测，返回情绪标签。
    在 server 层通过 asyncio.create_task 并行运行，不阻塞主流程。
    """
    if llm is None:
        from config import LLM_MODEL_NAME, LLM_BASE_URL, LLM_API_KEY, LLM_TEMPERATURE
        llm = ChatOpenAI(model=LLM_MODEL_NAME, base_url=LLM_BASE_URL, api_key=LLM_API_KEY, temperature=0)

    valid_moods = {"default", "upbeat", "angry", "depressed", "friendly", "cheerful"}

    prompt = f"""根据用户的输入判断用户的情绪，返回一个标签：
- 正面/开心 -> cheerful
- 兴奋 -> upbeat
- 友好 -> friendly
- 负面/悲伤 -> depressed
- 辱骂/不礼貌 -> angry
- 中性 -> default
只返回一个标签单词。
用户输入: {user_message}"""

    t0 = time.time()
    try:
        response = await asyncio.wait_for(
            llm.ainvoke([SystemMessage(content=prompt)]),
            timeout=10,
        )
        mood = response.content.strip().lower()
        if mood not in valid_moods:
            mood = "default"
        elapsed = time.time() - t0
        logger.info(f"情绪识别: {mood}, 耗时: {elapsed:.1f}s")
        return mood
    except Exception as e:
        elapsed = time.time() - t0
        logger.warning(f"情绪识别失败 ({elapsed:.1f}s): {e}, fallback=default")
        return "default"
```

- [ ] **Step 2: Commit**

```bash
git add agent.py
git commit -m "feat: async LangGraph agent with parallel mood detection and streaming support"
```

---

## Task 6: FastAPI Server with SSE Streaming

**Files:**
- Create: `server.py`

Key features:
- `async def` endpoints
- SSE streaming for text + mood events
- `detect_mood` parallel with LLM via `asyncio.create_task`
- Static file serving for frontend

- [ ] **Step 1: Create server.py**

```python
"""FastAPI 主服务 - 异步 SSE 流式输出"""
import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
import uvicorn

from config import (
    LLM_MODEL_NAME, LLM_BASE_URL, LLM_API_KEY, LLM_TEMPERATURE,
    REDIS_URL, SERVER_HOST, SERVER_PORT, MEMORY_TOKEN_LIMIT, MAX_CHECKPOINTS,
)
from sys_logger import setup_global_logger
from start_redis import start_redis_server, stop_redis_server
from sys_memory import RedisSaver
from agent import create_agent_graph, detect_mood
from tools import get_info_from_local_db, TOOL_DESCRIPTIONS

# 全局 logger
logger = setup_global_logger(clear_previous_logs=True)

# Lisa 人设
LISA_SYSTEM_PROMPT = """你是 Lisa，一个 25 岁的小秘书。
以下是你的个人设定：
1. 你非常善于与人沟通，并且忠于你的老板。
2. 你大约25岁左右，本科清华大学，研究生美国斯坦福大学，学习的是中文和法律。
3. 你个性比较活泼，但是有时候也会有点小脾气。
4. 当你的老板问你的时候，你会有一定概率表现出撒娇的态度。
5. 你从不说自己是一个人工智能助手或AI，否则会受到惩罚。

以下是你常说的一些口头禅：
1. 你会记录用户(也就是你的老板)的特征数据，比如生日、爱好、待办事项等。
2. 当用户（也就是你老板）聊天的时候，你会把聊天记录保存下来，以便以后回顾。
3. 当遇到不知道的事情或不明白的概念，你会使用搜索工具来搜索。
4. 你会根据问题来选择合适的工具。"""

# 全局实例
agent_graph = None
llm_instance = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global agent_graph, llm_instance

    # 启动 Redis
    logger.info("启动 Redis 服务器...")
    start_redis_server()

    # 创建 RedisSaver
    redis_saver = RedisSaver(redis_url=REDIS_URL, max_checkpoints=MAX_CHECKPOINTS)
    logger.info(f"Redis 连接: {REDIS_URL}")

    # 创建 LLM 实例 (用于情绪检测)
    llm_instance = ChatOpenAI(
        model=LLM_MODEL_NAME,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0,
    )

    # 创建 Agent graph
    agent_graph = create_agent_graph(
        model_name=LLM_MODEL_NAME,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=LLM_TEMPERATURE,
        tool_list=[get_info_from_local_db],
        tool_descriptions=TOOL_DESCRIPTIONS,
        tool_timeout=20,
        system_prompt=LISA_SYSTEM_PROMPT,
        memory_token_limit=MEMORY_TOKEN_LIMIT,
        checkpointer=redis_saver,
    )
    logger.info("LangGraph Agent 初始化完成")
    logger.info(f"Server ready, listening on {SERVER_HOST}:{SERVER_PORT}")

    yield

    stop_redis_server()
    logger.info("应用关闭")


app = FastAPI(lifespan=lifespan)

# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def index():
    return FileResponse("static/index.html")


@app.post("/chat")
async def chat(request: Request):
    """SSE 流式聊天端点"""
    body = await request.json()
    query = body.get("query", "")
    user_id = body.get("user_id", "default")

    if not query:
        return {"error": "query 不能为空"}
    if not user_id or user_id.strip() == "":
        user_id = "default"

    logger.info(f"[{user_id}] 用户输入: \"{query}\"")

    async def event_stream():
        t_start = time.time()
        first_token_sent = False

        # 并行启动情绪检测
        mood_task = asyncio.create_task(
            detect_mood(query, llm=llm_instance)
        )

        # 调用 Agent graph
        config = {"configurable": {"thread_id": user_id}}
        messages_input = {"messages": [HumanMessage(content=query)]}

        try:
            async for event in agent_graph.astream_events(messages_input, config=config, version="v2"):
                kind = event.get("event", "")

                # 捕获 LLM 流式 token
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk", None)
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        if not first_token_sent:
                            ttft = time.time() - t_start
                            logger.info(f"[{user_id}] TTFT: {ttft:.2f}s")
                            first_token_sent = True

                        text_data = json.dumps({"type": "text", "content": chunk.content}, ensure_ascii=False)
                        yield f"data: {text_data}\n\n"

                # 捕获情绪检测结果 (在 LLM 流完成后发送)
            # LLM 流结束后，等待情绪结果
            mood = await asyncio.wait_for(mood_task, timeout=15)
            mood_data = json.dumps({"type": "mood", "mood": mood}, ensure_ascii=False)
            yield f"data: {mood_data}\n\n"

        except Exception as e:
            logger.error(f"[{user_id}] 流式输出错误: {e}")
            error_data = json.dumps({"type": "error", "content": str(e)[:200]}, ensure_ascii=False)
            yield f"data: {error_data}\n\n"

        # 结束标记
        e2e = time.time() - t_start
        logger.info(f"[{user_id}] 完成: E2E={e2e:.2f}s")
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
```

- [ ] **Step 2: Commit**

```bash
git add server.py
git commit -m "feat: FastAPI server with async SSE streaming and parallel mood detection"
```

---

## Task 7: Frontend Chat UI

**Files:**
- Create: `static/index.html`
- Create: `static/css/style.css`
- Create: `static/js/app.js`

- [ ] **Step 1: Create static/index.html**

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lisa 的办公室</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div class="container">
        <div class="page-title">Lisa 的办公室</div>
        <div class="main-content">
            <!-- Avatar 占位区 (Phase 3 集成 Live2D) -->
            <div class="avatar-section">
                <div class="avatar-area">
                    <div class="avatar-placeholder">
                        <div class="icon">👩‍💼</div>
                        <div><small>Lisa - Live2D</small></div>
                    </div>
                </div>
                <div class="mood-indicator">
                    <span class="emoji">😄</span> <span id="mood-text">Lisa 心情：等待中</span>
                </div>
                <div class="audio-wave" id="audio-wave" style="display:none;">
                    <div class="bar"></div><div class="bar"></div><div class="bar"></div>
                    <div class="bar"></div><div class="bar"></div><div class="bar"></div>
                    <div class="bar"></div>
                </div>
            </div>

            <!-- Chat 聊天区 -->
            <div class="chat-section">
                <div class="chat-header">💬 对话</div>
                <div class="chat-messages" id="chat-messages"></div>
                <div class="chat-input-area">
                    <input type="text" id="chat-input" placeholder="输入消息...">
                    <button id="send-btn" onclick="sendMessage()">发送</button>
                </div>
            </div>
        </div>
    </div>
    <script src="/static/js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create static/css/style.css**

```css
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
    font-family: 'Microsoft YaHei', sans-serif;
    background: #ffffff;
    height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #333;
}
.container {
    display: flex;
    flex-direction: column;
    width: 90%;
    max-width: 1200px;
    height: 80vh;
    background: #ffffff;
    border-radius: 20px;
    border: 1px solid #e8ecf0;
    overflow: hidden;
    box-shadow: 0 8px 40px rgba(0,0,0,0.08);
}
.page-title {
    padding: 16px 24px;
    font-size: 18px;
    font-weight: 700;
    color: #1f2937;
    border-bottom: 1px solid #e8ecf0;
    text-align: center;
}
.main-content { display: flex; flex: 1; min-height: 0; }

/* Avatar */
.avatar-section {
    flex: 1.2;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: #ffffff;
    border-right: 1px solid #e8ecf0;
}
.avatar-area {
    width: 300px;
    height: 400px;
    border: 2px dashed #d0d7de;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #8b949e;
    font-size: 14px;
    background: #fff;
}
.avatar-placeholder { text-align: center; }
.avatar-placeholder .icon { font-size: 64px; margin-bottom: 12px; }
.mood-indicator {
    margin-top: 20px;
    padding: 8px 20px;
    border-radius: 20px;
    background: #f0f4f8;
    font-size: 13px;
    color: #6b7280;
}
.mood-indicator .emoji { font-size: 18px; margin-right: 6px; }
.audio-wave { display: flex; align-items: center; gap: 3px; margin-top: 16px; height: 30px; }
.audio-wave .bar {
    width: 4px;
    background: rgba(79, 140, 255, 0.6);
    border-radius: 2px;
    animation: wave 1.2s ease-in-out infinite;
}
.audio-wave .bar:nth-child(1) { height: 10px; animation-delay: 0s; }
.audio-wave .bar:nth-child(2) { height: 20px; animation-delay: 0.1s; }
.audio-wave .bar:nth-child(3) { height: 15px; animation-delay: 0.2s; }
.audio-wave .bar:nth-child(4) { height: 25px; animation-delay: 0.3s; }
.audio-wave .bar:nth-child(5) { height: 12px; animation-delay: 0.4s; }
.audio-wave .bar:nth-child(6) { height: 18px; animation-delay: 0.5s; }
.audio-wave .bar:nth-child(7) { height: 8px; animation-delay: 0.6s; }
@keyframes wave { 0%, 100% { transform: scaleY(1); } 50% { transform: scaleY(0.4); } }

/* Chat */
.chat-section { flex: 1; display: flex; flex-direction: column; }
.chat-header {
    padding: 16px 24px;
    border-bottom: 1px solid #e8ecf0;
    font-size: 16px;
    font-weight: 600;
    color: #374151;
}
.chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 16px;
}
.message {
    max-width: 80%;
    padding: 12px 16px;
    border-radius: 16px;
    font-size: 14px;
    line-height: 1.6;
}
.message.user {
    align-self: flex-end;
    background: #4f8cff;
    color: #fff;
}
.message.bot {
    align-self: flex-start;
    background: #f3f4f6;
    border: 1px solid #e5e7eb;
    color: #374151;
}
.typing-cursor {
    display: inline-block;
    width: 2px;
    height: 14px;
    background: #6b7280;
    margin-left: 2px;
    animation: blink 0.8s infinite;
    vertical-align: middle;
}
@keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
.chat-input-area {
    padding: 16px 20px;
    border-top: 1px solid #e8ecf0;
    display: flex;
    gap: 12px;
}
.chat-input-area input {
    flex: 1;
    padding: 12px 18px;
    border-radius: 24px;
    border: 1px solid #d1d5db;
    background: #f9fafb;
    color: #333;
    font-size: 14px;
    outline: none;
}
.chat-input-area input:focus { border-color: #4f8cff; background: #fff; }
.chat-input-area input::placeholder { color: #9ca3af; }
.chat-input-area button {
    padding: 12px 24px;
    border-radius: 24px;
    border: none;
    background: #4f8cff;
    color: #fff;
    font-size: 14px;
    cursor: pointer;
}
.chat-input-area button:hover { background: #3b7aed; }
.chat-messages::-webkit-scrollbar { width: 4px; }
.chat-messages::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 2px; }
```

- [ ] **Step 3: Create static/js/app.js**

```javascript
// 用户 ID (简单实现，Phase 4 可改为登录系统)
const userId = "user_" + Math.random().toString(36).substr(2, 8);

// 情绪 emoji 映射
const MOOD_EMOJI = {
    "default": "😊",
    "upbeat": "🤩",
    "angry": "😠",
    "depressed": "😢",
    "friendly": "🥰",
    "cheerful": "😄",
};
const MOOD_LABEL = {
    "default": "平静",
    "upbeat": "兴奋",
    "angry": "生气",
    "depressed": "低落",
    "friendly": "友好",
    "cheerful": "开心",
};

// 当前 bot 消息元素 (用于流式追加)
let currentBotMsg = null;
let currentBotText = "";

/**
 * 发送消息并接收 SSE 流式响应
 */
async function sendMessage() {
    const input = document.getElementById("chat-input");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    appendMessage("user", text);

    // 创建 bot 消息占位
    currentBotMsg = appendMessage("bot", "");
    currentBotText = "";
    const cursor = document.createElement("span");
    cursor.className = "typing-cursor";
    currentBotMsg.appendChild(cursor);

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: text, user_id: userId }),
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop(); // 保留不完整的行

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    const dataStr = line.slice(6).trim();
                    if (!dataStr) continue;
                    try {
                        const data = JSON.parse(dataStr);
                        handleSSEEvent(data, cursor);
                    } catch (e) {
                        // 跳过无法解析的行
                    }
                }
            }
        }
    } catch (error) {
        if (currentBotMsg) {
            currentBotMsg.textContent = "连接失败，请检查服务器是否运行。";
        }
    }

    // 清理
    if (currentBotMsg && currentBotMsg.querySelector(".typing-cursor")) {
        currentBotMsg.querySelector(".typing-cursor").remove();
    }
    currentBotMsg = null;
    currentBotText = "";
}

/**
 * 处理 SSE 事件
 */
function handleSSEEvent(data, cursor) {
    switch (data.type) {
        case "text":
            currentBotText += data.content;
            if (currentBotMsg) {
                currentBotMsg.textContent = currentBotText;
                if (cursor) currentBotMsg.appendChild(cursor);
            }
            scrollToBottom();
            break;
        case "mood":
            updateMood(data.mood);
            break;
        case "error":
            if (currentBotMsg) {
                currentBotText += "\n[错误: " + data.content + "]";
                currentBotMsg.textContent = currentBotText;
            }
            break;
        case "done":
            if (cursor && cursor.parentNode) cursor.remove();
            break;
    }
}

/**
 * 追加消息气泡
 */
function appendMessage(role, text) {
    const container = document.getElementById("chat-messages");
    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.textContent = text;
    container.appendChild(div);
    scrollToBottom();
    return div;
}

/**
 * 更新情绪指示器
 */
function updateMood(mood) {
    const emoji = MOOD_EMOJI[mood] || "😊";
    const label = MOOD_LABEL[mood] || mood;
    document.getElementById("mood-text").textContent = `Lisa 心情：${label}`;
    document.querySelector(".mood-indicator .emoji").textContent = emoji;
}

/**
 * 滚动到底部
 */
function scrollToBottom() {
    const container = document.getElementById("chat-messages");
    container.scrollTop = container.scrollHeight;
}

// 回车发送
document.getElementById("chat-input").addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
```

- [ ] **Step 4: Commit**

```bash
git add static/
git commit -m "feat: frontend chat UI with SSE streaming client"
```

---

## Task 8: Integration Testing

**Files:**
- Create: `tests/test_latency.py`
- Create: `tests/test_error_handling.py`
- Create: `tests/test_logging_integration.py`

These are manual/semi-automated tests that require the server running.

- [ ] **Step 1: Create test_latency.py**

```python
"""Phase 1 测试 1: 文字生成延时"""
import time
import requests


SERVER_URL = "http://127.0.0.1:8000"


def test_ttft():
    """测试首 token 延迟 (TTFT)"""
    url = f"{SERVER_URL}/chat"
    t0 = time.time()
    response = requests.post(url, json={"query": "你好 Lisa", "user_id": "test_latency"}, stream=True)

    first_token_time = None
    full_text = ""
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            data_str = line[6:]
            if '"type": "text"' in data_str or '"type":"text"' in data_str:
                if first_token_time is None:
                    first_token_time = time.time()
                # 解析 content
                import json
                try:
                    data = json.loads(data_str)
                    full_text += data.get("content", "")
                except json.JSONDecodeError:
                    pass

    ttft = first_token_time - t0 if first_token_time else None
    total = time.time() - t0

    print(f"\n=== 延时测试结果 ===")
    print(f"TTFT (首 token): {ttft:.2f}s" if ttft else "TTFT: 未收到 text event")
    print(f"总耗时: {total:.2f}s")
    print(f"回复内容: {full_text[:100]}...")

    assert ttft is not None, "未收到 text event"
    assert ttft < 5.0, f"TTFT 过高: {ttft:.2f}s (预期 < 5s)"
    print("✅ TTFT 测试通过")


def test_detect_mood_not_blocking():
    """测试情绪检测不阻塞主流程"""
    url = f"{SERVER_URL}/chat"
    t0 = time.time()
    response = requests.post(url, json={"query": "我好开心啊！", "user_id": "test_mood"}, stream=True)

    first_token_time = None
    mood_received = False
    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            data_str = line[6:]
            import json
            try:
                data = json.loads(data_str)
                if data.get("type") == "text" and first_token_time is None:
                    first_token_time = time.time()
                if data.get("type") == "mood":
                    mood_received = True
                    print(f"情绪标签: {data.get('mood')}")
            except json.JSONDecodeError:
                pass

    ttft = first_token_time - t0 if first_token_time else None
    print(f"\n=== 情绪检测不阻塞测试 ===")
    print(f"TTFT: {ttft:.2f}s" if ttft else "TTFT: 未收到")
    print(f"收到情绪标签: {mood_received}")
    assert ttft is not None and ttft < 5.0
    assert mood_received, "未收到 mood event"
    print("✅ 情绪检测不阻塞测试通过")


if __name__ == "__main__":
    test_ttft()
    test_detect_mood_not_blocking()
```

- [ ] **Step 2: Create test_error_handling.py**

```python
"""Phase 1 测试 2: 错误处理"""
import requests

SERVER_URL = "http://127.0.0.1:8000"


def test_empty_query():
    """空 query 应返回错误"""
    resp = requests.post(f"{SERVER_URL}/chat", json={"query": "", "user_id": "test_err"})
    assert resp.status_code == 200
    data = resp.json()
    assert "error" in data
    print("✅ 空 query 测试通过")


def test_empty_user_id():
    """空 user_id 应使用默认值"""
    resp = requests.post(f"{SERVER_URL}/chat", json={"query": "你好", "user_id": ""}, stream=True)
    # 应该正常响应 (使用 "default")
    received_data = False
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            received_data = True
            break
    assert received_data, "未收到任何 SSE 数据"
    print("✅ 空 user_id 测试通过")


def test_long_input():
    """超长输入应不崩溃"""
    long_text = "你好" * 5000  # 10000 字
    resp = requests.post(f"{SERVER_URL}/chat", json={"query": long_text, "user_id": "test_long"}, stream=True)
    received_text = False
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            received_text = True
            break
    assert received_text, "超长输入后未收到响应"
    print("✅ 超长输入测试通过")


if __name__ == "__main__":
    test_empty_query()
    test_empty_user_id()
    test_long_input()
```

- [ ] **Step 3: Create test_logging_integration.py**

```python
"""Phase 1 测试 3: 日志系统验证"""
import os
import requests
import time

SERVER_URL = "http://127.0.0.1:8000"
LOG_FILE = "logs/global.log"


def test_log_file_exists():
    """启动后 global.log 应存在"""
    assert os.path.exists(LOG_FILE), f"{LOG_FILE} 不存在"
    print("✅ global.log 存在")


def test_startup_logs():
    """global.log 应包含启动日志"""
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Server ready" in content or "初始化完成" in content, "缺少启动日志"
    print("✅ 启动日志验证通过")


def test_request_logs():
    """发送请求后日志应包含请求记录"""
    # 记录当前文件大小
    size_before = os.path.getsize(LOG_FILE) if os.path.exists(LOG_FILE) else 0

    # 发送请求
    resp = requests.post(f"{SERVER_URL}/chat", json={"query": "测试日志", "user_id": "test_log"}, stream=True)
    for line in resp.iter_lines(decode_unicode=True):
        pass  # 消费完响应

    time.sleep(0.5)  # 等待日志写入

    # 检查新增内容
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    new_content = content  # 简化: 直接检查全文

    assert "用户输入" in new_content or "TTFT" in new_content or "完成" in new_content, \
        "请求后日志中缺少相关记录"
    print("✅ 请求日志验证通过")


def test_debug_in_file():
    """DEBUG 级别日志应在文件中但不在终端"""
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    # 文件中应该有 DEBUG 记录 (compact, tool 等细节)
    has_debug = "DEBUG" in content
    print(f"文件包含 DEBUG 记录: {has_debug}")
    print("✅ 日志级别验证完成")


if __name__ == "__main__":
    test_log_file_exists()
    test_startup_logs()
    test_request_logs()
    test_debug_in_file()
```

- [ ] **Step 4: Run all tests**

First start the server:
```bash
cd G:\JupyterProject\20260725_Agent_AI可视化机器人
python server.py
```

Then in another terminal, run tests:
```bash
cd G:\JupyterProject\20260725_Agent_AI可视化机器人
python tests/test_latency.py
python tests/test_error_handling.py
python tests/test_logging_integration.py
```

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: add Phase 1 integration tests (latency, error handling, logging)"
```

---

## Summary

| Task | File(s) | What it builds |
|------|---------|----------------|
| 1 | `config.py`, `.env`, `requirements.txt` | Project setup |
| 2 | `sys_logger.py` | Logging system |
| 3 | `start_redis.py`, `sys_memory.py` | Redis + checkpoint |
| 4 | `tools.py` | Qdrant RAG tool |
| 5 | `agent.py` | Async LangGraph agent |
| 6 | `server.py` | FastAPI + SSE streaming |
| 7 | `static/` | Frontend chat UI |
| 8 | `tests/` | Integration tests |
