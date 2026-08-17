# Lisa 的办公室 - AI 可视化聊天机器人

一个带 MuseTalk 数字人虚拟形象的 AI 聊天机器人，支持流式文本输出、WebRTC 实时视频流、情绪检测、用户认证、斜杠命令系统。

## 技术栈

- **后端**: FastAPI + SSE 流式输出
- **Agent**: LangGraph（全异步）
- **LLM**: qwen3.6-flash（阿里云 Token Plan）
- **向量数据库**: Qdrant（RAG 知识库）
- **缓存**: Redis（LangGraph checkpoint 持久化）
- **用户数据库**: SQLite
- **认证**: JWT token（python-jose + bcrypt）
- **数字人**: MuseTalk + LiveTalking（WebRTC 实时口型同步视频流）

## 功能特性

### 核心流程
- 流式文本输出（SSE 实时推送）
- 情绪检测（6 种情绪：cheerful / upbeat / friendly / depressed / angry / default）
- 消息压缩（超过 token 上限自动摘要）
- Qdrant RAG 知识库工具
- 实时状态显示（检测情绪 → 压缩 → 思考 → 工具调用）

### 用户系统
- 用户注册 / 登录
- JWT token 认证
- 每个用户独立的对话记忆

### 命令系统

在聊天框输入以 `/` 开头的命令：

| 命令 | 功能 | 示例 |
|------|------|------|
| `/clear` | 清除所有对话记忆 | `/clear` |
| `/compact` | 手动压缩上下文 | `/compact` |
| `/status` | 查看当前状态 | `/status` |
| `/mood` | 查看当前情绪 | `/mood` |
| `/mood <情绪>` | 手动设置情绪 | `/mood cheerful` |
| `/help` | 显示帮助 | `/help` |

### 数字人（Phase 3）
- MuseTalk 实时口型同步（基于唇部动作驱动）
- WebRTC 实时视频流传输（本地直连，低延迟）
- 页面加载自动连接 LiveTalking（15 秒超时，失败降级为纯文字聊天）
- 发送按钮智能锁定（连接中/发送中/说话中禁用，说完自动解锁）
- Chunk 流水线优化（长文本首帧延迟 ~2s，chunk 间无缝衔接）
- Session 池复用（预创建 session，GPU 显存稳定 1613MB）

## 项目结构

```
├── server.py              # FastAPI 主服务器，SSE 流式输出
├── agent.py               # LangGraph Agent（4 节点）
├── commands.py            # 命令处理模块
├── memory_utils.py        # 消息压缩工具
├── tools.py               # Qdrant RAG 工具
├── config.py              # 配置加载
├── database.py            # SQLite 用户数据库
├── auth.py                # JWT 认证
├── sys_logger.py          # 日志系统
├── sys_memory.py          # RedisSaver（checkpoint 持久化）
├── start_redis.py         # Redis 服务器管理
├── .env.example           # 环境变量模板
├── requirements.txt       # 依赖列表
│
├── static/                # 前端文件
│   ├── index.html         # 主聊天页面
│   ├── login.html         # 登录页面
│   ├── css/               # 样式
│   └── js/                # 前端逻辑（含 WebRTC 连接管理）
│
└── docs/                  # 项目文档
    ├── custom/            # 项目设计文档
    ├── superpowers/       # 设计规格和实施计划
    └── test_reports/      # 测试报告
```

## 快速开始

### 1. 克隆项目

```bash
git clone <repo-url>
cd 20260725_Agent_AI可视化机器人
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API 密钥
```

### 4. 准备 Redis

```bash
redis-server/redis-server.exe redis_cache/redis.conf
```

### 5. 启动服务

需要**两个终端**分别启动：

**终端 1 — LiveTalking 数字人服务（WebRTC 视频流）**：
```bash
cd G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe app.py \
  --model musetalk --avatar_id lisa_avatar \
  --transport webrtc --listenport 8010 --pool_size 2
```

**终端 2 — Lisa 主服务（FastAPI + SSE 文字流）**：
```bash
conda run -n py310 python server.py
```

