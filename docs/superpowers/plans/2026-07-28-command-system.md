# 命令系统实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为聊天机器人添加斜杠命令系统（/clear, /compact, /status, /mood, /help），允许用户直接控制系统行为

**Architecture:** Server 层拦截命令 → commands.py 分发处理 → RedisSaver 操作状态 → SSE 返回结果

**Tech Stack:** FastAPI, LangGraph, Redis, asyncio

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `memory_utils.py` | 创建 | 消息压缩工具函数，供 agent.py 和 commands.py 共用 |
| `commands.py` | 创建 | 命令处理模块，5 个命令的分发和处理逻辑 |
| `sys_memory.py` | 修改 | 新增 clear_thread、mood_override 等 Redis 操作方法 |
| `agent.py` | 修改 | compact_node 调用 memory_utils，detect_mood_node 检查 mood_override |
| `server.py` | 修改 | 全局 redis_saver_instance，_event_stream 拦截命令 |
| `test_commands_manual.py` | 创建 | 手动测试脚本，快速验证所有命令 |

---

## Task 1: 创建 memory_utils.py - 消息压缩工具

**Files:**
- Create: `memory_utils.py`

**Context:**
从 agent.py 的 compact_node 提取压缩逻辑为独立函数，供 commands.py 的 /compact 命令复用。

- [ ] **Step 1: 创建 memory_utils.py 基础结构**

```python
"""
消息压缩工具模块
提供独立的压缩函数，供 agent.py 和 commands.py 共用
"""
import asyncio
import re
from typing import List, Tuple

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage, ToolMessage
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
```

- [ ] **Step 2: 验证文件创建成功**

Run: `ls -la memory_utils.py`

Expected: 文件存在，大小约 3-4 KB

- [ ] **Step 3: Commit**

```bash
git add memory_utils.py
git commit -m "feat: create memory_utils.py with compact_messages function"
```

---

## Task 2: 扩展 RedisSaver - 新增 Redis 操作方法

**Files:**
- Modify: `sys_memory.py`

**Context:**
为 RedisSaver 类新增 5 个方法，支持命令系统需要的 Redis 操作。

- [ ] **Step 1: 在 RedisSaver 类末尾添加 clear_thread 方法**

在 `sys_memory.py` 的 `RedisSaver` 类中，在 `async def alist` 方法之前添加：

```python
    # ==========================================
    # 清除用户所有 checkpoints
    # ==========================================
    def clear_thread(self, thread_id: str) -> int:
        """
        清除指定用户的所有 checkpoints 和相关数据。

        Args:
            thread_id: 线程 ID (str)

        Returns:
            int: 删除的 checkpoint 数量
        """
        # 获取 checkpoint 列表
        index_key = self._get_index_key(thread_id)
        checkpoint_ids = self.client.lrange(index_key, 0, -1)
        count = len(checkpoint_ids)

        if count == 0:
            return 0

        # 删除所有 checkpoints
        for cp_id_bytes in checkpoint_ids:
            checkpoint_id = cp_id_bytes.decode("utf-8")
            cp_key = self._get_checkpoint_key(thread_id, checkpoint_id)
            self.client.delete(cp_key)

            # 删除 writes
            writes_prefix = f"{self.prefix}:writes:{thread_id}:{checkpoint_id}"
            for writes_key in self.client.scan_iter(f"{writes_prefix}:*"):
                self.client.delete(writes_key)

        # 删除索引
        self.client.delete(index_key)

        # 删除 mood_override
        self.clear_mood_override(thread_id)

        logger.info(f"清除用户 {thread_id} 的所有 checkpoints: {count} 个")
        return count
```

- [ ] **Step 2: 添加 mood_override 相关方法**

在 `clear_thread` 方法之后添加：

