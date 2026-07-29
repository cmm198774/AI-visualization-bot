# Lisa 的办公室 - AI 可视化聊天机器人

一个带虚拟形象（Live2D）的 AI 聊天机器人，支持流式文本输出、情绪检测、用户认证、斜杠命令系统。

## 技术栈

- **后端**: FastAPI + SSE 流式输出
- **Agent**: LangGraph（全异步）
- **LLM**: qwen3.6-flash（阿里云 Token Plan）
- **向量数据库**: Qdrant（RAG 知识库）
- **缓存**: Redis（LangGraph checkpoint 持久化）
- **用户数据库**: SQLite
- **认证**: JWT token（python-jose + bcrypt）

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
│   └── js/                # 前端逻辑
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
# 复制模板
cp .env.example .env

# 编辑 .env，填入你的 API 密钥
# 必填项：
#   LLM_API_KEY        - 阿里云 Token Plan API Key
#   DASHSCOPE_API_KEY  - DashScope API Key（Embedding 模型）
#   SECRET_KEY         - JWT 签名密钥（自定义随机字符串）
```

### 4. 准备 Redis

项目内置了 Windows 版 Redis，启动时会自动运行。如需手动启动：

```bash
redis-server/redis-server.exe redis_cache/redis.conf
```

### 5. 启动服务

```bash
python server.py
```

服务启动后访问 `http://127.0.0.1:8000`

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

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | SSE 流式聊天 |
| POST | `/api/register` | 用户注册 |
| POST | `/api/login` | 用户登录 |
| GET | `/` | 主页 |

## 重要配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MEMORY_TOKEN_LIMIT` | 20000 | 上下文 token 上限 |
| `MAX_CHECKPOINTS` | 5 | 每个用户最大 checkpoint 数 |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 60 | JWT token 过期时间（分钟） |

## License

MIT
