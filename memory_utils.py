"""
消息压缩工具模块
提供独立的压缩函数，供 agent.py 和 commands.py 共用
"""
import asyncio
import re
from typing import List, Tuple

from langchain_core.messages import (
    BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
)
from langchain_openai import ChatOpenAI

from sys_logger import setup_global_logger


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()


# ==========================================
# Token 计数（区分中英文）
# ==========================================
def count_tokens(messages: List[BaseMessage]) -> int:
    """
    估算消息列表的 token 总数。
    中文约 1.5 字符/token, 英文约 4 字符/token。

    Args:
        messages: 消息列表 (List[BaseMessage])

    Returns:
        int: token 总数的估算值
    """
    total = 0
    for msg in messages:
        if hasattr(msg, "content") and msg.content:
            text = str(msg.content)
            chinese_chars = len(re.findall(r"[一-鿿]", text))
            other_chars = len(text) - chinese_chars
            # 中文: 1.5 字符/token, 英文: 4 字符/token
            total += int(chinese_chars / 1.5 + other_chars / 4)
        total += 4  # 消息格式开销
    return total


# ==========================================
# 消息压缩函数
# ==========================================
async def compact_messages(
    messages: List[BaseMessage],
    llm: ChatOpenAI,
    memory_token_limit: int
) -> Tuple[list, int]:
    """
    压缩消息列表。
    如果未超限，直接返回原消息；如果超限，调用 LLM 摘要或截断降级。

    Args:
        messages: 原始消息列表 (List[BaseMessage])
        llm: LLM 实例 (ChatOpenAI)
        memory_token_limit: token 上限 (int)

    Returns:
        Tuple[list, int]: (压缩后的消息列表, token 数)
    """
    total_tokens = count_tokens(messages)
    logger.debug(f"compact_messages: 当前 token={total_tokens}, 阈值={memory_token_limit}")

    # 未超限，直接返回
    if total_tokens <= memory_token_limit:
        return messages, total_tokens

    # 超限，需要压缩
    # 摘要目标: memory_token_limit 的 1/3
    summary_token_limit = memory_token_limit // 3
    # 估算字数（中文约 1.5 字符/token）
    summary_char_limit = int(summary_token_limit * 1.5)

    try:
        # 调用 LLM 生成摘要
        summary_prompt = (
            "请总结以下对话内容，保留关键信息，用简洁的语言表达：\n\n"
            "对话内容：\n"
            "{dialogue}\n\n"
            f"请用 {summary_char_limit} 字以内总结："
        )

        dialogue_parts = []
        for msg in messages:
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
                # 工具消息不截断，保留完整内容
                dialogue_parts.append(f"[工具 {tool_name} 返回]: {msg.content}")

        dialogue = "\n".join(dialogue_parts)

        response = await asyncio.wait_for(
            llm.ainvoke([SystemMessage(content=summary_prompt.format(dialogue=dialogue))]),
            timeout=10,
        )
        summary_text = response.content.strip()
        summary_msg = SystemMessage(content=f"[对话历史摘要] {summary_text}")
        compressed = [summary_msg]

        new_tokens = count_tokens(compressed)
        logger.info(f"compact_messages: 摘要压缩完成, {total_tokens} → {new_tokens} tokens")

        return compressed, new_tokens

    except Exception as e:
        logger.warning(f"compact_messages: 摘要失败 ({e}), 降级为截断")

        # 截断降级: 保留 memory_token_limit 的 1/2
        truncate_limit = memory_token_limit // 2
        compressed = []
        current_tokens = 0

        for msg in reversed(messages):
            msg_tokens = count_tokens([msg])
            if current_tokens + msg_tokens > truncate_limit:
                break
            compressed.insert(0, msg)
            current_tokens += msg_tokens

        logger.info(f"compact_messages: 截断降级, {total_tokens} → {current_tokens} tokens")
        return compressed, current_tokens
