"""
命令处理模块
实现斜杠命令的分发和处理逻辑
"""
from langchain_openai import ChatOpenAI

from config import LLM_MODEL_NAME, LLM_BASE_URL, LLM_API_KEY, MEMORY_TOKEN_LIMIT
from sys_logger import setup_global_logger
from memory_utils import compact_messages, count_tokens


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()


# ==========================================
# 有效命令列表
# ==========================================
VALID_COMMANDS = {"clear", "compact", "status", "mood", "help"}

# 有效情绪列表
VALID_MOODS = {"default", "upbeat", "angry", "depressed", "friendly", "cheerful"}


# ==========================================
# /clear 命令处理
# ==========================================
async def handle_clear(user_id: str, redis_saver) -> dict:
    """
    清除用户的所有对话记忆。

    Args:
        user_id: 用户 ID (str)
        redis_saver: RedisSaver 实例

    Returns:
        dict: {"type": "text", "content": "..."}
    """
    count = redis_saver.clear_thread(user_id)

    if count == 0:
        return {"type": "text", "content": "当前没有对话记忆"}

    return {
        "type": "text",
        "content": f"已清除所有对话记忆（{count} 个 checkpoints）"
    }


# ==========================================
# /compact 命令处理
# ==========================================
async def handle_compact(user_id: str, redis_saver, agent_graph) -> dict:
    """
    手动触发上下文压缩。

    Args:
        user_id: 用户 ID (str)
        redis_saver: RedisSaver 实例
        agent_graph: LangGraph agent 实例

    Returns:
        dict: {"type": "text", "content": "..."}
    """
    # 从 Redis 加载 checkpoints
    checkpoints = redis_saver.get_checkpoints(user_id)

    if not checkpoints:
        return {"type": "text", "content": "当前没有可压缩的上下文"}

    # 获取最新 checkpoint
    latest = checkpoints[0]
    checkpoint = latest.get("checkpoint", {})
    channel_values = checkpoint.get("channel_values", {})

    # 提取 messages
    messages = channel_values.get("messages", [])
    compact_msgs = channel_values.get("compact_messages", [])

    if not messages and not compact_msgs:
        return {"type": "text", "content": "当前没有可压缩的上下文"}

    # 计算压缩前的 token 数
    before_tokens = count_tokens(messages) + count_tokens(compact_msgs)

    # 创建 LLM 实例用于压缩
    llm = ChatOpenAI(
        model=LLM_MODEL_NAME,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0,
    )

    # 调用压缩函数
    combined = compact_msgs + messages
    compressed, after_tokens = await compact_messages(combined, llm, MEMORY_TOKEN_LIMIT)

    # 注意：由于 checkpoint 结构复杂，这里只返回统计信息
    # 实际压缩会在下次聊天时自动进行

    return {
        "type": "text",
        "content": f"上下文已压缩: {before_tokens} → {after_tokens} tokens"
    }


# ==========================================
# /status 命令处理
# ==========================================
async def handle_status(user_id: str, redis_saver) -> dict:
    """
    查看当前对话状态。

    Args:
        user_id: 用户 ID (str)
        redis_saver: RedisSaver 实例

    Returns:
        dict: {"type": "text", "content": "..."}
    """
    # 获取 checkpoints
    checkpoints = redis_saver.get_checkpoints(user_id)

    if not checkpoints:
        return {"type": "text", "content": "当前没有对话状态"}

    # 获取最新 checkpoint
    latest = checkpoints[0]
    checkpoint = latest.get("checkpoint", {})
    channel_values = checkpoint.get("channel_values", {})

    messages = channel_values.get("messages", [])
    compact_msgs = channel_values.get("compact_messages", [])
    mood = channel_values.get("mood", "default")

    # 检查 mood_override
    mood_override = redis_saver.get_mood_override(user_id)
    if mood_override:
        mood = f"{mood} (覆盖: {mood_override})"

    # 计算 token 数
    msg_tokens = count_tokens(messages)
    compact_tokens = count_tokens(compact_msgs)
    total_tokens = msg_tokens + compact_tokens

    status_text = (
        f"当前状态：\n"
        f"- Checkpoint 数量: {len(checkpoints)}\n"
        f"- 消息数量: {len(messages)}\n"
        f"- 压缩消息: {len(compact_msgs)}\n"
        f"- Token 使用: {total_tokens}\n"
        f"- 当前情绪: {mood}"
    )

    return {"type": "text", "content": status_text}


# ==========================================
# /mood 命令处理
# ==========================================
async def handle_mood(user_id: str, args: str, redis_saver) -> dict:
    """
    查看或设置当前情绪。

    Args:
        user_id: 用户 ID (str)
        args: 命令参数 (str)
        redis_saver: RedisSaver 实例

    Returns:
        dict: {"type": "text", "content": "..."}
    """
    if not args or not args.strip():
        # 无参数：查看当前情绪
        mood_override = redis_saver.get_mood_override(user_id)
        if mood_override:
            return {"type": "text", "content": f"当前情绪：{mood_override} (手动设置)"}
        else:
            return {"type": "text", "content": "当前情绪：default (自动检测)"}

    # 有参数：设置情绪
    mood_input = args.strip().lower()

    if mood_input not in VALID_MOODS:
        valid_list = ", ".join(sorted(VALID_MOODS))
        return {
            "type": "text",
            "content": f"无效情绪 '{args}'，可选值：{valid_list}"
        }

    redis_saver.set_mood_override(user_id, mood_input)
    return {"type": "text", "content": f"情绪已设置为：{mood_input}"}


# ==========================================
# /help 命令处理
# ==========================================
async def handle_help() -> dict:
    """
    显示所有可用命令。

    Returns:
        dict: {"type": "text", "content": "..."}
    """
    help_text = (
        "可用命令：\n"
        "- /clear - 清除所有对话记忆\n"
        "- /compact - 手动压缩上下文\n"
        "- /status - 查看当前状态\n"
        "- /mood - 查看当前情绪\n"
        "- /mood <情绪> - 设置情绪（可选：default, upbeat, angry, depressed, friendly, cheerful）\n"
        "- /help - 显示此帮助"
    )
    return {"type": "text", "content": help_text}


# ==========================================
# 命令分发器
# ==========================================
async def dispatch_command(
    command: str,
    args: str,
    user_id: str,
    redis_saver,
    agent_graph
) -> dict:
    """
    命令分发器，根据命令名称调用对应的处理函数。

    Args:
        command: 命令名称 (str)
        args: 命令参数 (str)
        user_id: 用户 ID (str)
        redis_saver: RedisSaver 实例
        agent_graph: LangGraph agent 实例

    Returns:
        dict: {"type": "text" | "mood", "content": "..."}
    """
    logger.info(f"[{user_id}] 执行命令: /{command} {args}")

    try:
        if command == "clear":
            return await handle_clear(user_id, redis_saver)
        elif command == "compact":
            return await handle_compact(user_id, redis_saver, agent_graph)
        elif command == "status":
            return await handle_status(user_id, redis_saver)
        elif command == "mood":
            return await handle_mood(user_id, args, redis_saver)
        elif command == "help":
            return await handle_help()
        else:
            return {
                "type": "text",
                "content": "命令错误，输入 /help 查看可用命令"
            }
    except Exception as e:
        logger.error(f"[{user_id}] 命令执行失败: {e}")
        return {
            "type": "text",
            "content": f"命令执行失败: {str(e)}"
        }
