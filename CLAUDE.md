# Lisa 的办公室 - AI 可视化聊天机器人

## 项目概述
一个带虚拟形象（MuseTalk 数字人）的 AI 聊天机器人，支持流式文本/音频/视频输出、情绪检测、用户认证、命令系统。

**Phase 3 重大变更**: 虚拟形象从 Live2D 改为 MuseTalk 数字人（开源项目 lipku/LiveTalking），通过 WebRTC 实时传输视频流。

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

### Phase 2: TTS 集成（2026-07-31 迁移到 edge-tts）
- [x] edge-tts 云端语音合成（zh-CN-XiaoxiaoNeural 音色，直接调用无需独立服务）
- [x] 语音流式输出（逐句文字 + 音频，sentence_splitter 分句）
- [x] 错误处理（TTS 失败静默降级为文本）
- [x] 前端音频播放（队列 + 声波动画 + 🔊 开关）
- [x] tts_client 新增 tts_stream()（chunk_sentences 合并 + 并发合成 + 预缓冲 + 有序输出）
- [x] 浏览器缓存修复（NoCacheStaticFiles 类）
- [x] **TTS 流畅度已解决**（edge-tts 云端合成极快，消除句子间停顿）

### Phase 3: MuseTalk 数字人集成（进行中，2026-08-07 启动）

#### Phase 3a：LiveTalking Demo 验证 ✅
- [x] 放弃 Docker 方案（WebRTC NAT 穿透失败），改用 Windows 原生运行
- [x] py310 环境直接复用（PyTorch 2.10.0+cu128，无需新建 py312）
- [x] 补装 4 个缺失包：resampy、flask、aiortc、aiohttp_cors
- [x] 创建 utils/__init__.py 修复 Windows 模块导入问题
- [x] MuseTalk 模型加载成功，RTX 5090D CUDA 加速正常
- [x] WebRTC 视频流本地浏览器正常显示（http://127.0.0.1:8010/webrtcapi.html）
- [x] 清理 Docker 镜像（释放 ~65GB）和旧测试脚本

**LiveTalking 文件位置**:
| 项目 | 路径 |
|---|---|
| LiveTalking 代码 | `G:\JupyterProject\LiveTalking\` |
| 模型文件 | `G:\JupyterProject\LiveTalking\models\`（musetalkV15、sd-vae、whisper、dwpose、face-parse-bisent） |
| 数字人素材 | `G:\JupyterProject\LiveTalking\data\avatars\musetalk_avatar1\` |
| 测试脚本 | `tests/test_livetalking_py310.py` |

#### Phase 3b：server.py 改造 ✅
- [x] 移除 edge-tts 相关代码（删除 tts_client.py、sentence_splitter.py）
- [x] SSE 输出简化为纯文字流（音频由 LiveTalking 负责）
- [x] config.py 移除 TTS 配置，新增 LIVETALKING_URL

#### Phase 3c：前端集成 ✅
- [x] index.html 替换 avatar 占位区为 `<video>` 容器
- [x] app.js 新增 WebRTC 连接 LiveTalking（POST /offer）
- [x] app.js 新增 sendToLiveTalking() 发送文字触发数字人（POST /human）
- [x] app.js 移除音频队列、声波动画、TTS 开关逻辑
- [x] style.css 添加视频流样式，移除 audio-wave/tts-toggle 样式

#### Phase 3b+：开始/结束按钮验证 ✅（2026-08-11）
- [x] avatar 区域新增控制栏（`.avatar-controls`）：开始/结束按钮 + 连接状态标签
- [x] `startLiveTalking()` / `stopLiveTalking()` 按钮互斥切换（绿色开始 / 红色结束）
- [x] 内部 `_resetLiveTalking()` 清理旧连接，不操作按钮（修复按钮被覆盖 bug）
- [x] Playwright 自动化测试通过：开始→视频流 576×768 + 按钮切换 → 结束→恢复初始状态
- [x] 发消息验证：SSE 文字回复正常，`sendToLiveTalking()` 调用 `/human` 触发数字人说话
- [x] **已知问题**: `sendToLiveTalking()` 使用 `interrupt: true`，快速连续对话时数字人会被打断

#### Phase 3d：Lisa 形象定制（待开始）
- [ ] 需要生成 Lisa 数字人照片
- [ ] 创建 Lisa 专属 avatar_id

#### Phase 3e：LiveTalking 稳定性修复 ✅（2026-08-10）

**问题根因**：
- 每次新建 session 都加载模型到 GPU，销毁时 PyTorch caching allocator 不释放缓存
- 3 session 并发 → 3 × ~10GB 推理线程 → 30GB → CUDA OOM
- 推理队列（`feat_queue`/`res_frame_queue`/`_queue`）阻塞导致 FPS 从 25 降到 9 后卡死

**解决方案（三层）**：

1. **诊断日志系统**（`utils/diag.py` 独立模块）：
   - `GPUMonitor`：每 100 帧检测显存，增长 >500MB 触发 `torch.cuda.empty_cache()`
   - 推理链路计时：`inference()` / `process_frames()` / `recv()` 各环节耗时
   - 队列预警：`push_video()` 队列堆积时打日志

2. **GPU 资源泄漏修复**：
   - `app.py` 启动前：kill 残留 LiveTalking 进程 + CUDA cache 清理 + 显存报告
   - `app.py` 退出时：`atexit` 注册清理函数，释放 GPU 资源
   - `base_avatar.py`：`_check_gpu_health()` 每 100 帧监控显存

3. **Session 池改造**（核心修复）：
   - `session_manager.py` 重写为 `SessionPool`：启动时 `init_pool()` 预创建 N 个 session
   - `asyncio.Lock` 保护 `acquire()` / `release()` 并发安全
   - WebRTC 断开 → `release()` 回池（`reset_for_reuse()` 清队列 + 重置 speaking，不杀线程）
   - `config.py`：`--max_session` → `--pool_size`，默认 2

**改动文件**：
| 文件 | 改动 |
|---|---|
| `server/session_manager.py` | 重写为 SessionPool（pool/busy 两个字典 + Lock） |
| `avatars/base_avatar.py` | 新增 `reset_for_reuse()` + `_check_gpu_health()` |
| `server/webrtc.py` | 新增 `clear_queues()` + `recv()` FPS 日志 |
| `server/rtc_manager.py` | `create_session` → `acquire`，`remove_session` → `release` |
| `config.py` | `--max_session` → `--pool_size` |
| `app.py` | 启动前清理 + `init_pool()` + atexit 退出清理 |
| `utils/diag.py` | 新建，诊断模块 |

**结果**：
- GPU 显存稳定 1613MB（之前 3 并发爆到 30GB）
- 服务启动预创建 2 session，线程全程运行（空闲时 `queue.get(timeout=1)` 占 <1% CPU）
- WebRTC 断开回池复用，不创建/销毁 session

**Phase 3 启动命令**:
```bash
# LiveTalking 服务（单独终端）
set PYTHONPATH=G:\JupyterProject\LiveTalking
cd G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe app.py --model musetalk --avatar_id musetalk_avatar1 --transport webrtc --listenport 8010 --pool_size 2

