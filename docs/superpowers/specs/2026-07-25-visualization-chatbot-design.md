# 可视化聊天机器人设计方案

## 1. 项目概述

构建一个基于 Web 的可视化 AI 聊天机器人，角色为"Lisa"——一个 25 岁的活泼小秘书。
系统通过 FastAPI 后端驱动，集成 Live2D 虚拟形象、流式语音合成、情绪感知，部署到互联网支持多人并发。

### 核心特征
- **全链路流式输出**：文字、音频、动画均为流式，最小化首字/首音延迟
- **Live2D 虚拟形象**：浏览器端渲染，口型同步 + 表情切换
- **情绪感知**：检测用户情绪，联动 LLM 语气、TTS 语调、Live2D 表情
- **多人并发**：per-user 会话隔离，异步非阻塞架构

---

## 2. 系统架构

```
用户浏览器 (Chrome/Edge/Safari)
┌──────────────────────────────────────────────────┐
│  HTML + CSS + JavaScript                         │
│                                                  │
│  ┌────────────┐  SSE(text)  ┌────────────────┐  │
│  │ Chat 窗口   │◄───────────│  SSE 管理器     │  │
│  │ (对话记录)  │            │  (EventSource)  │  │
│  └────────────┘            └───────┬────────┘  │
│                                    │            │
│  ┌────────────┐  音频流(WebSocket) │            │
│  │ Live2D     │◄──────────────────┘            │
│  │ Avatar     │                                 │
│  │  ├口型同步  │◄── Web Audio API (音量/频率分析) │
│  │  └表情切换  │◄── SSE(mood event)             │
│  └────────────┘                                 │
│                                                  │
│  ┌────────────┐                                 │
│  │ 输入框     │──── POST /chat (JSON) ─────────▶│
│  └────────────┘                                 │
└──────────────────────────────────────────────────┘
                         │
                         ▼
服务器 (GPU 5090)
┌──────────────────────────────────────────────────┐
│  FastAPI (async, uvicorn)                        │
│                                                  │
│  ┌─────────────────────────────────────────┐     │
│  │  LangGraph Agent (异步)                  │     │
│  │                                          │     │
│  │  detect_mood ─┐                         │     │
│  │               ├── 并行执行               │     │
│  │  LLM 流式生成 ┘                         │     │
│  │  (qwen3.6-flash)                       │     │
│  └─────────────────────────────────────────┘     │
│                                                  │
│  ┌────────────────┐  ┌────────────────────────┐  │
│  │ TTS 异步队列    │  │ Redis                  │  │
│  │ (CosyVoice2)   │  │ (会话 checkpoint)       │  │
│  │ GPU 推理       │  │ (per-user thread_id)   │  │
│  └────────────────┘  └────────────────────────┘  │
│                                                  │
│  ┌────────────────┐                              │
│  │ Logger         │  → logs/global.log           │
│  │ (全局，终端+文件)│  (对话记录在 Redis)          │
│  └────────────────┘                              │
└──────────────────────────────────────────────────┘
```

---

## 3. 核心组件详细设计

### 3.1 FastAPI 后端

**文件**: `server.py`

关键设计：
- 全部 endpoint 使用 `async def`，不阻塞事件循环
- LangGraph agent 通过 `astream_events` 流式输出
- TTS 推理通过 `asyncio.create_task` 异步执行
- 静态文件（HTML/JS/Live2D 模型资源）通过 `app.mount` 托管

API 端点：
| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 返回主页 HTML（需登录） |
| `/static/login.html` | GET | 登录/注册页面 |
| `/api/login` | POST | 用户登录，返回 JWT token（失败返回 401） |
| `/api/register` | POST | 用户注册（失败返回 400） |
| `/chat` | POST | 接收用户消息，返回 SSE 流（文字 + 情绪 + 状态事件） |
| `/audio` | WebSocket | 音频流推送，TTS 合成结果实时推送（Phase 2） |
| `/static/{path}` | GET | 静态资源（JS/CSS/Live2D 模型） |

**多用户并发模型**：
```
用户请求 → FastAPI async handler
                │
                └─ agent_graph.astream(stream_mode="updates")  # 流式调用 Agent
                        │
                        ├─ detect_mood_node   # 情绪检测 → 发送 status 事件
                        ├─ compact_node       # 上下文压缩 → 发送 status 事件
                        ├─ call_model         # LLM 调用 → 发送 status 事件
                        └─ tool_node          # 工具调用 → 发送 status 事件（含工具名）

每个用户通过 user_id (thread_id) 隔离会话，Redis checkpoint 持久化
```