服务启动后访问 `http://127.0.0.1:8000`，页面会自动连接数字人视频流（连接失败时降级为纯文字聊天，不影响使用）。

### 6. 浏览器测试

- 访问 `http://127.0.0.1:8000` → Lisa 聊天主界面
- 访问 `http://127.0.0.1:8010/webrtcapi.html` → LiveTalking 独立测试页

## Agent 架构

```
用户输入
    │
    ▼
┌─────────────────┐
│  detect_mood    │  情绪检测（6 种情绪）
└────────┬────────┘
         ▼
┌─────────────────┐
│    compact      │  消息压缩（LLM 摘要 + 截断降级）
└────────┬────────┘
         ▼
┌─────────────────┐
│     model       │  LLM 调用（带工具绑定）
└────────┬────────┘
         │
         ├── 有 tool_calls → tools → compact → model
         │
         └── 无 tool_calls → 返回最终响应
```

## 整体架构（Phase 3）

```
用户 → FastAPI → LangGraph → SSE（文字）→ 前端
                  ↓
              LiveTalking API（POST /human）
                  ↓
              WebRTC 视频流 → 前端 <video> 元素
```

## Phase 3f 智能交互优化

### 自动连接
- 页面加载时自动建立 WebRTC 连接（15 秒超时）
- 连接失败显示"数字人不可用"，不影响文字聊天
- Edge 浏览器兼容：显式 `play()` 调用 + `muted` 属性

### 发送按钮锁定
- `callState` Proxy 追踪 3 个状态：`isConnecting` / `isSending` / `isSpeaking`
- 连接中 / 发送中 / 数字人说话中 → 按钮禁用
- 50ms 轮询 `/is_speaking`，说完自动解锁
- 30s 超时 + 10s 连续失败兜底（防死锁）

### Chunk 流水线
- 长文本自动分句（`split_sentences()`）+ 分块（`chunk_sentences()`，默认 50 字/chunk）
- 所有 chunks 一次性全部送入 TTS 队列，TTS 线程连续处理
- 每完成一个 chunk 立即进入 ASR→推理→播放流水线，chunk 间无缝衔接
- 400 字文本（8 个 chunks）：首帧延迟 ~2s，chunk 间停顿 0

## Phase 3g 唇型抽搐修复

**问题**：话音结束时嘴唇出现约 10 帧的不自然抽搐。

**原因**：音频尾部进入静音区间后，Whisper 特征提取的 sliding window 混合了历史说话帧与静音帧，导致 MuseTalk 推理结果不稳定。

**修复**（LiveTalking 侧）：
- `inference()` 检测静音帧（`AudioFrameData.type != 0`），生成 `silent_mask`
- 静音帧的推理结果用 `None` 替代，`process_frames()` 走静音分支直接使用原始视频帧
- 避免对不稳定推理结果调用 `paste_back_frame()`，从根源消除嘴型抽搐

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | SSE 流式聊天 |
| POST | `/api/register` | 用户注册 |
| POST | `/api/login` | 用户登录 |
| GET | `/` | 主页 |

**LiveTalking API（独立服务，端口 8010）**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/offer` | 建立 WebRTC 连接 |
| POST | `/human` | 发送文字，触发数字人说话 |
| GET | `/is_speaking?sessionid=xxx` | 查询数字人是否在说话 |
| GET | `/webrtcapi.html` | WebRTC 前端测试页 |

## 重要配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MEMORY_TOKEN_LIMIT` | 20000 | 上下文 token 上限 |
| `MAX_CHECKPOINTS` | 5 | 每个用户最大 checkpoint 数 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 60 | JWT token 过期时间（分钟） |
| `LIVETALKING_URL` | `http://localhost:8010` | LiveTalking 服务地址 |
| `TEXT_SEND_DELAY` | 500 | 前端文字缓冲延迟（ms） |
| `SENTENCE_INTERVAL` | 1000 | 数字人说话句间间隔（ms） |

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10（conda py310） | LiveTalking 依赖 |
| PyTorch | 2.10.0+cu128 | CUDA 12.8，RTX 5090D 加速 |
| Node.js | ≥18 | 前端构建 |

## License

MIT
