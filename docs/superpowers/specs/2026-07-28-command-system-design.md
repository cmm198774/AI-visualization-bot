# 命令系统设计文档

**日期**: 2026-07-28  
**作者**: Lisa (AI 助手)  
**状态**: 待审核

---

## 1. 概述

为聊天机器人添加斜杠命令系统，允许用户通过 `/command` 格式直接控制系统行为，无需经过 LLM 处理。

### 1.1 目标

- 提供快速操作：清除记忆、压缩上下文、查看状态等
- 降低 LLM 调用成本：命令直接处理，不消耗 token
- 提升用户体验：即时反馈，明确的操作结果

### 1.2 非目标

- 不实现复杂的权限系统（所有用户都可执行所有命令）
- 不持久化命令历史
- 不支持命令参数复杂解析（仅支持简单的单参数）

---

## 2. 功能需求

### 2.1 命令列表

| 命令 | 参数 | 功能 | 示例 |
|------|------|------|------|
| `/clear` | 无 | 清除用户的所有对话记忆 | `/clear` |
| `/compact` | 无 | 手动触发上下文压缩 | `/compact` |
| `/status` | 无 | 查看当前对话状态 | `/status` |
| `/mood` | 可选：情绪名称 | 查看或设置当前情绪 | `/mood`、`/mood cheerful` |
| `/help` | 无 | 显示所有可用命令 | `/help` |

### 2.2 命令格式

- 以 `/` 开头
- 命令名称不区分大小写（自动转小写）
- 参数与命令之间用空格分隔
- 参数自动去除首尾空格

### 2.3 错误处理

| 错误场景 | 响应 |
|----------|------|
| 命令不存在 | `命令错误，输入 /help 查看可用命令` |
| `/mood` 参数无效 | `无效情绪 '{input}'，可选值：angry, cheerful, default, depressed, friendly, upbeat` |
| `/clear` 无 checkpoint | `当前没有对话记忆` |
| `/compact` 无上下文 | `当前没有可压缩的上下文` |
| 命令执行异常 | `命令执行失败: {error}` |

---

## 3. 架构设计

### 3.1 命令拦截流程

```
用户输入
  ↓
_event_stream() 检测 "/" 前缀
  ↓
解析命令和参数
  ↓
验证命令是否在 VALID_COMMANDS 中
  ↓
有效 → dispatch_command() → 执行命令 → 返回 SSE 事件
无效 → 返回错误信息 → 返回 SSE 事件
  ↓
非命令 → 正常走 agent_graph.ainvoke()
```

### 3.2 SSE 响应格式

命令返回的 SSE 事件保持现有格式：

```
data: {"type": "text", "content": "命令执行结果"}
data: {"type": "done"}
```

特殊情况下可包含 mood 事件：

```
data: {"type": "text", "content": "情绪已设置为：cheerful"}
data: {"type": "mood", "mood": "cheerful"}
data: {"type": "done"}
```

---

## 4. 文件结构设计

### 4.1 新增文件

#### `memory_utils.py` - 消息压缩工具模块

**职责**: 提供独立的压缩函数，供 `agent.py` 和 `commands.py` 共用

**核心函数**:

```python
async def compact_messages(
    messages: List[BaseMessage],
    llm: ChatOpenAI,
    memory_token_limit: int
) -> tuple[list, int]:
    """
    压缩消息列表
    
    Args:
        messages: 原始消息列表
        llm: LLM 实例
        memory_token_limit: token 上限
    
    Returns:
        (compressed_messages, token_count): 压缩后的消息和 token 数
    """
```

**实现逻辑**:
1. 计算当前 token 数
2. 如果未超限，直接返回原消息
3. 如果超限：
   - 调用 LLM 生成摘要（目标：memory_token_limit / 3）
   - 失败则截断降级（保留 memory_token_limit / 2）

#### `commands.py` - 命令处理模块

**职责**: 实现所有命令的处理逻辑

**核心结构**:

```python
VALID_COMMANDS = {"clear", "compact", "status", "mood", "help"}

async def dispatch_command(
    command: str,
    args: str,
    user_id: str,
    redis_saver: RedisSaver,
    agent_graph
) -> dict:
    """
    命令分发器
    
    Returns:
        {"type": "text" | "mood", "content": "..."}
    """
```

**命令处理函数**:

| 函数 | 功能 |
|------|------|
| `handle_clear(user_id, redis_saver)` | 清除所有 checkpoints |
| `handle_compact(user_id, redis_saver, agent_graph)` | 手动压缩上下文 |
| `handle_status(user_id, redis_saver)` | 查看状态 |
| `handle_mood(user_id, args, redis_saver)` | 查看/设置情绪 |
| `handle_help()` | 返回帮助文本 |

### 4.2 修改文件

#### `agent.py`

**改动 1**: `compact_node` 调用 `memory_utils.compact_messages()`

