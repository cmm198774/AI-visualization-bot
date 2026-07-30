# Lisa 的办公室 - AI 可视化聊天机器人

## 项目概述
一个带虚拟形象（Live2D）的 AI 聊天机器人，支持流式文本/音频输出、情绪检测、用户认证。

## 技术栈
- **后端**: FastAPI + SSE 流式输出
- **Agent**: LangGraph（全异步）
- **LLM**: qwen3.6-flash（阿里云 Token Plan）
- **向量数据库**: Qdrant（RAG 知识库）
- **缓存**: Redis（LangGraph checkpoint 持久化）
- **用户数据库**: SQLite
- **认证**: JWT token（python-jose + bcrypt）

## 已完成功能（Phase 1 MVP）

### 核心流程
- [x] FastAPI 服务器 + SSE 流式输出
- [x] LangGraph Agent（4 节点：detect_mood → compact → model → tools）
- [x] 情绪检测（detect_mood 节点，6 种情绪）
- [x] 消息压缩（compact 节点，LLM 摘要 + 截断降级）
- [x] Qdrant RAG 知识库工具（get_info_from_local_db）
- [x] 实时状态显示（asyncio.Queue + BaseCallbackHandler）

### 用户系统
- [x] 用户注册/登录 API
- [x] JWT token 管理
- [x] 前端认证检查
- [x] 登出功能

### 命令系统（2026-07-28 新增）
- [x] 斜杠命令拦截（server.py 中检测 "/" 前缀）
- [x] `/clear` - 清除所有对话记忆（Redis checkpoints）
- [x] `/compact` - 手动触发上下文压缩
- [x] `/status` - 查看当前对话状态（checkpoint 数、token 数、情绪）
- [x] `/mood` - 查看/设置当前情绪（支持手动覆盖自动检测）
- [x] `/help` - 显示所有可用命令
- [x] 命令错误处理（无效命令提示、参数验证）
- [x] 情绪覆盖机制（mood_override 存储在 Redis，detect_mood_node 优先检查）

### 关键改进
- **敏感内容处理**: detect_mood 捕获 DataInspectionFailed，通过 skip_count 机制跳过敏感消息，防止上下文污染
- **状态去重**: thinking 状态只显示一次（LLM 可能调用多次）
- **消息压缩策略**:
  - 摘要压缩到 memory_token_limit/3（约 10000 字）
  - 截断降级保留 memory_token_limit/2（约 10000 tokens）
  - 工具消息保留完整内容（不截断）
  - 压缩逻辑提取到 memory_utils.py，供 agent.py 和 commands.py 共用

## 待完成功能

### Phase 2: TTS 集成
- [x] CosyVoice-300M-SFT 语音合成（独立服务 tts_server.py，端口 9233，内置"中文女"音色）
- [x] 语音流式输出（逐句文字 + 音频，sentence_splitter 分句）
- [x] 错误处理（TTS 失败静默降级为文本）
- [x] 前端音频播放（队列 + 声波动画 + 🔊 开关）

### Phase 3: Live2D 虚拟形象
- [ ] Live2D 集成（pixi-live2d-display）
- [ ] 情绪联动（根据 mood 切换表情）
- [ ] 口型同步（配合 TTS）