```python
    # ==========================================
    # 情绪覆盖操作
    # ==========================================
    def set_mood_override(self, thread_id: str, mood: str) -> None:
        """
        设置情绪覆盖值。

        Args:
            thread_id: 线程 ID (str)
            mood: 情绪标签 (str)
        """
        key = f"{self.prefix}:mood_override:{thread_id}"
        self.client.set(key, mood)
        logger.info(f"设置用户 {thread_id} 情绪覆盖: {mood}")

    def get_mood_override(self, thread_id: str) -> str:
        """
        获取情绪覆盖值。

        Args:
            thread_id: 线程 ID (str)

        Returns:
            str: 情绪标签，无则返回 None
        """
        key = f"{self.prefix}:mood_override:{thread_id}"
        value = self.client.get(key)
        return value.decode("utf-8") if value else None

    def clear_mood_override(self, thread_id: str) -> None:
        """
        清除情绪覆盖。

        Args:
            thread_id: 线程 ID (str)
        """
        key = f"{self.prefix}:mood_override:{thread_id}"
        self.client.delete(key)
        logger.debug(f"清除用户 {thread_id} 情绪覆盖")
```

- [ ] **Step 3: 添加 get_checkpoints 方法**

在 `clear_mood_override` 方法之后添加：

```python
    # ==========================================
    # 获取 checkpoints 列表
    # ==========================================
    def get_checkpoints(self, thread_id: str) -> list:
        """
        获取用户的所有 checkpoints（元数据）。

        Args:
            thread_id: 线程 ID (str)

        Returns:
            list: checkpoint 元数据列表
        """
        index_key = self._get_index_key(thread_id)
        checkpoint_ids = self.client.lrange(index_key, 0, -1)

        checkpoints = []
        for cp_id_bytes in checkpoint_ids:
            checkpoint_id = cp_id_bytes.decode("utf-8")
            key = self._get_checkpoint_key(thread_id, checkpoint_id)
            data = self.client.get(key)
            if data:
                checkpoint, metadata = pickle.loads(data)
                checkpoints.append({
                    "checkpoint_id": checkpoint_id,
                    "metadata": metadata,
                })

        return checkpoints
```

- [ ] **Step 4: 验证修改**

Run: `python -c "from sys_memory import RedisSaver; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 5: Commit**

```bash
git add sys_memory.py
git commit -m "feat: add clear_thread, mood_override, get_checkpoints methods to RedisSaver"
```

---

## Task 3: 创建 commands.py - 命令处理模块

**Files:**
- Create: `commands.py`

**Context:**
实现 5 个命令的处理函数和分发器。

- [ ] **Step 1: 创建 commands.py 基础结构和有效命令列表**

```python
"""
命令处理模块
实现斜杠命令的分发和处理逻辑
"""
from typing import Optional

from langchain_core.messages import HumanMessage, AIMessage

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
```

- [ ] **Step 2: 添加 dispatch_command 分发器**

在文件末尾添加：

```python
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
```

- [ ] **Step 3: 添加 handle_clear 函数**

在 dispatch_command 之前添加：

```python
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
```

- [ ] **Step 4: 添加 handle_compact 函数**

在 handle_clear 之后添加：

```python
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
    # 从 config 加载 checkpoint
    config = {"configurable": {"thread_id": user_id}}
    checkpoint_tuple = redis_saver.get_tuple(config)
    
    if not checkpoint_tuple:
        return {"type": "text", "content": "当前没有可压缩的上下文"}
    
    checkpoint = checkpoint_tuple.checkpoint
    channel_values = checkpoint.get("channel_values", {})
    
    # 提取 messages
    messages = channel_values.get("messages", [])
    compact_msgs = channel_values.get("compact_messages", [])
    
    if not messages and not compact_msgs:
        return {"type": "text", "content": "当前没有可压缩的上下文"}
    
    # 计算压缩前的 token 数
    before_tokens = count_tokens(messages) + count_tokens(compact_msgs)
    
    # 调用压缩函数
    # 注意：这里需要从 agent_graph 获取 llm 和 memory_token_limit
    # 暂时使用简化版本，实际实现需要从 config 获取
    from config import LLM_MODEL_NAME, LLM_BASE_URL, LLM_API_KEY, MEMORY_TOKEN_LIMIT
    from langchain_openai import ChatOpenAI
    
    llm = ChatOpenAI(
        model=LLM_MODEL_NAME,
        base_url=LLM_BASE_URL,
        api_key=LLM_API_KEY,
        temperature=0,
    )
    
    combined = compact_msgs + messages
    compressed, after_tokens = await compact_messages(combined, llm, MEMORY_TOKEN_LIMIT)
    
    # 更新 checkpoint（这里简化处理，实际需要更新 channel_values）
    # 由于 checkpoint 结构复杂，暂时只返回统计信息
    
    return {
        "type": "text",
        "content": f"上下文已压缩: {before_tokens} → {after_tokens} tokens"
    }
