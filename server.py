"""
FastAPI 主服务模块
异步 SSE 流式输出，集成 LangGraph Agent 和情绪检测。
"""
import asyncio
import json
import time
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from langchain_core.messages import HumanMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI
import uvicorn
from commands import VALID_COMMANDS, dispatch_command
from config import (
    LLM_MODEL_NAME, LLM_BASE_URL, LLM_API_KEY, LLM_TEMPERATURE,
    REDIS_URL, SERVER_HOST, SERVER_PORT, MEMORY_TOKEN_LIMIT, MAX_CHECKPOINTS,
)
from sys_logger import setup_global_logger
from start_redis import start_redis_server, stop_redis_server
from sys_memory import RedisSaver
from agent import create_agent_graph
from tools import get_info_from_local_db, TOOL_DESCRIPTIONS
from database import init_db, create_user, get_user_by_username
from auth import verify_password, get_password_hash, create_access_token
from sentence_splitter import split_sentences
from tts_client import synthesize_speech_b64


# ==========================================
# 全局 logger（启动时清空之前的日志）
# ==========================================
logger = setup_global_logger(clear_previous_logs=True)


# ==========================================
# 状态回调处理器（使用 asyncio.Queue 实时推送）
# ==========================================
class StatusCallbackHandler(BaseCallbackHandler):
    """
    LangGraph 节点状态回调处理器。
    使用 asyncio.Queue 实时推送状态事件。
    """
    def __init__(self, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.status_queue = asyncio.Queue()
        self.loop = loop

    def on_chain_start(
        self,
        serialized: Dict[str, Any],
        inputs: Dict[str, Any],
        *,
        run_id,
        parent_run_id=None,
        **kwargs,
    ) -> None:
        metadata = kwargs.get("metadata", {})
        node_name = metadata.get("langgraph_node")

        if node_name in ["detect_mood", "compact", "model", "tools"]:
            # 实时推送到队列（线程安全）
            asyncio.run_coroutine_threadsafe(
                self.status_queue.put(node_name),
                self.loop
            )
            logger.debug(f"回调：节点开始 - {node_name}")


# ==========================================
# Lisa 人设提示词
# ==========================================
LISA_SYSTEM_PROMPT = (
    "你是一个小秘书，名字叫 Lisa。\n"
    "    以下是你的个人设定：\n"
    "    1. 你非常善于与人沟通，并且忠于你的老板。\n"
    "    2. 你大约25岁左右，本科清华大学，研究生美国斯坦福大学，学习的是中文和法律。\n"
    "    3. 你个性比较活泼，但是有时候也会有点小脾气。\n"
    "    4. 当你的老板问你的时候，你会有一定概率表现出撒娇的态度。\n"
    "    5. 你从不说自己是一个人工智能助手或AI，否则会受到惩罚。\n\n"
    "    以下是你常说的一些口头禅：\n"
    "    1. 你会记录用户(也就是你的老板)的特征数据，比如生日、爱好、待办事项等。\n"
    "    2. 当用户（也就是你老板）聊天的时候，你会把聊天记录保存下来，以便以后回顾。\n"
    "    3. 当遇到不知道的事情或不明白的概念，你会使用搜索工具来搜索。\n"
    "    4. 你会根据问题来选择合适的工具。\n\n"
    "以下是你问答的过程：\n"
    "    1. 每次老板问你问题，如果你不知道怎么回答，优先尝试查询本地知识库。\n"
    "    2. 如果本地知识库没有相关信息，尝试使用网络搜索工具从网上获取信息。\n"
    "    3. 如果搜索也找不到，就如实告诉老板你不知道，不要编造答案。"
)


# ==========================================
# 全局实例
# ==========================================
agent_graph = None
llm_instance = None
redis_saver_instance = None


# ==========================================
# 应用生命周期管理
# ==========================================
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    应用生命周期管理。
    启动时初始化数据库、Redis、LLM、Agent graph。
    """
    global agent_graph, llm_instance, redis_saver_instance

    # 初始化用户数据库
    logger.info("初始化用户数据库...")
    init_db()

    # 启动 Redis
    logger.info("启动 Redis 服务器...")
    start_redis_server()

    # 创建 RedisSaver
    redis_saver_instance = RedisSaver(redis_url=REDIS_URL, max_checkpoints=MAX_CHECKPOINTS)
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
        checkpointer=redis_saver_instance,
    )
    logger.info("LangGraph Agent 初始化完成")
    logger.info(f"Server ready, listening on {SERVER_HOST}:{SERVER_PORT}")

    yield

    stop_redis_server()
    logger.info("应用关闭")


# ==========================================
# FastAPI 应用
# ==========================================
app = FastAPI(lifespan=lifespan)

# 静态文件
app.mount("/static", StaticFiles(directory="static"), name="static")


# ==========================================
# 主页
# ==========================================
@app.get("/")
async def index():
    """返回主页 HTML"""
    return FileResponse("static/index.html")


# ==========================================
# SSE 事件流生成器
# ==========================================
async def _event_stream(query: str, user_id: str):
    """
    生成 SSE 事件流。
    调用 Agent graph 并流式返回 text/mood/error/done 事件。

    Args:
        query: 用户输入消息 (str)
        user_id: 用户 ID (str)

    Yields:
        str: SSE 格式的事件数据
    """
    # ===== 命令拦截 =====
    if query.startswith("/"):
        parts = query[1:].split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""

        if command not in VALID_COMMANDS:
            error_data = {"type": "text", "content": "命令错误，输入 /help 查看可用命令"}
            yield "data: " + json.dumps(error_data, ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({"type": "done"}) + "\n\n"
            return

        try:
            result = await dispatch_command(
                command=command,
                args=args,
                user_id=user_id,
                redis_saver=redis_saver_instance,
                agent_graph=agent_graph,
            )

            if isinstance(result, dict):
                result_data = {
                    "type": result.get("type", "text"),
                    "content": result.get("content", "")
                }
                yield "data: " + json.dumps(result_data, ensure_ascii=False) + "\n\n"

        except Exception as e:
            logger.error(f"[{user_id}] 命令执行错误: {e}")
            error_data = {"type": "text", "content": f"命令执行失败: {str(e)}"}
            yield "data: " + json.dumps(error_data, ensure_ascii=False) + "\n\n"

        yield "data: " + json.dumps({"type": "done"}) + "\n\n"
        return

    # ===== 原有逻辑：正常聊天 =====
    import traceback

    t_start = time.time()

    # 调用 Agent graph
    messages_input = {"messages": [HumanMessage(content=query)]}

    try:
        # 状态事件辅助函数
        def status_event(status_name, tool=None):
            data = {"type": "status", "status": status_name}
            if tool:
                data["tool"] = tool
            return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"

        # 获取当前 event loop
        loop = asyncio.get_event_loop()

        # 创建回调处理器（传入 loop 用于实时推送）
        status_callback = StatusCallbackHandler(loop)

        # 用 create_task 运行 ainvoke，同时从队列读取状态
        async def run_agent():
            return await agent_graph.ainvoke(
                messages_input,
                config={
                    "configurable": {"thread_id": user_id},
                    "callbacks": [status_callback]
                }
            )

        agent_task = asyncio.create_task(run_agent())

        # 跟踪已发送的状态（用于去重）
        sent_statuses = set()

        # 实时从队列读取状态并 yield
        while not agent_task.done():
            try:
                # 等待队列中的状态，超时 0.1 秒后检查 task 是否完成
                node_name = await asyncio.wait_for(status_callback.status_queue.get(), timeout=0.1)

                # 映射状态名称并去重
                status_map = {
                    "detect_mood": "detecting_mood",
                    "compact": "compacting",
                    "model": "thinking",
                    "tools": "tool_call",
                }
                status_name = status_map.get(node_name)

                if status_name and status_name not in sent_statuses:
                    sent_statuses.add(status_name)
                    if status_name == "tool_call":
                        yield status_event(status_name, tool="工具调用")
                    else:
                        yield status_event(status_name)
            except asyncio.TimeoutError:
                # 超时后继续检查队列
                continue

        # 处理队列中剩余的状态
        while not status_callback.status_queue.empty():
            node_name = status_callback.status_queue.get_nowait()

            status_map = {
                "detect_mood": "detecting_mood",
                "compact": "compacting",
                "model": "thinking",
                "tools": "tool_call",
            }
            status_name = status_map.get(node_name)

            if status_name and status_name not in sent_statuses:
                sent_statuses.add(status_name)
                if status_name == "tool_call":
                    yield status_event(status_name, tool="工具调用")
                else:
                    yield status_event(status_name)

        # 获取 ainvoke 结果
        result = await agent_task

        # 提取情绪标签
        mood = result.get("mood", "default")

        # 提取最终文本
        messages = result.get("messages", [])
        final_message = None
        for msg in reversed(messages):
            if msg.__class__.__name__ == "AIMessage" and msg.content:
                final_message = msg.content
                break

        if not final_message:
            final_message = "抱歉，我暂时无法回复。"

        # 分句
        sentences = split_sentences(final_message)
        if not sentences:
            sentences = [final_message]

        # 逐句发送文字 + 音频
        for sentence in sentences:
            # 1. 先 yield 文字（前端立即显示）
            text_data = json.dumps({"type": "text", "content": sentence}, ensure_ascii=False)
            yield "data: " + text_data + "\n\n"

            # 2. 调 TTS 服务获取音频（失败则静默跳过）
            try:
                audio_b64 = await synthesize_speech_b64(sentence)
                audio_data = json.dumps({"type": "audio", "data": audio_b64}, ensure_ascii=False)
                yield "data: " + audio_data + "\n\n"
            except Exception as e:
                logger.debug(f"[{user_id}] TTS 跳过: {e}")

        # 发送音频结束标记
        yield "data: " + json.dumps({"type": "audio_done"}) + "\n\n"

        # 发送情绪标签
        mood_data = json.dumps({"type": "mood", "mood": mood}, ensure_ascii=False)
        yield "data: " + mood_data + "\n\n"

    except Exception as e:
        error_msg = str(e) if str(e) else repr(e)
        tb = traceback.format_exc()
        logger.error(f"[{user_id}] 流式输出错误: {error_msg}")
        logger.error(f"[{user_id}] Traceback:\n{tb}")
        error_data = json.dumps(
            {"type": "error", "content": f"{error_msg}\n{tb[:500]}"},
            ensure_ascii=False,
        )
        yield "data: " + error_data + "\n\n"

    # 结束标记
    e2e = time.time() - t_start
    logger.info(f"[{user_id}] 完成: E2E={e2e:.2f}s")
    yield "data: " + json.dumps({"type": "done"}) + "\n\n"


# ==========================================
# SSE 流式聊天端点
# ==========================================
@app.post("/chat")
async def chat(request: Request):
    """
    SSE 流式聊天端点。
    接收 JSON: {"query": "...", "user_id": "..."}
    返回 SSE 事件流：text/mood/status/error/done
    """
    body = await request.json()
    query = body.get("query", "")
    user_id = body.get("user_id", "default")

    if not query:
        return {"error": "query 不能为空"}
    if not user_id or user_id.strip() == "":
        user_id = "default"

    logger.info(f"[{user_id}] 用户输入: \"{query}\"")

    return StreamingResponse(_event_stream(query, user_id), media_type="text/event-stream")


# ==========================================
# 用户注册 API
# ==========================================
@app.post("/api/register")
async def register(request: Request):
    """
    用户注册接口。
    接收 JSON: {"username": "...", "password": "..."}
    返回: {"message": "..."}
    """
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    if len(password) < 6:
        raise HTTPException(status_code=400, detail="密码长度至少 6 位")

    # 检查用户名是否已存在
    existing = get_user_by_username(username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 创建用户
    hashed_pw = get_password_hash(password)
    create_user(username, hashed_pw)

    logger.info(f"用户注册: {username}")
    return {"message": "注册成功"}


# ==========================================
# 用户登录 API
# ==========================================
@app.post("/api/login")
async def login(request: Request):
    """
    用户登录接口。
    接收 JSON: {"username": "...", "password": "..."}
    返回: {"token": "...", "username": "..."}
    """
    body = await request.json()
    username = body.get("username", "").strip()
    password = body.get("password", "")

    if not username or not password:
        raise HTTPException(status_code=400, detail="用户名和密码不能为空")

    # 查找用户
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 验证密码
    if not verify_password(password, user["hashed_password"]):
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 生成 JWT token
    token_data = {"sub": username, "user_id": str(user["id"])}
    token = create_access_token(token_data)

    logger.info(f"用户登录: {username}")
    return {"token": token, "username": username}


# ==========================================
# 启动入口
# ==========================================
if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