## 项目文件结构
```
20260725_Agent_AI可视化机器人/
├── .env                    # 环境变量配置（API keys, SECRET_KEY 等）
├── CLAUDE.md              # 项目记忆文件
├── server.py              # FastAPI 主服务器，SSE 流式输出，命令拦截，TTS 集成
├── agent.py               # LangGraph Agent（4 节点：detect_mood, compact, model, tools）
├── commands.py            # 命令处理模块（/clear, /compact, /status, /mood, /help）
├── memory_utils.py        # 消息压缩工具（compact_messages 函数，供 agent 和 commands 共用）
├── sentence_splitter.py   # 中文分句工具（按标点拆句，供 TTS 逐句输出）
├── test_sentence_splitter.py # 分句单元测试（9 个用例）
├── tts_client.py          # TTS 客户端（aiohttp 异步调用 TTS 服务，含 Windows SSL 修复）
├── tts_server.py          # TTS 独立服务（封装 CosyVoice-300M-SFT，端口 9233）
├── tools.py               # Qdrant RAG 工具（get_info_from_local_db）
├── config.py              # 配置加载（从 .env 读取）
├── database.py            # SQLite 用户数据库（users 表）
├── auth.py                # JWT 认证（create/decode token, password hash）
├── sys_logger.py          # 全局日志系统（终端 + 文件双输出）
├── sys_memory.py          # RedisSaver（LangGraph checkpoint 持久化 + 命令系统方法）
├── start_redis.py         # Redis 服务器管理（启动/停止）
├── test_chat.py           # 测试脚本（SSE 流式聊天）
├── test_commands_manual.py # 命令系统手动测试脚本
├── users.db               # SQLite 用户数据库文件（运行时生成）
│
├── static/                # 前端文件
│   ├── index.html         # 主聊天页面
│   ├── login.html         # 登录/注册页面
│   ├── css/
│   │   ├── style.css      # 主页面样式
│   │   └── login.css      # 登录页样式
│   └── js/
│       ├── app.js         # 主页面逻辑（SSE 处理、状态显示）
│       └── login.js       # 登录/注册逻辑
│
├── logs/                  # 日志目录（运行时生成）
│   └── global.log         # 全局日志文件
│
├── tests/                 # 测试文件
│   ├── test_error_handling.py
│   ├── test_latency.py
│   └── test_logging_integration.py
│
└── docs/                  # 文档
    ├── custom/
    │   ├── preview.html                    # 网页预览
    │   ├── 可视化聊天机器人项目准备.md
    │   └── 机器人人设.md
    ├── superpowers/
    │   ├── specs/
    │   │   ├── 2026-07-25-visualization-chatbot-design.md   # Phase 1 设计文档
    │   │   └── 2026-07-28-command-system-design.md          # 命令系统设计文档
    │   └── plans/
    │       ├── 2026-07-26-phase1-core-pipeline.md           # Phase 1 实施计划
    │       ├── 2026-07-28-command-system.md                 # 命令系统实施计划
    │       └── 2026-07-30-phase2-tts-integration.md         # Phase 2 TTS 实施计划
    └── test_reports/
        └── phase1-test-report.md           # Phase 1 测试报告
```

## 运行方式
```bash
# 终端 1：启动 TTS 服务（可选，不开则文字正常但无语音）
conda run -n py310 python tts_server.py

# 终端 2：启动主服务
conda run -n py310 python server.py
```

## 重要配置
- `MEMORY_TOKEN_LIMIT=20000`: 上下文 token 上限
- `MAX_CHECKPOINTS=5`: Redis 最大 checkpoint 数
- LLM 超时: 60 秒
- 工具超时: 20 秒

## 已知问题
- astream_events 抛出 NotImplementedError，使用 ainvoke + 回调替代
- 浏览器缓存问题：修改前端后需要 Ctrl+Shift+R 刷新
- Windows SSL 证书加载 bug：aiohttp 导入时 `ssl.create_default_context()` 调用 `_load_windows_store_certs` 可能抛出 `NOT_ENOUGH_DATA`。已在 `tts_client.py` 顶部用 monkey-patch 修复（改为使用 certifi 的 CA 证书包）
- pip 安装时如遇 SSL 错误：`export SSL_CERT_FILE="<certifi_path>/cacert.pem"` 后用默认 PyPI（不用阿里云镜像）
- NumPy 版本冲突：CosyVoice 依赖 `pyworld` 需要 NumPy 1.x，已降级到 `numpy==1.26.4`
- CosyVoice2-0.5B 是基座模型，`inference_sft` 无内置音色。实际使用 `CosyVoice-300M-SFT`（内置"中文女"/"中文男"等音色）
- pip SSL 全局修复：`export SSL_CERT_FILE="C:/ProgramData/Anaconda3/envs/py310/lib/site-packages/certifi/cacert.pem"`

## Agent 流程图
```
用户输入
    │
    ▼
┌─────────────────┐
│  detect_mood    │ ← 情绪检测（第一个节点）
│  (LLM 调用)     │   捕获 DataInspectionFailed → mood="sensitive", skip_count=1
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│    compact      │ ← 消息压缩
│                 │   如果 skip_count > 0，跳过敏感消息
│                 │   合并 new_messages 到 compact_messages
│                 │   超过阈值时调用 LLM 摘要（或截断降级）
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│     model       │ ← LLM 调用
│                 │   如果 mood="sensitive"，直接返回友好提示
│                 │   否则调用 LLM（带工具绑定）
└────────┬────────┘
         │
         ├── 有 tool_calls ──┐
         │                   ▼
         │            ┌─────────────┐
         │            │   tools     │ ← 执行工具调用
         │            └──────┬──────┘
         │                   │
         │                   ▼
         │            ┌─────────────┐
         │            │   compact   │ ← 合并工具结果
         │            └──────┬──────┘
         │                   │
         │                   ▼
         │            ┌─────────────┐
         └───────────►│   model     │ ← 再次调用 LLM
                      └──────┬──────┘
                             │
                             ▼
                      返回最终响应
```