```python
async def compact_node(state, config):
    # ... 处理 skip_count 等逻辑 ...
    
    combined = compact_messages + new_messages
    
    # 调用 memory_utils 的函数
    from memory_utils import compact_messages as compress
    new_compact, total_tokens = await compress(combined, llm, memory_token_limit)
    
    return {
        "compact_messages": new_compact,
        "compacted_count": len(messages),
        "skip_count": 0,
    }
```

**改动 2**: `detect_mood_node` 检查 mood_override

```python
async def detect_mood_node(state, config):
    user_id = (config or {}).get("configurable", {}).get("thread_id", "?")
    
    # 检查是否有情绪覆盖
    mood_override = None
    if checkpointer and hasattr(checkpointer, 'get_mood_override'):
        mood_override = checkpointer.get_mood_override(user_id)
    
    if mood_override:
        logger.info(f"[{user_id}] 使用情绪覆盖：{mood_override}")
        return {"mood": mood_override, "skip_count": 0}
    
    # 原有逻辑：LLM 情绪检测
    # ...
```

#### `sys_memory.py`

**新增方法**:

```python
class RedisSaver(BaseCheckpointSaver):
    def clear_thread(self, thread_id: str) -> int:
        """
        清除指定用户的所有 checkpoints
        
        删除的键:
        - langgraph:index:{thread_id}
        - langgraph:checkpoint:{thread_id}:*
        - langgraph:writes:{thread_id}:*
        - langgraph:mood_override:{thread_id}
        
        Returns:
            int: 删除的 checkpoint 数量
        """
    
    def set_mood_override(self, thread_id: str, mood: str) -> None:
        """设置情绪覆盖值"""
        key = f"{self.prefix}:mood_override:{thread_id}"
        self.client.set(key, mood)
    
    def get_mood_override(self, thread_id: str) -> Optional[str]:
        """获取情绪覆盖值，无则返回 None"""
        key = f"{self.prefix}:mood_override:{thread_id}"
        value = self.client.get(key)
        return value.decode("utf-8") if value else None
    
    def clear_mood_override(self, thread_id: str) -> None:
        """清除情绪覆盖"""
        key = f"{self.prefix}:mood_override:{thread_id}"
        self.client.delete(key)
    
    def get_checkpoints(self, thread_id: str) -> list:
        """获取用户的所有 checkpoints（元数据）"""
        # 用于 /status 命令统计
```

#### `server.py`

**改动 1**: 全局 `redis_saver_instance`

```python
# server.py 顶部
redis_saver_instance = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global agent_graph, llm_instance, redis_saver_instance
    
    # ... 原有代码 ...
    
    redis_saver_instance = RedisSaver(redis_url=REDIS_URL, max_checkpoints=MAX_CHECKPOINTS)
    
    # ...
```

**改动 2**: `_event_stream()` 开头拦截命令

```python
async def _event_stream(query: str, user_id: str):
    """生成 SSE 事件流"""
    
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
    
    # 原有逻辑：正常聊天
    # ...
```

---

## 5. 数据流设计

### 5.1 `/clear` 命令

```
用户输入 "/clear"
  ↓
server.py 拦截
  ↓
dispatch_command("clear", "", user_id, redis_saver, agent_graph)
  ↓
handle_clear(user_id, redis_saver)
  ↓
redis_saver.clear_thread(user_id)
  ↓
删除 Redis 键:
  - langgraph:index:{user_id}
  - langgraph:checkpoint:{user_id}:*
  - langgraph:writes:{user_id}:*
  - langgraph:mood_override:{user_id}
  ↓
返回 {"type": "text", "content": "已清除所有对话记忆"}
  ↓
SSE 返回给前端
```

### 5.2 `/compact` 命令

```
用户输入 "/compact"
  ↓
server.py 拦截
  ↓
dispatch_command("compact", "", user_id, redis_saver, agent_graph)
  ↓
handle_compact(user_id, redis_saver, agent_graph)
  ↓
1. 从 Redis 加载当前 checkpoint
2. 提取 messages 和 compact_messages
3. 调用 memory_utils.compact_messages()
4. 更新 checkpoint 中的 compact_messages
  ↓
返回 {"type": "text", "content": "上下文已压缩，token: 15000 → 8000"}
  ↓
SSE 返回给前端
```

### 5.3 `/mood cheerful` 命令

```
用户输入 "/mood cheerful"
  ↓
server.py 拦截
  ↓
dispatch_command("mood", "cheerful", user_id, redis_saver, agent_graph)
  ↓
handle_mood(user_id, "cheerful", redis_saver)
  ↓
1. 验证 "cheerful" 在有效情绪列表中
2. redis_saver.set_mood_override(user_id, "cheerful")
  ↓
返回 {"type": "text", "content": "情绪已设置为：cheerful"}
  ↓
SSE 返回给前端
  ↓
后续聊天时，detect_mood_node 检查到 mood_override，直接使用 "cheerful"
```