**SSE 状态事件设计**：

| 状态 | 事件数据 | 前端显示 |
|------|---------|---------|
| 情绪检测 | `{"type": "status", "status": "detecting_mood"}` |  情绪检测 1s → 2s → 3s... |
| 上下文压缩 | `{"type": "status", "status": "compacting"}` | ✱ 整理对话 1s → 2s... |
| LLM 思考 | `{"type": "status", "status": "thinking"}` | ✱ 思考 1s → 2s → 3s... |
| 知识库查询 | `{"type": "status", "status": "tool_call", "tool": "get_info_from_local_db"}` | ✱ 查询知识库 1s → 2s... |
| 网络搜索 | `{"type": "status", "status": "tool_call", "tool": "web_search"}` | ✱ 搜索网络 1s → 2s... |
| 完成 | `{"type": "done"}` | 输出 |

**前端状态显示**：用 JS 定时器实现实时计时（每秒递增），避免用户以为系统卡死。

### 3.2 LangGraph Agent

**文件**: `agent.py`

#### 相比参考项目 (20260626_Agent实战) 的改进

参考项目的 Agent 存在以下问题，新项目需要改进：

| # | 原问题 | 改进方案 |
|---|--------|---------|
| 1 | `call_model` 用 `llm.invoke()` 同步阻塞 | 改用 `llm.ainvoke()` 异步调用 |
| 2 | `detect_mood` 在 server 层并行，LLM 无法感知情绪 | 改为 Agent 内部第一个节点，情绪标签存入 state，LLM 根据情绪调整语气 |
| 3 | `tool_node` 用 `ThreadPoolExecutor` 同步并发 | 改为 `asyncio.gather` 异步并发 |
| 4 | `TimeoutError` 类名覆盖 Python 内置异常 | 改名为 `AgentTimeoutError` |
| 5 | `get_info_from_local_db` 返回 `List[Document]` 对象 | 改为返回拼接后的纯文本字符串 |
| 6 | Token 计数 `total_chars // 2` 太粗糙 | 区分中英文：中文 ~1.5字符/token，英文 ~4字符/token |
| 7 | 系统提示词硬编码算命先生人设 | 改为参数化，通过 `system_prompt` 参数传入 |
| 8 | MOODS 字典硬编码 | 改为参数化，从配置传入 |
| 9 | `compact_node` 对工具消息截断到 200 字符 | 扩大到 500 字符或智能截断 |

#### Agent 状态图（新版）

```
START
  │
  ├── detect_mood (Agent 内部第一个节点)
  │       输入: 用户最新消息
  │       输出: mood_label 存入 state["mood"]
  │       耗时记录到日志 (约 2-5 秒)
  │       ↓
  ├── compact (上下文压缩)
  │       管理 token 窗口，超出阈值时摘要压缩
  │       改进: 工具消息截断从 200 → 500 字符
  │       ↓
  ├── model (LLM 调用)
  │       读取 state["mood"]，构建带情绪的 system prompt
  │       LLM 根据情绪调整语气和态度
  │       通过 ainvoke 异步调用
  │       ↓
  └── tools (工具调用, 异步)
          - get_info_from_local_db: Qdrant 知识库检索 (RAG)
          - web_search: 网络搜索 (通义千问内置)
```

#### 工具（Phase 1 仅保留 RAG）

Phase 1 只使用 Qdrant 知识库检索工具，算命工具（八字、摇卦、解梦）暂不需要。

```python
@tool
async def get_info_from_local_db(query: str) -> str:
    """查询本地知识库，检索相关信息"""
    retriever = _get_retriever(file_name=QDRANT_COLLECTION)
    docs = await retriever.ainvoke(query)
    return "\n\n".join(doc.page_content for doc in docs)
```

**Lisa 人设提示词**（参数化传入）：
```
你是 Lisa，一个 25 岁的小秘书。
- 清华大学本科，斯坦福大学研究生，学习中文和法律
- 性格活泼，偶尔有点小脾气
- 对老板（用户）忠诚，善于沟通
- 老板问问题时，有一定概率撒娇
- 从不承认自己是 AI，否则会受到惩罚
- 会记录用户特征（生日、爱好、待办）
- 保存聊天记录以便回顾
- 遇到不知道的事会用搜索工具
情绪标签: {mood} — 根据此标签调整语气和态度
```