## 常见错误和解决方案

### 1. bcrypt 版本问题
**错误**: `passlib 1.7.4` 与新版 bcrypt 不兼容
**解决**: `pip install bcrypt==4.0.1`

### 2. f-string 换行导致 SyntaxError
**错误**: f-string 中包含 `\n\n` 被解释为实际换行
**解决**: 使用字符串拼接替代 f-string
```python
# 错误
f"data: {json.dumps(data)}\n\n"

# 正确
"data: " + json.dumps(data) + "\n\n"
```

### 3. 浏览器缓存问题
**现象**: 修改前端代码后，浏览器仍显示旧版本
**解决**: Ctrl+Shift+R 强制刷新

### 4. astream_events NotImplementedError
**错误**: LangGraph 的 `astream_events(version="v2")` 抛出 NotImplementedError
**解决**: 使用 `ainvoke` + `BaseCallbackHandler` 替代

### 5. 端口被占用
**错误**: `[Errno 10048] error while attempting to bind`
**解决**:
```bash
# 查找占用端口的进程
netstat -ano | findstr :8000
# 杀掉进程
cmd //c "taskkill /PID <PID> /F"
```

## API 端点说明

### POST /chat - SSE 流式聊天
**请求**:
```json
{
    "query": "用户消息",
    "user_id": "用户ID"
}
```
**响应** (SSE 事件流):
```
data: {"type": "status", "status": "detecting_mood"}
data: {"type": "status", "status": "compacting"}
data: {"type": "status", "status": "thinking"}
data: {"type": "status", "status": "tool_call", "tool": "工具调用"}
data: {"type": "text", "content": "第一句话"}
data: {"type": "audio", "data": "<base64 WAV>"}
data: {"type": "text", "content": "第二句话"}
data: {"type": "audio", "data": "<base64 WAV>"}
data: {"type": "audio_done"}
data: {"type": "mood", "mood": "friendly"}
data: {"type": "done"}
```

### POST /api/register - 用户注册
**请求**:
```json
{
    "username": "用户名",
    "password": "密码（至少6位）"
}
```
**响应**: `{"message": "注册成功"}`

### POST /api/login - 用户登录
**请求**:
```json
{
    "username": "用户名",
    "password": "密码"
}
```
**响应**: `{"token": "JWT token", "username": "用户名"}`

## 命令系统使用指南

在聊天框中输入以 `/` 开头的命令：

| 命令 | 功能 | 示例 |
|------|------|------|
| `/clear` | 清除所有对话记忆 | `/clear` |
| `/compact` | 手动压缩上下文 | `/compact` |
| `/status` | 查看当前状态 | `/status` |
| `/mood` | 查看当前情绪 | `/mood` |
| `/mood <情绪>` | 设置情绪（覆盖自动检测） | `/mood cheerful` |
| `/help` | 显示帮助 | `/help` |

**有效情绪**: default, upbeat, angry, depressed, friendly, cheerful

**实现细节**:
- 命令在 server.py 的 `_event_stream()` 开头拦截，不经过 LLM
- 情绪覆盖存储在 Redis (`langgraph:mood_override:{user_id}`)
- `/clear` 同时清除 checkpoints 和 mood_override
- `/compact` 调用 memory_utils.compact_messages() 进行压缩

## 调试技巧

### 1. 查看日志
```bash
# 实时查看日志
tail -f logs/global.log

# 查看最近 50 行
tail -50 logs/global.log

# 搜索错误
grep "ERROR" logs/global.log
```

### 2. 测试 SSE 流式聊天
```bash
# 使用测试脚本
conda run -n py310 python test_chat.py

# 使用 curl
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "你好", "user_id": "test"}' \
  --no-buffer
```

### 3. 检查 Redis
```bash
# 连接 Redis
redis-cli

# 查看所有 key
keys *

# 查看特定用户的 checkpoint
get langgraph:checkpoints:test_user
```

### 4. 检查用户数据库
```bash
# 使用 sqlite3 查看
sqlite3 users.db "SELECT id, username, created_at FROM users;"
```

### 5. 重启服务器
```bash
# 杀掉旧进程
cmd //c "taskkill /PID <PID> /F"

# 启动新进程
conda run -n py310 python server.py
```

### 6. 测试命令系统
```bash
# 使用手动测试脚本
conda run -n py310 python test_commands_manual.py

# 或直接在浏览器聊天框输入命令测试
```

### 7. 检查情绪覆盖
```bash
# 连接 Redis
redis-cli

# 查看用户的情绪覆盖
get langgraph:mood_override:test_user

# 手动清除情绪覆盖
del langgraph:mood_override:test_user
```