# Lisa 主服务（另一个终端）
conda run -n py310 python server.py
```

## 项目文件结构
```
20260725_Agent_AI可视化机器人/
├── .env                    # 环境变量配置（API keys, SECRET_KEY 等）
├── CLAUDE.md              # 项目记忆文件
├── server.py              # FastAPI 主服务器，SSE 流式输出，命令拦截
├── agent.py               # LangGraph Agent（4 节点：detect_mood, compact, model, tools）
├── commands.py            # 命令处理模块（/clear, /compact, /status, /mood, /help）
├── memory_utils.py        # 消息压缩工具（compact_messages 函数，供 agent 和 commands 共用）
├── tools.py               # Qdrant RAG 工具（get_info_from_local_db）
├── config.py              # 配置加载（从 .env 读取）
├── database.py            # SQLite 用户数据库（users 表）
├── auth.py                # JWT 认证（create/decode token, password hash）
├── sys_logger.py          # 全局日志系统（终端 + 文件双输出）
├── sys_memory.py          # RedisSaver（LangGraph checkpoint 持久化 + 命令系统方法）
├── start_redis.py         # Redis 服务器管理（启动/停止）
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
├── tests/                 # 测试文件（所有测试必须放在此目录）
│   ├── test_chat.py               # SSE 流式聊天测试
│   ├── test_commands_manual.py    # 命令系统手动测试
│   ├── test_e2e.py                # 端到端测试
│   ├── test_e2e_real.py           # 端到端测试（长文本）
│   ├── test_error_handling.py     # 错误处理测试
│   ├── test_latency.py            # 延迟测试
│   ├── test_logging_integration.py # 日志集成测试
│   ├── test_server.py             # 服务器测试
│   ├── test_single.py             # 单句计时测试
│   ├── test_stress.py             # 多用户压力测试（3 用户 × 8 请求）
│   └── test_livetalking_py310.py  # LiveTalking 连接测试
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

## 开发规范

- **测试文件必须放在 `tests/` 目录下**，不得在项目根目录创建 `test_*.py` 文件。根目录只放业务代码和配置文件。

## 运行方式
```bash
# 需要两个终端分别启动：

# 终端 1: LiveTalking 服务（WebRTC 视频流）
cd G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe app.py --model musetalk --avatar_id musetalk_avatar1 --transport webrtc --listenport 8010 --pool_size 2

# 终端 2: Lisa 主服务（FastAPI + SSE 文字流）
conda run -n py310 python server.py
```