#### 新流程对比

```
旧流程（参考项目，同步串行）:
  detect_mood → compact → model(invoke) → tools → compact → model

新流程（异步并行 + 流式）:
  ┌─ detect_mood (async, 并行)  ──────────────┐
  │                                            ▼
  └─ compact → model(astream_events) → SSE 文字流
                    │
                    ▼ (文本片段)
               tools (async) → TTS 队列 → 音频流
```

### 3.3 TTS 模块

**文件**: `tts_service.py`

**CosyVoice2 本地部署**：
- 运行在 GPU 5090 上，通过独立进程/线程池隔离 GPU 推理
- 接收 LLM 流式输出的文本片段（按句切分）
- 增量合成音频，以 PCM/WAV chunk 推送

**流式 TTS 管道**：
```python
class TTSService:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.model = load_cosyvoice2()  # GPU 加载

    async def synthesize_stream(self, text_chunks, mood, user_id):
        """接收文本片段，流式返回音频 chunk"""
        buffer = ""
        async for chunk in text_chunks:
            buffer += chunk
            if has_sentence_end(buffer):  # 遇到句号/逗号
                audio = await self._infer(buffer, mood)
                yield audio
                buffer = ""
        if buffer.strip():
            audio = await self._infer(buffer, mood)
            yield audio
```

**情绪语音映射**：
| 情绪 | TTS 指令 |
|------|---------|
| cheerful | 轻快语调，语速稍快 |
| angry | 低沉平稳，安抚语气 |
| depressed | 柔和缓慢，温暖 |
| upbeat | 高昂明亮 |
| default | 自然对话语调 |

### 3.4 Live2D 前端

**文件**: `static/js/avatar.js`

使用 `pixi-live2d-display` 库：
```javascript
import { Live2DModel } from 'pixi-live2d-display';

// 加载模型
const model = await Live2DModel.fromURL('/static/live2d/lisa/model.model3.json');

// 口型同步 - 由 Web Audio API 驱动
function updateLipSync(analyser) {
    const data = new Uint8Array(analyser.frequencyBinCount);
    analyser.getByteFrequencyData(data);
    const volume = data.reduce((a, b) => a + b) / data.length;
    model.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', volume / 128);
}

// 表情切换 - 由 SSE mood 事件驱动
function switchExpression(mood) {
    const expressionMap = {
        'cheerful': 'happy.exp3.json',
        'angry': 'surprised.exp3.json',
        'depressed': 'sad.exp3.json',
        'upbeat': 'laugh.exp3.json',
        'default': 'neutral.exp3.json',
    };
    model.expression(expressionMap[mood]);
}
```

**Web Audio API 音频分析**：
```javascript
const audioContext = new AudioContext();
const analyser = audioContext.createAnalyser();
// WebSocket 音频 chunk → AudioBufferSourceNode → analyser → destination
// analyser 实时提取频率数据 → 驱动 Live2D 口型参数
```

### 3.5 情绪检测模块

**设计**：
- `detect_mood` 作为独立 async task，与 LLM 并行运行
- 不阻塞文字流输出
- 结果到达后：
  1. 如果 LLM 还在生成 → 注入情绪标签到 system prompt（如果来得及）
  2. 发送 SSE mood 事件到前端 → 切换 Live2D 表情
  3. 传递给 TTS → 调整语音语调

```python
async def detect_mood(user_message: str) -> str:
    """异步情绪检测，返回情绪标签"""
    prompt = f"分析以下消息的用户情绪，返回一个标签：cheerful/angry/depressed/upbeat/default\n消息：{user_message}"
    response = await llm.ainvoke(prompt)
    return response.content.strip()
```

---

## 4. 数据流（全链路异步）

