# Lisa 的办公室 - AI 可视化聊天机器人

一个带 MuseTalk 数字人虚拟形象的 AI 聊天机器人。Lisa 是你的私人 AI 秘书，拥有实时口型同步的数字人形象，支持流式文本输出、情绪感知、知识库查询和对话记忆。

## 功能一览

- **数字人形象**：基于 MuseTalk 的实时口型同步视频流（WebRTC 低延迟传输）
- **情绪感知**：自动检测用户情绪（6 种），动态调整回复语气
- **知识库**：Qdrant 向量数据库 RAG，可导入自定义知识
- **对话记忆**：Redis 持久化，每个用户独立记忆，支持手动压缩/清除
- **用户系统**：注册/登录 + JWT 认证，多用户隔离
- **命令系统**：斜杠命令管理对话状态

---

## 使用指南

### 启动应用

**方式一：一键启动（推荐）**

双击项目根目录下的 `start_lisa.bat`，会自动打开两个终端窗口：
- **LiveTalking** 窗口：数字人服务（端口 8010）
- **Lisa Server** 窗口：主聊天服务（端口 8000）

等待约 10 秒（模型加载），两个窗口都显示 `running` 即可使用。

**方式二：手动启动**

需要两个终端分别执行（详见 [部署指南](#部署指南)）。

### 打开聊天界面

浏览器访问 **http://127.0.0.1:8000**

- 首次使用需要先**注册账号**（用户名 + 密码，密码至少 6 位）
- 登录后自动连接数字人视频流（右上角出现 Lisa 的视频画面）
- 如果数字人连接失败，会显示"数字人不可用"，文字聊天不受影响

### 聊天交互

在底部输入框输入消息，按 **Enter** 或点击发送按钮：

1. Lisa 会先进行**情绪检测**（状态栏显示"情绪检测 Xs"）
2. 然后**整理对话上下文**（状态栏显示"整理对话 Xs"）
3. 接着**思考回复**（状态栏显示"💭 思考 Xs"）
4. 如果需要查询知识库，会显示"🔍 查询 Xs"
5. 最后文字逐字显示在聊天框，数字人同步说话

**注意**：数字人说话期间，发送按钮会自动锁定（灰色），说完后自动解锁。

### 斜杠命令

在聊天框输入以 `/` 开头的命令直接发送：

| 命令 | 功能 | 说明 |
|------|------|------|
| `/clear` | 清除所有对话记忆 | 重新开始对话，Lisa 会忘记之前聊过的内容 |
| `/compact` | 手动压缩上下文 | 对话太长时手动触发摘要压缩 |
| `/status` | 查看当前状态 | 显示 checkpoint 数量、token 用量、当前情绪 |
| `/mood` | 查看当前情绪 | 显示 Lisa 当前感知到的情绪 |
| `/mood <情绪>` | 手动设置情绪 | 覆盖自动检测，有效值：default / upbeat / angry / depressed / friendly / cheerful |
| `/help` | 显示帮助 | 显示所有可用命令 |

### 关闭应用

双击项目根目录下的 `stop_lisa.bat`，会自动关闭所有相关进程（Lisa 服务、LiveTalking、Redis）。

---

## 部署指南

### 方式一：Docker 部署（推荐，Linux + NVIDIA GPU）

适合 Linux 服务器部署，一键启动所有服务。

**环境要求**：
- Linux（Ubuntu 20.04+ / CentOS 8+）
- NVIDIA GPU + 驱动 ≥ 525
- Docker 20.10+ + Docker Compose v2.0+
- NVIDIA Container Toolkit

**部署步骤**：

```bash
# 1. 克隆代码
mkdir -p ~/lisa && cd ~/lisa
git clone https://github.com/cmm198774/AI-visualization-bot.git .
git clone https://github.com/cmm198774/LiveTalking-Local-Modified.git livetalking

# 2. 下载模型文件（从百度网盘）
# 链接：https://pan.baidu.com/s/1uokpYFLX23ebEv0PbJ46Q（提取码：26a5）
mkdir -p models data/avatars
unzip models_all.zip -d models/
unzip avatar_data.zip -d data/avatars/

# 3. 配置环境变量
cp .env.example .env
nano .env  # 填入 API keys

# 4. 一键启动
docker-compose up -d --build

# 5. 访问
# 浏览器打开 http://<服务器IP>:8000
```

Docker Compose 会自动启动 4 个服务：
- **lisa**：FastAPI 主服务（端口 8000）
- **livetalking**：数字人服务（端口 8010，使用 `network_mode: host` 解决 WebRTC 穿透）
- **redis**：对话记忆持久化（端口 6379）
- **qdrant**：向量数据库（端口 6333）

详细部署文档见 [Docker 部署指南](docs/superpowers/specs/2026-08-18-docker-deployment-design.md)

---

### 方式二：Windows 本地部署

适合开发测试或 Windows 服务器。

**环境要求**：

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | 3.10（conda py310） | LiveTalking 依赖 |
| PyTorch | 2.10.0+cu128 | CUDA 12.8 |
| Redis | 5.0+ | 对话记忆持久化 |
| GPU | NVIDIA（推荐 8GB+ 显存） | 数字人推理 |

### 1. 克隆项目

```bash
# Lisa 主项目
git clone https://github.com/cmm198774/AI-visualization-bot.git
cd AI-visualization-bot

# LiveTalking 数字人项目（单独克隆）
git clone https://github.com/cmm198774/LiveTalking-Local-Modified.git
```

### 2. 安装依赖

```bash
# Lisa 主项目依赖
pip install -r requirements.txt

# LiveTalking 依赖（详见 LiveTalking 仓库 README）
cd LiveTalking-Local-Modified
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入你的 API 密钥（LLM_API_KEY 必填）
```

### 4. 准备数字人素材

LiveTalking 需要预先生成的数字人素材（`data/avatars/lisa_avatar/`），包含：
- `full_imgs/` — 原始帧图片
- `mask/` — 面部 mask
- `coords.pkl` — 面部坐标
- `latents.pt` — VAE 编码特征

使用 LiveTalking 的 `genavatar.py` 从视频生成素材，或从百度网盘下载预制素材（详见 CLAUDE.md）。

### 5. 启动服务

**一键启动**（推荐）：
```bash
# 双击或命令行运行
start_lisa.bat
```

**手动启动**（两个终端）：

终端 1 — LiveTalking 数字人服务：
```bash
cd LiveTalking-Local-Modified
python app.py --model musetalk --avatar_id lisa_avatar \
  --transport webrtc --listenport 8010 --pool_size 2
```

终端 2 — Lisa 主服务：
```bash
cd AI-visualization-bot
conda run -n py310 python server.py
```

### 6. 访问

- 主界面：http://127.0.0.1:8000
- LiveTalking 测试页：http://127.0.0.1:8010/webrtcapi.html

---

## 技术架构

### 技术栈

- **后端**: FastAPI + SSE 流式输出
- **Agent**: LangGraph（全异步，4 节点：detect_mood → compact → model → tools）
- **LLM**: qwen3.6-flash（阿里云 Token Plan）
- **向量数据库**: Qdrant（RAG 知识库）
- **缓存**: Redis（LangGraph checkpoint 持久化）
- **用户数据库**: SQLite
- **认证**: JWT token（python-jose + bcrypt）
- **数字人**: MuseTalk + LiveTalking（WebRTC 实时口型同步）

### Agent 流程

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

### 整体架构

```
用户 → FastAPI → LangGraph → SSE（文字）→ 前端
                  ↓
              LiveTalking API（POST /human）
                  ↓
              WebRTC 视频流 → 前端 <video> 元素
```

### 项目结构

```
├── server.py              # FastAPI 主服务器，SSE 流式输出
├── agent.py               # LangGraph Agent（4 节点）
├── commands.py            # 命令处理模块
├── memory_utils.py        # 消息压缩工具
├── text_utils.py          # TTS 文本清洗（去 emoji/*/#）
├── tools.py               # Qdrant RAG 工具
├── config.py              # 配置加载
├── database.py            # SQLite 用户数据库
├── auth.py                # JWT 认证
├── sys_logger.py          # 日志系统
├── sys_memory.py          # RedisSaver（checkpoint 持久化）
├── start_redis.py         # Redis 服务器管理
├── start_lisa.bat         # 一键启动脚本（Windows）
├── stop_lisa.bat          # 一键关闭脚本（Windows）
├── .env                   # 环境变量配置
│
├── docker/                # Docker 部署文件
│   └── Dockerfile.lisa    # Lisa 服务 Dockerfile
├── docker-compose.yml     # Docker Compose 编排（Linux 部署）
│
├── static/                # 前端文件
│   ├── index.html         # 主聊天页面
│   ├── login.html         # 登录页面
│   ├── css/               # 样式
│   └── js/                # 前端逻辑（含 WebRTC 连接管理）
│
└── docs/                  # 项目文档
    └── superpowers/specs/ # 设计文档
        └── 2026-08-18-docker-deployment-design.md  # Docker 部署设计
```

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MEMORY_TOKEN_LIMIT` | 20000 | 上下文 token 上限 |
| `MAX_CHECKPOINTS` | 5 | 每个用户最大 checkpoint 数 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 60 | JWT token 过期时间（分钟） |
| `LIVETALKING_URL` | `http://localhost:8010` | LiveTalking 服务地址 |
| `TEXT_SEND_DELAY` | 500 | 前端文字缓冲延迟（ms） |
| `SENTENCE_INTERVAL` | 1000 | 数字人说话句间间隔（ms） |

## API 端点

**Lisa 主服务（端口 8000）**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | SSE 流式聊天（返回 text/mood/status/done 事件） |
| POST | `/api/register` | 用户注册 |
| POST | `/api/login` | 用户登录 |
| GET | `/` | 主页 |

**LiveTalking 服务（端口 8010）**：

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/offer` | 建立 WebRTC 连接 |
| POST | `/human` | 发送文字，触发数字人说话 |
| GET | `/is_speaking?sessionid=xxx` | 查询数字人是否在说话 |
| GET | `/webrtcapi.html` | WebRTC 独立测试页 |

## License

MIT