---

## 6. 错误处理

### 6.1 命令验证错误

**场景**: 用户输入 `/unknown`

**处理**:
```python
if command not in VALID_COMMANDS:
    yield error_event("命令错误，输入 /help 查看可用命令")
    return
```

### 6.2 参数验证错误

**场景**: 用户输入 `/mood happy`

**处理**:
```python
if mood_input not in valid_moods:
    return {
        "type": "text",
        "content": f"无效情绪 '{args}'，可选值：{', '.join(sorted(valid_moods))}"
    }
```

### 6.3 状态检查错误

**场景**: 用户输入 `/clear`，但没有 checkpoint

**处理**:
```python
if not has_checkpoints:
    return {"type": "text", "content": "当前没有对话记忆"}
```

### 6.4 异常处理

**场景**: 命令执行过程中抛出异常

**处理**:
```python
try:
    result = await dispatch_command(...)
except Exception as e:
    logger.error(f"[{user_id}] 命令执行错误: {e}")
    yield error_event(f"命令执行失败: {str(e)}")
```

---

## 7. 测试策略

### 7.1 手动测试（优先）

**测试脚本**: `test_commands_manual.py`

**测试用例**:

1. `/help` - 验证帮助文本显示
2. `/status` - 无状态时显示
3. 聊天产生上下文
4. `/status` - 有状态时显示
5. `/compact` - 手动压缩
6. `/mood` - 查看情绪
7. `/mood cheerful` - 设置情绪
8. `/mood happy` - 无效情绪提示
9. `/clear` - 清除记忆
10. `/status` - 验证已清空
11. `/unknown` - 命令错误提示

### 7.2 单元测试（后续补充）

**测试文件**: `test_commands.py`

**测试内容**:
- 每个命令函数的返回值
- Redis 操作是否正确
- 错误处理是否生效

### 7.3 集成测试（后续补充）

**测试文件**: `test_commands_integration.py`

**测试内容**:
- 通过 HTTP 端点的完整流程
- SSE 事件格式验证
- Redis 状态变化验证

---

## 8. 实现计划

### 8.1 阶段 1：核心功能

1. 创建 `memory_utils.py`，提取 `compact_messages()` 函数
2. 修改 `sys_memory.py`，新增 Redis 操作方法
3. 创建 `commands.py`，实现 5 个命令处理函数
4. 修改 `agent.py`，集成 `memory_utils` 和 mood_override 检查
5. 修改 `server.py`，添加命令拦截逻辑

### 8.2 阶段 2：测试验证

1. 编写手动测试脚本
2. 逐个测试所有命令
3. 修复发现的问题

### 8.3 阶段 3：自动化测试（可选）

1. 编写单元测试
2. 编写集成测试
3. 集成到 CI/CD

---

## 9. 风险与缓解

### 9.1 风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Redis 操作失败 | 命令无法执行 | 添加异常处理，返回友好错误信息 |
| `/compact` 压缩失败 | 上下文仍然过大 | 降级为截断策略 |
| mood_override 未清除 | 情绪一直生效 | `/clear` 命令同时清除 mood_override |
| 命令与正常消息混淆 | 误触发命令 | 严格验证命令格式，只有完全匹配才触发 |

### 9.2 限制

- 命令不支持多参数（如 `/mood cheerful 10`）
- 命令不支持选项（如 `/clear --force`）
- 命令不支持管道（如 `/status | grep token`）

---

## 10. 未来扩展

### 10.1 可能的命令

| 命令 | 功能 |
|------|------|
| `/history` | 查看对话历史摘要 |
| `/export` | 导出对话记录 |
| `/reset` | 重置系统（清除所有用户数据） |
| `/config` | 查看/修改配置 |

### 10.2 增强功能

- 命令自动补全（前端实现）
- 命令别名（如 `/c` = `/clear`）
- 命令权限控制（管理员 vs 普通用户）
- 命令执行日志

---

## 附录 A：Redis 键设计

| 键模式 | 用途 | 数据类型 |
|--------|------|----------|
| `langgraph:index:{thread_id}` | checkpoint 索引 | List |
| `langgraph:checkpoint:{thread_id}:{checkpoint_id}` | checkpoint 数据 | String (pickle) |
| `langgraph:writes:{thread_id}:{checkpoint_id}:{task_id}` | 中间写入 | String (pickle) |
| `langgraph:mood_override:{thread_id}` | 情绪覆盖 | String |

---

## 附录 B：情绪列表

| 情绪 | 描述 | 触发场景 |
|------|------|----------|
| `default` | 中性 | 默认状态 |
| `cheerful` | 愉悦 | 开心、兴奋 |
| `upbeat` | 兴奋 | 非常激动 |
| `friendly` | 友好 | 温和交流 |
| `depressed` | 低落 | 悲伤、需要安慰 |
| `angry` | 愤怒 | 不满、生气 |

---

**文档结束**