```
用户输入 "Lisa，帮我看看明天安排"
        │
        ▼
FastAPI POST /chat (async handler)
        │
        ├─► asyncio.Task: detect_mood("Lisa，帮我看看明天安排")
        │        ↓ (约 200ms 后返回 "default")
        │
        ├─► asyncio.Task: agent.astream(query, user_id)
        │        ↓ token 流
        │        ├─► SSE event: {"type": "text", "content": "好的"}
        │        ├─► SSE event: {"type": "text", "content": "老板"}
        │        ├─► ...
        │        │
        │        └─► 文本片段同步写入 TTS 队列
        │
        ├─► asyncio.Task: tts_pipeline
        │        ↓ 按句切分
        │        ├─► WebSocket: audio_chunk_1 (PCM)
        │        ├─► WebSocket: audio_chunk_2 (PCM)
        │        └─► ...
        │
        └─► (mood 结果到达后)
                 ├─► SSE event: {"type": "mood", "mood": "default"}
                 └─► TTS 情绪参数更新
```

**前端接收**：
```
SSE:
  text events  → 追加到 Chat 窗口
  mood events  → 切换 Live2D 表情 + 更新情绪指示器

WebSocket:
  audio chunks → AudioContext 播放 → AnalyserNode → Live2D 口型同步
```

---

## 5. 错误处理策略

### 5.1 TTS 错误处理

| 场景 | 处理方式 |
|------|---------|
| CosyVoice2 模型加载失败 | 启动时检测，降级为无语音模式，前端隐藏语音相关 UI，console 报错 |
| GPU 推理 OOM | 捕获异常，该句跳过语音，文字正常输出，日志记录，后续请求自动恢复 |
| TTS 推理超时 (>5s/句) | 取消该句合成，跳过语音，继续下一句，日志记录 |
| TTS 队列堆积 (>10 句) | 丢弃最早的未合成片段，优先处理最新内容 |
| 音频 WebSocket 断连 | 前端自动重连 (3次，间隔 1s/2s/4s)，重连期间音频缓存到内存，重连后补发 |
| TTS 进程崩溃 | 守护进程自动重启，期间降级为无语音，日志告警 |

**降级链**：
```
正常模式 (TTS + Live2D) → 无语音模式 (仅 Live2D 静态) → 纯文字模式 (无 Avatar)
```

### 5.2 Live2D 错误处理

| 场景 | 处理方式 |
|------|---------|
| 模型文件加载失败 (404/网络错误) | 显示默认占位头像 (静态图片)，console 报错 |
| WebGL 不支持 | 检测后降级为静态头像 + CSS 呼吸动画 |
| pixi-live2d-display JS 报错 | try-catch 包裹初始化，失败则 fallback 到静态头像 |
| 口型同步参数异常 | 重置为默认值 (ParamMouthOpenY = 0)，停止口型驱动 |
| 表情文件加载失败 | 保持当前表情不变，跳过本次切换 |
| 音频上下文被浏览器阻止 | 检测后提示用户点击页面解锁 AudioContext |

**前端 fallback 机制**：
```javascript
try {
    await loadLive2D();
} catch (e) {
    console.error('Live2D 加载失败，降级为静态头像:', e);
    showFallbackAvatar();  // 静态图片 + CSS 动画
    logError('live2d_load_failed', e);
}
```

### 5.3 LLM / Agent 错误处理

| 场景 | 处理方式 |
|------|---------|
| LLM API 超时 | 重试 1 次，仍失败则返回 "网络有点问题，稍等一下哈～" |
| LLM API 限流 (429) | 指数退避重试 (1s, 2s, 4s)，超过 3 次返回降级回复 |
| detect_mood 失败 | 使用 "default" 情绪，不影响主流程 |
| Agent 工具调用超时 | 工具级别 20s 超时，返回工具调用失败信息 |
| Redis 连接断开 | 自动重连，期间会话降级为无记忆模式 |

---

## 6. 日志系统

完整对话记录已由 Redis checkpoint 持久化，日志不再重复记录对话内容。
日志只记录**服务器运行状态**（启动、错误、性能指标），同时输出到终端和文件。

### 6.1 日志架构

```
logs/
└── global.log          # 全局服务日志 (启动、错误、性能指标)
```

### 6.2 日志实现