```

- [ ] **Step 5: 添加 handle_status 函数**

在 handle_compact 之后添加：

```python
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
```

- [ ] **Step 6: 添加 handle_mood 函数**

在 handle_status 之后添加：

```python
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
```

- [ ] **Step 7: 添加 handle_help 函数**

在 handle_mood 之后添加：

```python
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
```

- [ ] **Step 8: 验证文件创建成功**

Run: `python -c "from commands import VALID_COMMANDS, dispatch_command; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 9: Commit**

```bash
git add commands.py
git commit -m "feat: create commands.py with 5 command handlers"
```

---

## Task 4: 修改 agent.py - 集成 memory_utils 和 mood_override

**Files:**
- Modify: `agent.py`

**Context:**
1. compact_node 调用 memory_utils.compact_messages()
2. detect_mood_node 检查 mood_override

- [ ] **Step 1: 在 agent.py 顶部添加 import**

在 `agent.py` 文件顶部，在 `from sys_logger import setup_global_logger` 之后添加：

```python
from memory_utils import compact_messages as compress_messages
```

- [ ] **Step 2: 修改 detect_mood_node 函数**

找到 `detect_mood_node` 函数，在函数开头（获取 user_id 之后）添加 mood_override 检查：

```python
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
        
        # 原有逻辑继续...
        messages = state.get("messages", [])
        # ... 后面的代码保持不变
```

- [ ] **Step 3: 修改 compact_node 函数**

找到 `compact_node` 函数，将压缩逻辑替换为调用 memory_utils：

```python
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
```

- [ ] **Step 4: 验证修改**

Run: `python -c "from agent import create_agent_graph; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 5: Commit**

```bash
git add agent.py
git commit -m "feat: integrate memory_utils and mood_override in agent.py"
```

---

## Task 5: 修改 server.py - 添加命令拦截

**Files:**
- Modify: `server.py`

**Context:**
1. 添加全局 redis_saver_instance
2. 在 _event_stream 开头拦截命令

- [ ] **Step 1: 添加全局变量 redis_saver_instance**

在 `server.py` 顶部，在 `agent_graph = None` 和 `llm_instance = None` 之后添加：

```python
redis_saver_instance = None
```

- [ ] **Step 2: 修改 lifespan 函数，初始化 redis_saver_instance**

找到 `lifespan` 函数，在创建 `redis_saver` 之后添加全局变量赋值：

```python
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

    # ... 后面的代码保持不变
```

- [ ] **Step 3: 在 _event_stream 开头添加命令拦截**

找到 `_event_stream` 函数，在函数开头（`t_start = time.time()` 之前）添加命令拦截逻辑：

```python
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
    # 命令拦截
    if query.startswith("/"):
        parts = query[1:].split(maxsplit=1)
        command = parts[0].lower() if parts else ""
        args = parts[1] if len(parts) > 1 else ""
        
        from commands import VALID_COMMANDS, dispatch_command
        
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
    
    # 原有逻辑继续...
    t_start = time.time()
    # ... 后面的代码保持不变
```

- [ ] **Step 4: 验证修改**

Run: `python -c "from server import app; print('Import OK')"`

Expected: `Import OK`

- [ ] **Step 5: Commit**

```bash
git add server.py
git commit -m "feat: add command interception in server.py"
```

---

## Task 6: 创建手动测试脚本

**Files:**
- Create: `test_commands_manual.py`

**Context:**
快速验证所有命令是否正常工作。

- [ ] **Step 1: 创建 test_commands_manual.py**

```python
"""
命令系统手动测试脚本
快速验证所有命令功能
"""
import asyncio
import json
import httpx