## 重要配置
- `MEMORY_TOKEN_LIMIT=20000`: 上下文 token 上限
- `MAX_CHECKPOINTS=5`: Redis 最大 checkpoint 数
- LLM 超时: 60 秒
- 工具超时: 20 秒
- `LIVETALKING_URL="http://localhost:8010"`: LiveTalking 服务地址
- `TEXT_SEND_DELAY=500`: 前端文字缓冲延迟（ms），无新 chunk 后发送
- `SENTENCE_INTERVAL=1000`: 数字人说话句间间隔（ms）

## 已知问题

### Phase 1/2 问题
- astream_events 抛出 NotImplementedError，使用 ainvoke + 回调替代
- 浏览器缓存问题：修改前端后需要 Ctrl+Shift+R 刷新
- Windows SSL 证书加载 bug：aiohttp 导入时 `ssl.create_default_context()` 调用 `_load_windows_store_certs` 可能抛出 `NOT_ENOUGH_DATA`。已在 `tts_client.py` 和 `config.py` 顶部用 monkey-patch 修复
- pip 安装时如遇 SSL 错误：`export SSL_CERT_FILE="<certifi_path>/cacert.pem"` 后用默认 PyPI（不用阿里云镜像）
- **edge-tts 需要联网**：语音合成依赖 Microsoft 云端服务，断网时降级为纯文字输出

### Phase 3 踩坑记录
1. **Docker WebRTC 完全不通**：Docker NAT 阻断 UDP P2P 连接，STUN 服务器也无法穿透。解决：放弃 Docker，改用 Windows 原生运行
2. **accelerate 覆盖 PyTorch CUDA 版本**：`pip install -r requirements.txt` 会把 torch 降级为 CPU 版。解决：先装 PyTorch cu128，再装 requirements
3. **Windows 下 `ModuleNotFoundError: No module named 'utils.logger'`**：`utils/` 目录缺 `__init__.py`。解决：创建空文件 `utils/__init__.py`
4. **端口 8010 被占用**：旧进程未退出。解决：`netstat -ano | findstr :8010` 找 PID，`taskkill //PID xxx //F`
5. **conda 镜像源 SSL 报错**：清华镜像在代理环境下失败。解决：`conda config --set proxy_servers.http ''`
6. **LiveTalking 推理线程死锁（2026-08-10）**：
   - **现象**：昨天 demo 正常，今天 WebRTC 连接成功但视频画面不动。FPS 从 25 降到 9.37 后卡死，日志停止更新
   - **已排除**：GPU 显存充足（17GB 空闲）、GPU 频率正常（2595MHz）、虚拟内存充足
   - **expandable_segments 效果**：设置 `PYTORCH_ALLOC_CONF=expandable_segments:True` 后 FPS 恢复到 25，但 100 帧后仍会死锁
   - **怀疑原因**：`feat_queue`/`res_frame_queue`/`_queue` 队列阻塞，或 CUDA 上下文丢失
   - **关键代码位置**：
     - `avatars/base_avatar.py:326-381` — `inference()` 主循环
     - `avatars/base_avatar.py:383-467` — `process_frames()` 消费推理结果
     - `avatars/audio_features/whisper.py:58-76` — `run_step()` 提取音频特征
     - `server/webrtc.py:111-152` — `recv()` 从 `_queue` 取帧
   - **下一步调试**：在队列 get/put 处加时间戳日志、检查队列大小、尝试减小 `batch_size`、加 `torch.cuda.synchronize()` 捕获 CUDA 错误
   - **临时方案**：每次测试前重启 LiveTalking，用 `--max_session 1`，发短文本（<50 字）更稳定

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
data: {"type": "text", "content": "第二句话"}
data: {"type": "mood", "mood": "friendly"}
data: {"type": "done"}
```
（Phase 3 后音频由 LiveTalking 负责，SSE 仅推送文字）

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

## LiveTalking 集成技术细节

### 架构变更
```
旧架构 (Phase 1/2):
用户 → FastAPI → LangGraph → TTS(edge-tts) → SSE(文字+音频) → 前端

新架构 (Phase 3):
用户 → FastAPI → LangGraph → SSE(文字) → 前端
                  ↓
              LiveTalking API → WebRTC 视频流 → 前端
```

### LiveTalking API 端点
- `POST /echo` — 发送文字，触发数字人说话
- `GET /webrtcapi.html` — WebRTC 前端页面
- `POST /whep` — WHEP 协议建立 WebRTC 连接

### 关键配置
- LiveTalking 端口：`8010`
- Lisa 主服务端口：`8000`
- 传输模式：`webrtc`（本地直连，不需要 STUN）
- 数字人模型：`musetalk`
- Avatar ID：`musetalk_avatar1`

### 依赖版本
- PyTorch 2.10.0+cu128（已有，不要装 PyTorch 3.12 浪费磁盘）
- 关键包：resampy、flask、aiortc、aiohttp_cors、opencv-python-headless
- `utils/__init__.py` 必须存在（Windows 必需）

---

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