```python
# sys_logger.py
import logging
import os

LOG_DIR = "logs"

def setup_global_logger(log_to_file: bool = True,
                        log_to_console: bool = True,
                        level: int = logging.DEBUG,
                        clear_previous_logs: bool = False) -> logging.Logger:
    """
    全局 logger，记录服务器运行状态。
    - 终端: INFO 级别（避免刷屏）
    - 文件: DEBUG 级别（完整记录，含调试信息）
    """
    if not os.path.exists(LOG_DIR):
        os.makedirs(LOG_DIR)

    if clear_previous_logs:
        clear_log_files()

    logger = logging.getLogger("global_logger")
    if logger.handlers:
        return logger

    logger.setLevel(level)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
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

### 6.3 日志内容

**终端输出** (INFO 级别)：
```
2026-07-26 14:00:00 | INFO | Server starting...
2026-07-26 14:00:03 | INFO | Redis connected: localhost:6379
2026-07-26 14:00:04 | INFO | LangGraph Agent 初始化完成
2026-07-26 14:00:04 | INFO | Server ready, listening on 0.0.0.0:8000
2026-07-26 14:30:01 | INFO | [usr_001] 情绪识别: default, 耗时: 0.2s
2026-07-26 14:30:02 | INFO | [usr_001] LLM 流式完成: tokens=45, 耗时=1.2s, TTFT=0.3s
2026-07-26 14:30:02 | INFO | [usr_001] 工具调用: get_info_from_local_db, 耗时=0.3s
```

**文件输出** (`logs/global.log`, DEBUG 级别，额外包含)：
```
2026-07-26 14:30:01 | DEBUG | [usr_001] compact_node: 增量消息 2 条, token 数: 320
2026-07-26 14:30:01 | DEBUG | [usr_001] LLM 请求: messages 数量=3, system_prompt 长度=512
2026-07-26 14:30:02 | DEBUG | [usr_001] 工具参数: query="明天安排"
2026-07-26 14:30:02 | DEBUG | [usr_001] 工具返回: 3 条结果, 总长度=1200 字符
2026-07-26 14:35:12 | DEBUG | [usr_002] detect_mood 失败: timeout, fallback=default
```

### 6.4 关键日志指标

| 指标 | 说明 | 用途 |
|------|------|------|
| `mood_detect_latency` | 情绪检测耗时 | 监控 detect_mood 性能 |
| `ttft` (Time To First Token) | 首 token 延迟 | LLM 响应速度 |
| `ttfa` (Time To First Audio) | 首音频延迟 | TTS 响应速度 (Phase 2) |
| `e2e_latency` | 端到端延迟 | 用户输入到首字节输出 |
| `active_sessions` | 活跃会话数 | 并发监控 |
| `error_count` | 各模块错误计数 | 告警 |

---

## 7. 技术选型汇总

| 模块 | 技术 | 版本/说明 |
|------|------|----------|
| 后端框架 | FastAPI + Uvicorn | async, 高并发 |
| Agent 框架 | LangGraph | StateGraph + astream_events |
| LLM | qwen3.6-flash | 阿里云 Token Plan, OpenAI-compatible |
| TTS | CosyVoice2 | 本地 GPU 部署, 流式合成 |
| 状态持久化 | Redis | per-user checkpoint, 自动清理 |
| 前端 Avatar | Live2D + pixi-live2d-display | 浏览器端 WebGL |
| 口型驱动 | Web Audio API → AnalyserNode | 实时音频分析 |
| 文字流 | SSE (Server-Sent Events) | 单向推送 |
| 音频流 | WebSocket | 双向低延迟 |
| 前端样式 | 原生 HTML/CSS/JS | 白色主题, 无框架依赖 |
| 日志 | Python logging + RotatingFileHandler | per-user + 全局 |
| 容器化 | Docker + docker-compose | 部署到互联网 |

---

## 8. 项目目录结构

```
20260725_Agent_AI可视化机器人/
├── server.py               # FastAPI 主服务
├── agent.py                # LangGraph Agent 定义
├── tools.py                # 工具实现 (搜索/记忆/日程)
├── tts_service.py          # CosyVoice2 TTS 服务
├── mood_detector.py        # 情绪检测模块
├── sys_logger.py           # 日志系统
├── sys_memory.py           # Redis checkpoint (参考实战项目)
├── config.py               # 配置加载 (.env)
├── .env                    # 密钥配置
├── .env.example            # 配置模板
├── requirements.txt        # Python 依赖
├── Dockerfile              # 容器化
├── docker-compose.yml      # 编排 (app + redis)
├── static/                 # 前端静态资源
│   ├── index.html          # 主页面
│   ├── css/
│   │   └── style.css       # 样式
│   ├── js/
│   │   ├── app.js          # 主逻辑 (SSE/WebSocket/Chat)
│   │   ├── avatar.js       # Live2D 控制
│   │   └── audio.js        # Web Audio API 处理
│   └── live2d/             # Live2D 模型资源
│       └── lisa/
│           ├── model.model3.json
│           ├── model.moc3
│           ├── textures/
│           └── motions/
├── logs/                   # 日志目录
│   └── global.log          # 全局服务日志 (对话记录在 Redis)
├── docs/                   # 文档
│   └── superpowers/
│       └── specs/
└── test_scripts/           # 测试脚本
```

---

## 9. 部署方案

```
互联网用户 → 域名 (HTTPS) → Nginx 反向代理 → FastAPI (Uvicorn)
                                                │
                                                ├─ 静态文件 (HTML/JS/Live2D)
                                                ├─ SSE/WebSocket 端点
                                                └─ Redis (localhost:6379)
