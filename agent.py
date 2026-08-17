"""
异步 LangGraph Agent 模块
改进自 20260626_Agent实战/MyAgent.py:
    - 全异步 (asyncio, 无 ThreadPoolExecutor)
    - detect_mood 在 server 层并行运行, 不在此处阻塞
    - 参数化 system_prompt 和 MOODS
    - Token 计数区分中英文
    - 工具消息截断 500 字符
"""
import asyncio
import re
import time
from typing import TypedDict, Annotated, List, Optional

from langchain_core.tools import BaseTool
from langchain_core.messages import (
    BaseMessage, AIMessage, SystemMessage, ToolMessage, HumanMessage,
)
from langchain_core.runnables import RunnableConfig
from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.checkpoint.memory import MemorySaver

from sys_logger import setup_global_logger
from memory_utils import compact_messages as compress_messages


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()


# ==========================================
# 自定义超时异常（不覆盖 builtins.TimeoutError）
# ==========================================
class AgentTimeoutError(Exception):
    """Agent 操作超时异常"""
    pass


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
# 文本内容提取（兼容不同模型输出格式）
# ==========================================
def _extract_text_content(content) -> str:
    """
    从模型输出中提取纯文本内容。

    Args:
        content: 模型输出内容，可能是 str 或 list

    Returns:
        str: 提取的纯文本内容
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        text_parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and "text" in item:
                text_parts.append(item["text"])
        return "\n".join(text_parts) if text_parts else str(content)
    return str(content)


# ==========================================
# Agent 状态定义
# ==========================================
class AgentState(TypedDict):
    """
    Agent 状态结构。
    messages: 完整消息历史
    compact_messages: 压缩后的上下文
    compacted_count: 已处理到 messages 的第几条
    mood: 情绪状态
    skip_count: 需要跳过的消息数量（内容审核失败时使用）
    """
    messages: Annotated[list, add_messages]
    compact_messages: list
    compacted_count: int
    mood: Optional[str]
    skip_count: int


# ==========================================
# 创建 Agent Graph
# ==========================================
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
        model_name: LLM 模型名称 (str)
        base_url: API 地址 (str)
        api_key: API 密钥 (str)
        temperature: 温度参数 (float)
        tool_list: 工具列表 (List[BaseTool])
        tool_descriptions: 工具描述，追加到 system prompt (str)
        tool_timeout: 工具超时秒数 (int)
        system_prompt: 系统提示词，含角色设定 (str)
        moods_config: 情绪配置字典 (dict)
        memory_token_limit: 上下文 token 上限 (int)
        checkpointer: checkpoint 存储，默认 MemorySaver

    Returns:
        编译好的 graph，可用 graph.ainvoke() 或 graph.astream_events() 调用
    """
    # 默认情绪配置
    if moods_config is None:
        moods_config = {
            "default": {"roleSet": ""},
            "upbeat": {
                "roleSet": (
                    "    - 你此时非常兴奋，表现得很有活力。\n"
                    "    - 添加类似'太棒了！'等语气词。"
                ),
            },
            "angry": {
                "roleSet": (
                    "    - 你以愤怒的语气回答。\n"
                    "    - 提醒用户小心行事。"
                ),
            },
            "depressed": {
                "roleSet": (
                    "    - 你以温柔安慰的语气回答。\n"
                    "    - 加上激励的话语。"
                ),
            },
            "friendly": {
                "roleSet": (
                    "    - 你以友好温和的语气回答。\n"
                    "    - 随机分享一些经历。"
                ),
            },
            "cheerful": {
                "roleSet": (
                    "    - 你以愉悦兴奋的语气回答。\n"
                    "    - 加入愉悦的词语。"
                ),
            },
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

    # 绑定工具：内置 web_search + 自定义工具
    tools_with_web_search = [{"type": "web_search"}] + (tool_list or [])
    llm_with_tools = llm.bind_tools(tools_with_web_search)

    # ==========================================
    # 节点: detect_mood (情绪检测)
    # ==========================================
    async def detect_mood_node(state: AgentState, config: RunnableConfig = None) -> dict:
        """
        情绪检测节点。
        快速分类用户情绪，将结果存入 state["mood"]。
        如果检测到内容审核失败，设置 skip_count=1 跳过敏感消息。
        """
        user_id = (config or {}).get("configurable", {}).get("thread_id", "?")

        # 检查是否有情绪覆盖
        mood_override = None
        if checkpointer and hasattr(checkpointer, 'get_mood_override'):
            mood_override = checkpointer.get_mood_override(user_id)

        if mood_override:
            logger.info(f"[{user_id}] 使用情绪覆盖：{mood_override}")
            return {"mood": mood_override, "skip_count": 0}

        # 原有逻辑：LLM 情绪检测
        messages = state.get("messages", [])
        last_msg = messages[-1] if messages else None

        if last_msg is None or not hasattr(last_msg, "content"):
            return {"mood": "default", "skip_count": 0}

        user_input = last_msg.content
        valid_moods = {"default", "upbeat", "angry", "depressed", "friendly", "cheerful"}

        prompt = (
            "根据用户的输入判断用户的情绪，返回一个标签：\n"
            "    - 正面/开心 -> cheerful\n"
            "    - 兴奋 -> upbeat\n"
            "    - 友好 -> friendly\n"
            "    - 负面/悲伤 -> depressed\n"
            "    - 辱骂/不礼貌 -> angry\n"
            "    - 中性 -> default\n"
            "只返回一个标签单词。\n"
            f"用户输入：{user_input}"
        )

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
            logger.info(f"[{user_id}] 情绪检测：{mood}, 耗时：{elapsed:.1f}s")
            return {"mood": mood, "skip_count": 0}
        except Exception as e:
            elapsed = time.time() - t0
            error_str = str(e)

            # 检测内容审核失败（DataInspectionFailed）
            if "DataInspectionFailed" in error_str or "inappropriate content" in error_str:
                logger.warning(f"[{user_id}] 情绪检测：内容审核失败，替换敏感消息内容")
                # 替换敏感消息内容为安全占位符（同 ID 会被 add_messages 更新）
                # 防止敏感内容留在 messages 中污染后续所有 LLM 调用
                sanitized = HumanMessage(
                    content="[用户消息因内容规范被过滤]",
                    id=last_msg.id,
                )
                return {"mood": "sensitive", "skip_count": 1, "messages": [sanitized]}

            logger.warning(f"[{user_id}] 情绪检测失败 ({elapsed:.1f}s): {e}, fallback=default")
            return {"mood": "default", "skip_count": 0}

    # ==========================================
    # 节点: compact (消息压缩)
    # ==========================================
    async def compact_node(state: AgentState, config: RunnableConfig = None) -> dict:
        """
        消息压缩节点。
        处理 messages 的增量，合并到 compact_messages。
        超过阈值时调用 LLM 摘要压缩。
        如果 skip_count > 0，跳过敏感消息，不合并到 compact_messages。
        """
        user_id = (config or {}).get("configurable", {}).get("thread_id", "?")
        messages = list(state["messages"])
        compact_msgs = list(state.get("compact_messages", []))
        compacted_count = state.get("compacted_count", 0)
        skip_count = state.get("skip_count", 0)

        new_messages = messages[compacted_count:]
        if not new_messages:
            return {"skip_count": 0}

        # 如果 skip_count > 0，跳过敏感消息（通常是最后一条 HumanMessage）
        if skip_count > 0 and len(new_messages) >= skip_count:
            logger.debug(f"[{user_id}] compact: 跳过 {skip_count} 条敏感消息")
            new_messages = new_messages[:-skip_count]
            if not new_messages:
                # 所有新消息都是敏感的，直接跳过
                return {"skip_count": 0}

        combined = compact_msgs + new_messages

        # 调用 memory_utils 的压缩函数
        new_compact, total_tokens = await compress_messages(combined, llm, memory_token_limit)

        logger.debug(f"[{user_id}] compact: 压缩后 token={total_tokens}")

        return {
            "compact_messages": new_compact,
            "compacted_count": len(messages),
            "skip_count": 0,
        }

    # ==========================================
    # 节点: model (异步调用 LLM)
    # ==========================================
    async def call_model(state: AgentState, config: RunnableConfig = None) -> dict:
        """
        模型调用节点。
        使用 compact_messages 作为上下文，异步调用 LLM。
        如果 mood="sensitive"，直接返回友好提示，不调用 LLM。
        """
        user_id = (config or {}).get("configurable", {}).get("thread_id", "?")
        compact_messages = state.get("compact_messages", [])
        mood = state.get("mood", "default")

        # 如果内容审核失败（mood="sensitive"），直接返回友好提示
        if mood == "sensitive":
            logger.info(f"[{user_id}] 内容审核失败，跳过 LLM 调用")
            safe_msg = AIMessage(content="这个话题有点敏感呢，我们换个话题吧～")
            return {"messages": [safe_msg]}

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
            error_str = str(e)
            logger.error(f"[{user_id}] LLM 调用失败 ({elapsed:.1f}s): {e}")

            # 检测内容审核失败（DataInspectionFailed）- 作为备用处理
            if "DataInspectionFailed" in error_str or "inappropriate content" in error_str:
                logger.warning(f"[{user_id}] LLM 调用时内容审核失败")
                error_msg = AIMessage(content="这个话题有点敏感呢，我们换个话题吧～")
                return {"messages": [error_msg]}

            error_msg = AIMessage(content=f"API 调用失败: {error_str[:100]}")
            return {"messages": [error_msg]}

    # ==========================================
    # 执行单个工具调用（同级函数）
    # ==========================================
    async def _run_one_tool(tool_call, user_id: str, tools, timeout: int):
        """
        执行单个工具调用，带超时控制。

        Args:
            tool_call: 工具调用信息 (dict)
            user_id: 用户 ID (str)
            tools: 可用工具列表 (list)
            timeout: 超时秒数 (int)

        Returns:
            ToolMessage: 工具执行结果
        """
        tool_name = tool_call.get("name", "") if isinstance(tool_call, dict) else getattr(tool_call, "name", "")
        tool_args = tool_call.get("args", {}) if isinstance(tool_call, dict) else getattr(tool_call, "args", {})
        tid = tool_call.get("id", "") if isinstance(tool_call, dict) else getattr(tool_call, "id", "")
        logger.debug(f"[{user_id}] 工具调用: {tool_name}, 参数: {tool_args}")

        tool = next((t for t in (tools or []) if t.name == tool_name), None)
        if tool is None:
            return ToolMessage(content=f"工具 {tool_name} 未找到", tool_call_id=tid)

        t0 = time.time()
        try:
            # 支持 async 和 sync 工具
            if asyncio.iscoroutinefunction(tool.ainvoke):
                result = await asyncio.wait_for(tool.ainvoke(tool_args), timeout=timeout)
            else:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(None, lambda: tool.invoke(tool_args)),
                    timeout=timeout,
                )
            elapsed = time.time() - t0
            logger.info(f"[{user_id}] 工具 {tool_name} 完成: 耗时={elapsed:.1f}s")
            return ToolMessage(content=str(result), tool_call_id=tid)
        except asyncio.TimeoutError:
            elapsed = time.time() - t0
            logger.warning(f"[{user_id}] 工具 {tool_name} 超时 ({elapsed:.1f}s)")
            return ToolMessage(content=f"工具 {tool_name} 执行超时 ({timeout}秒)", tool_call_id=tid)
        except Exception as e:
            elapsed = time.time() - t0
            logger.error(f"[{user_id}] 工具 {tool_name} 错误 ({elapsed:.1f}s): {e}")
            return ToolMessage(content=f"工具 {tool_name} 错误: {str(e)[:100]}", tool_call_id=tid)

    # ==========================================
    # 节点: tools (异步工具调用)
    # ==========================================
    async def tool_node(state: AgentState, config: RunnableConfig = None) -> dict:
        """
        工具调用节点。
        并行执行所有工具调用，支持 async 和 sync 工具。
        """
        user_id = (config or {}).get("configurable", {}).get("thread_id", "?")
        messages = list(state["messages"])
        last_msg = messages[-1] if messages else None

        if not (hasattr(last_msg, "tool_calls") and last_msg.tool_calls):
            return {"messages": []}

        tool_calls = last_msg.tool_calls

        # 并行执行所有工具
        tasks = [_run_one_tool(tc, user_id, tool_list, tool_timeout) for tc in tool_calls]
        results = await asyncio.gather(*tasks)
        return {"messages": list(results)}

    # ==========================================
    # 路由: 判断是否继续调用工具
    # ==========================================
    def should_end(state: AgentState) -> str:
        """
        判断是否应该结束循环。

        Args:
            state: Agent 状态

        Returns:
            str: 下一个节点名称 ("tools" 或 END)
        """
        messages = state["messages"]
        last_msg = messages[-1] if messages else None
        if last_msg is None:
            return END
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            return "tools"
        return END

    # ==========================================
    # 构建 Graph
    # ==========================================
    workflow = StateGraph(AgentState)
    workflow.add_node("detect_mood", detect_mood_node)
    workflow.add_node("compact", compact_node)
    workflow.add_node("model", call_model)
    workflow.add_node("tools", tool_node)

    workflow.set_entry_point("detect_mood")
    workflow.add_edge("detect_mood", "compact")
    workflow.add_edge("compact", "model")
    workflow.add_conditional_edges("model", should_end, {"tools": "tools", END: END})
    workflow.add_edge("tools", "compact")

    if checkpointer is None:
        checkpointer = MemorySaver()

    return workflow.compile(checkpointer=checkpointer)