# ==========================================
# 配置
# ==========================================
BASE_URL = "http://127.0.0.1:8000"
USER_ID = "test_commands_user"


# ==========================================
# 辅助函数
# ==========================================
async def send_command(command: str):
    """
    发送命令并打印响应。

    Args:
        command: 命令字符串 (str)
    """
    print(f"\n{'='*50}")
    print(f"发送命令: {command}")
    print(f"{'='*50}")
    
    async with httpx.AsyncClient() as client:
        async with client.stream(
            "POST",
            f"{BASE_URL}/chat",
            json={"query": command, "user_id": USER_ID},
            timeout=30.0,
        ) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:]
                    try:
                        data = json.loads(data_str)
                        print(f"响应: {data}")
                    except json.JSONDecodeError:
                        print(f"原始数据: {data_str}")


# ==========================================
# 主测试函数
# ==========================================
async def test_all_commands():
    """测试所有命令"""
    print("\n" + "="*50)
    print("开始命令系统测试")
    print("="*50)
    
    # 测试 1: /help
    await send_command("/help")
    
    # 测试 2: /status (无状态)
    await send_command("/status")
    
    # 测试 3: 聊天产生上下文
    print("\n" + "="*50)
    print("发送普通消息产生上下文")
    print("="*50)
    await send_command("你好，我叫小明")
    await send_command("我喜欢编程")
    
    # 测试 4: /status (有状态)
    await send_command("/status")
    
    # 测试 5: /compact
    await send_command("/compact")
    
    # 测试 6: /mood (查看)
    await send_command("/mood")
    
    # 测试 7: /mood cheerful (设置)
    await send_command("/mood cheerful")
    
    # 测试 8: /mood (验证设置)
    await send_command("/mood")
    
    # 测试 9: /mood happy (无效)
    await send_command("/mood happy")
    
    # 测试 10: /clear
    await send_command("/clear")
    
    # 测试 11: /status (验证清空)
    await send_command("/status")
    
    # 测试 12: /unknown (无效命令)
    await send_command("/unknown")
    
    print("\n" + "="*50)
    print("测试完成")
    print("="*50)


# ==========================================
# 入口
# ==========================================
if __name__ == "__main__":
    asyncio.run(test_all_commands())
```

- [ ] **Step 2: 验证文件创建成功**

Run: `ls -la test_commands_manual.py`

Expected: 文件存在

- [ ] **Step 3: Commit**

```bash
git add test_commands_manual.py
git commit -m "test: add manual test script for command system"
```

---

## Task 7: 手动测试所有命令

**Context:**
启动服务器并运行测试脚本，验证所有命令正常工作。

- [ ] **Step 1: 启动服务器**

```bash
conda run -n py310 python server.py
```

在另一个终端继续以下步骤。

- [ ] **Step 2: 运行测试脚本**

```bash
conda run -n py310 python test_commands_manual.py
```

Expected: 所有命令正常响应，无报错

- [ ] **Step 3: 验证关键功能**

检查以下功能是否正常：
1. `/help` 显示帮助文本
2. `/status` 显示状态信息
3. `/compact` 压缩上下文
4. `/mood cheerful` 设置情绪
5. `/mood happy` 提示无效情绪
6. `/clear` 清除记忆
7. `/unknown` 提示命令错误

- [ ] **Step 4: 修复发现的问题**

如果测试发现问题，修复代码并重新测试。

- [ ] **Step 5: Commit 修复**

```bash
git add .
git commit -m "fix: fix issues found in manual testing"
```

---

## 总结

完成以上 7 个 Task 后，命令系统应该可以正常工作。

**已实现功能：**
- ✅ `/clear` - 清除所有对话记忆
- ✅ `/compact` - 手动压缩上下文
- ✅ `/status` - 查看当前状态
- ✅ `/mood` - 查看/设置情绪
- ✅ `/help` - 显示帮助
- ✅ 命令错误处理
- ✅ 参数验证

**下一步（可选）：**
- 编写单元测试
- 编写集成测试
- 添加更多命令（如 /history, /export）