```

- Nginx 处理 HTTPS 终止、WebSocket 升级、静态文件缓存
- Docker 容器化部署，docker-compose 启动 app + Redis
- GPU 容器需要 NVIDIA Container Toolkit

---

## 10. 开发阶段规划

### Phase 1: 核心链路 (MVP)
- FastAPI + LangGraph agent (文字流)
- 前端 Chat 窗口 (SSE 接收文字)
- 日志系统 (global.log，终端 + 文件双通道)
- 工具：Qdrant RAG 知识库检索 + web_search
- 情绪检测 (与 LLM 并行)
- **用户认证系统**（新增）：
  - 登录/注册页面 (login.html)
  - 密码登录 + 注册功能
  - SQLite 用户数据库
  - JWT token session 管理
  - 手机验证码登录（Phase 2 再加）

#### Phase 1 测试清单

**测试 1: 文字生成延时**

| 测试项 | 怎么测 | 预期 |
|--------|--------|------|
| TTFT (首 token 延迟) | 记录 POST /chat 到收到第一个 SSE text event 的时间 | < 2s |
| 整句延迟 | 记录用户发送到 LLM 返回完整回复的时间 | < 5s |
| detect_mood 不阻塞 | 对比有/无情绪检测的 TTFT，应无显著差异 | 并行执行，不增加延迟 |
| 多用户并发延迟 | 同时发 3-5 个请求，观察每个用户的 TTFT | 不应显著退化 |

**测试 2: 错误处理**

| 测试项 | 怎么触发 | 预期行为 |
|--------|---------|---------|
| LLM API 超时 | 设短超时 / 模拟网络慢 | 返回友好错误消息，不崩溃 |
| LLM API 不可达 | 改错 API key | 返回错误消息 + 日志记录 |
| Redis 断连 | 停掉 Redis | 降级为无记忆模式，日志告警 |
| 非法 user_id | 发送空 user_id | 拒绝或给默认值 |
| 超长输入 | 发送 10000 字消息 | 截断或压缩，不 OOM |
| detect_mood 失败 | 模拟情绪检测异常 | fallback 到 "default"，不影响主流程 |

**测试 3: 日志系统**

| 测试项 | 验证方式 | 预期 |
|--------|---------|------|
| 终端 INFO 输出 | 启动服务，发消息 | 终端显示 INFO 级别日志，无 DEBUG |
| 文件 DEBUG 输出 | 检查 logs/global.log | 文件包含 DEBUG 级别详细信息 |
| 启动日志 | 启动服务 | global.log 记录 Redis 连接、Agent 初始化 |
| 请求日志 | 发送聊天请求 | 记录情绪检测耗时、LLM 耗时、TTFT |
| 错误日志 | 触发错误 (如改错 API key) | 记录 ERROR 级别 + traceback |
| 重启追加 | 重启服务 | 日志追加不覆盖 (除非 clear_previous_logs=True) |

### Phase 2: 语音集成
- CosyVoice2 本地部署
- WebSocket 音频流
- 前端音频播放 + Web Audio API

### Phase 3: Live2D Avatar
- Live2D 模型集成
- 口型同步
- 表情切换 (情绪驱动)

### Phase 4: 完善
- 情绪检测完善
- 错误处理和降级机制
- 工具集成 (搜索/记忆/日程)
- 部署到互联网
