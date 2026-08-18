# Lisa Docker 化部署设计文档

**日期**: 2026-08-18
**状态**: 设计中
**目标平台**: Linux + NVIDIA GPU

---

## 1. 背景与目标

### 1.1 为什么 Docker 化

Lisa 办公室当前在 Windows 原生运行，部署到新机器需要手动安装：
- Python 3.10 + conda (~400MB)
- PyTorch 2.10+cu128 (~2.5GB)
- LiveTalking 依赖包 (~500MB)
- Lisa 依赖包 (~200MB)
- 模型文件 (4.6GB)
- Avatar 素材 (730MB)

总计约 9.5GB 需要下载安装，每步都可能出错（conda 镜像源 SSL、PyTorch 版本冲突等）。

### 1.2 目标

- 部署到 Linux 服务器（NVIDIA GPU，局域网内）
- 一键部署：`docker-compose up`
- WebRTC 视频流正常工作（之前 Docker bridge 网络下失败过）

### 1.3 为什么之前 Docker 失败，现在能成功

**Phase 3a 失败原因**：Docker bridge 网络做了 NAT，容器内部 IP（172.17.0.x）对外不可达。WebRTC 的 SDP 里写的 ICE candidate 是容器内部 IP，浏览器尝试连接时找不到路由。

**解决方案**：LiveTalking 容器使用 `network_mode: host`，容器直接使用宿主机真实 IP，SDP 里写的就是宿主机局域网 IP，浏览器可以直接连上。

**前提条件**：目标机器是 Linux（原生支持 host 网络模式）+ 局域网部署（浏览器和服务器 IP 互通）。

---

## 2. 容器架构

### 2.1 服务组成

```
┌──────────────── Linux 宿主机 ────────────────────────────────┐
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │           compose 内部网络 (lisa-net, bridge)            │ │
│  │                                                          │ │
│  │  ┌──────────┐    ┌──────────┐    ┌──────────┐          │ │
│  │  │   lisa   │───►│  redis   │    │  qdrant  │          │ │
│  │  │  :8000   │    │  :6379   │    │  :6333   │          │ │
│  │  └────┬─────┘    └──────────┘    └──────────┘          │ │
│  │       │                                                  │ │
│  └───────│──────────────────────────────────────────────────┘ │
│          │                                                    │
│          │  host.docker.internal                              │
│          ▼                                                    │
│  ┌──────────────────┐   (共享宿主机网络)                      │
│  │   livetalking    │                                         │
│  │   network_mode:  │                                         │
│  │     host :8010   │                                         │
│  │   gpus: all      │                                         │
│  └──────────────────┘                                         │
│                                                               │
│  ┌─────────────────────── 宿主机磁盘 ──────────────────────┐ │
│  │  ./models/    → livetalking:/app/models (只读)          │ │
│  │  ./data/      → livetalking:/app/data (读写)            │ │
│  │  ./users.db   → lisa:/app/users.db                      │ │
│  │  ./qdrant_data/ → qdrant:/qdrant/storage                │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

### 2.2 四个服务

| 服务 | 基础镜像 | 网络模式 | GPU | 端口 |
|------|---------|---------|-----|------|
| **lisa** | python:3.10-slim | bridge (lisa-net) | 无 | 8000 |
| **livetalking** | nvcr.io/nvidia/pytorch:24.01-py3 | host | 全部 | 8010 |
| **redis** | redis:7-alpine | bridge (lisa-net) | 无 | 6379 |
| **qdrant** | qdrant/qdrant:latest | bridge (lisa-net) | 无 | 6333 |

### 2.3 为什么这样分

- **LiveTalking 独立 + host 网络**：WebRTC 需要宿主机真实 IP，host 模式是唯一可靠的方案
- **Lisa 用 bridge 网络**：纯 CPU 服务，不需要 GPU，bridge 网络通过 DNS 互相访问
- **Redis / Qdrant 用官方镜像**：比自己装稳定，镜像小（Redis ~30MB, Qdrant ~100MB）

### 2.4 容器间通信

| 路径 | 方式 | 地址 |
|------|------|------|
| 浏览器 → lisa | 端口映射 | `http://<宿主机IP>:8000` |
| 浏览器 → livetalking (WebRTC) | host 网络直通 | `http://<宿主机IP>:8010` |
| lisa → redis | compose DNS | `redis:6379` |
| lisa → qdrant | compose DNS | `qdrant:6333` |
| lisa → livetalking | extra_hosts | `host.docker.internal:8010` |

---

## 3. Dockerfile 设计

### 3.1 LiveTalking Dockerfile

```dockerfile
# LiveTalking/Dockerfile
FROM nvcr.io/nvidia/pytorch:24.01-py3

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（利用 Docker 缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码（模型通过 volume 挂载，不打进镜像）
COPY . .

# 创建必要的目录
RUN mkdir -p data/avatars data/record

EXPOSE 8010

CMD ["python", "app.py", \
     "--model", "musetalk", \
     "--avatar_id", "lisa_avatar", \
     "--transport", "webrtc", \
     "--listenport", "8010", \
     "--pool_size", "2"]
```

**关键点**：
- 基础镜像自带 PyTorch + CUDA，不需要手动安装
- 模型文件（4.6GB）通过 volume 挂载到 `/app/models`
- Avatar 素材通过 volume 挂载到 `/app/data/avatars/lisa_avatar`
- 镜像体积约 8-10GB（主要是 PyTorch + 依赖包）

### 3.2 Lisa Dockerfile

```dockerfile
# Dockerfile
FROM python:3.10-slim

WORKDIR /app

# 系统依赖
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

EXPOSE 8000

CMD ["python", "server.py"]
```

**关键点**：
- 纯 CPU 服务，基础镜像 python:3.10-slim 体积小
- 不需要 GPU 相关依赖
- 镜像约 500MB

---

## 4. docker-compose.yml

```yaml
version: '3.8'

services:
  # ═══════════════════════════════════════════════════════════
  # Lisa 主服务（FastAPI + LangGraph）
  # ═══════════════════════════════════════════════════════════
  lisa:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: lisa-server
    ports:
      - "8000:8000"
    env_file: .env
    environment:
      # 这几个用 compose 的值覆盖 .env 中的 localhost
      - REDIS_HOST=redis
      - QDRANT_HOST=qdrant
      - QDRANT_PORT=6333
      - LIVETALKING_URL=http://host.docker.internal:8010
    volumes:
      - ./users.db:/app/users.db
      - ./local_qdrant:/app/local_qdrant
    depends_on:
      - redis
      - qdrant
    extra_hosts:
      - "host.docker.internal:host-gateway"
    networks:
      - lisa-net
    restart: unless-stopped

  # ═══════════════════════════════════════════════════════════
  # LiveTalking 数字人服务（GPU + WebRTC）
  # ═══════════════════════════════════════════════════════════
  livetalking:
    build:
      context: ./livetalking
      dockerfile: Dockerfile
    container_name: livetalking-server
    network_mode: host
    gpus: all
    env_file: ./livetalking/.env
    volumes:
      - ./models:/app/models
      - ./data:/app/data
    environment:
      - PYTHONPATH=/app
    restart: unless-stopped

  # ═══════════════════════════════════════════════════════════
  # Redis（LangGraph checkpoint 持久化）
  # ═══════════════════════════════════════════════════════════
  redis:
    image: redis:7-alpine
    container_name: lisa-redis
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    networks:
      - lisa-net
    restart: unless-stopped

  # ═══════════════════════════════════════════════════════════
  # Qdrant（向量数据库，RAG 知识库）
  # ═══════════════════════════════════════════════════════════
  qdrant:
    image: qdrant/qdrant:latest
    container_name: lisa-qdrant
    ports:
      - "6333:6333"
    volumes:
      - qdrant-data:/qdrant/storage
    networks:
      - lisa-net
    restart: unless-stopped

networks:
  lisa-net:
    driver: bridge

volumes:
  redis-data:
  qdrant-data:
```

---

## 5. 环境变量管理

### 5.1 策略

- **.env 文件放在宿主机上**，不打包进镜像
- 通过 `env_file` 指令注入，修改配置不用重建镜像
- Docker 特有的值（Redis/Qdrant/LiveTalking 地址）在 `environment` 中覆盖

### 5.2 Lisa .env 文件

```bash
# LLM 配置
LLM_API_KEY=sk-your-key-here
LLM_MODEL_NAME=qwen3.6-flash
LLM_BASE_URL=https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1
LLM_TEMPERATURE=0.2

# DashScope（Embedding）
DASHSCOPE_API_KEY=sk-your-key-here
EMBEDDING_MODEL=text-embedding-v3

# Qdrant
QDRANT_COLLECTION=lisa_knowledge

# Redis（本地开发用 localhost，Docker 内会被 compose 覆盖为 redis）
REDIS_HOST=localhost
REDIS_PORT=6379

# 服务配置
SERVER_PORT=8000
MEMORY_TOKEN_LIMIT=20000
MAX_CHECKPOINTS=5
SECRET_KEY=your-secret-key-change-in-production
ACCESS_TOKEN_EXPIRE_MINUTES=60

# LiveTalking（本地开发用 localhost，Docker 内会被 compose 覆盖）
LIVETALKING_URL=http://localhost:8010
```

### 5.3 覆盖机制

当 `env_file` 和 `environment` 同时存在时，`environment` 的值会覆盖 `env_file` 中的同名变量。所以：

- .env 里写 `REDIS_HOST=localhost`（本地开发用）
- compose 里写 `REDIS_HOST=redis`（Docker 内用）
- 最终容器内是 `redis`

**Lisa 和 LiveTalking 的代码都不需要改**。

---

## 6. 模型和素材管理

### 6.1 为什么通过 volume 挂载

- 模型文件 4.6GB + Avatar 素材 730MB，不打进镜像（否则镜像超 15GB）
- 更新素材不需要重建镜像
- 多个部署点可以共享同一份模型文件（通过 NAS）

### 6.2 目录结构

```
部署目录/
├── docker-compose.yml
├── .env                            # 配置文件
├── Dockerfile                      # Lisa Dockerfile
├── server.py / agent.py / ...      # Lisa 代码
├── users.db                        # 用户数据库
│
├── livetalking/                    # LiveTalking 代码
│   ├── Dockerfile
│   ├── app.py
│   ├── requirements.txt
│   └── ...
│
├── models/                         # LiveTalking 模型（volume 挂载）
│   ├── musetalkV15/   (3.2GB)
│   ├── sd-vae/        (639MB)
│   ├── whisper/       (217MB)
│   ├── dwpose/        (474MB)
│   └── face-parse-bisent/ (96MB)
│
└── data/                           # Avatar 素材（volume 挂载）
    └── avatars/
        └── lisa_avatar/  (730MB)
            ├── full_imgs/
            ├── mask/
            ├── coords.pkl
            ├── latents.pt
            └── mask_coords.pkl
```

### 6.3 获取模型文件

**百度网盘**：
- 链接：https://pan.baidu.com/s/1uokpYFLX23ebEv0PbJ46Q
- 提取码：26a5
- `models_all.zip` → 解压到 `models/` 目录
- `avatar_data.zip` → 解压到 `data/avatars/lisa_avatar/`（如果是 `musetalk_avatar1/` 需要重命名）

---

## 7. 部署流程

### 7.1 环境要求

| 项目 | 要求 |
|------|------|
| 操作系统 | Ubuntu 20.04+ / CentOS 8+ / Debian 11+ |
| NVIDIA 驱动 | >= 525（需支持 CUDA 12.x） |
| Docker | 20.10+ |
| Docker Compose | v2.0+ |
| NVIDIA Container Toolkit | 最新稳定版 |
| 磁盘空间 | >= 30GB |

### 7.2 步骤

```bash
# 1. 安装 Docker
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# 2. 安装 NVIDIA Container Toolkit
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
  sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
curl -s -L https://nvidia.github.io/libnvidia-container/$distribution/libnvidia-container.list | \
  sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
  sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo nvidia-ctk runtime configure --runtime=docker
sudo systemctl restart docker

# 3. 验证 GPU
docker run --rm --gpus all nvidia/cuda:12.0-base-ubuntu22.04 nvidia-smi

# 4. 下载代码
mkdir -p ~/lisa-deploy && cd ~/lisa-deploy
git clone git@github.com:cmm198774/AI-visualization-bot.git lisa
git clone git@github.com:cmm198774/LiveTalking-Local-Modified.git livetalking

# 5. 下载模型（从百度网盘，通过 Windows scp 传过来）
mkdir -p models data/avatars
# ... 传输并解压 models_all.zip 和 avatar_data.zip

# 6. 配置 .env
cd lisa
nano .env  # 填入 API keys

# 7. 放置 Dockerfile 和 docker-compose.yml
cp ~/path/to/docker-compose.yml ~/lisa-deploy/
cp ~/path/to/lisa-Dockerfile ~/lisa-deploy/lisa/Dockerfile
cp ~/path/to/livetalking-Dockerfile ~/lisa-deploy/livetalking/Dockerfile

# 8. 启动
cd ~/lisa-deploy
docker-compose up -d --build

# 9. 验证
docker-compose ps
docker exec livetalking-server nvidia-smi
# 浏览器打开 http://<服务器IP>:8000
```

---

## 8. 故障排查

### 8.1 LiveTalking 启动失败

```bash
docker-compose logs livetalking
# 检查 GPU 是否可用
docker exec livetalking-server nvidia-smi
```

### 8.2 WebRTC 连接失败

```bash
# 检查 LiveTalking 是否绑定到 0.0.0.0
docker exec livetalking-server netstat -tlnp | grep 8010
# 应该看到 0.0.0.0:8010

# 检查防火墙
sudo ufw allow 8010/tcp
sudo ufw allow 8010/udp
```

### 8.3 Lisa 无法连接 LiveTalking

```bash
docker exec lisa-server curl http://host.docker.internal:8010/human?text=test&sessionid=1
```

---

## 9. 后续工作

### 9.1 需要创建的文件

| 文件 | 位置 | 说明 |
|------|------|------|
| `Dockerfile` | Lisa 项目根目录 | Lisa 的 Dockerfile |
| `livetalking/Dockerfile` | LiveTalking 项目根目录 | LiveTalking 的 Dockerfile |
| `docker-compose.yml` | Lisa 项目根目录（或独立 deploy 目录） | Compose 编排 |

### 9.2 不需要改的代码

- Lisa 的 `config.py` 已有 Docker 兼容逻辑（`/.dockerenv` 检测）
- Lisa 的 `tools.py` 已有 Docker 兼容逻辑
- 环境变量通过 `env_file` + `environment` 覆盖，代码零改动

### 9.3 部署体验

```bash
# 目标 Linux 机器上：
git clone <仓库>
# 手动放模型文件和 .env
docker-compose up -d
# 完成！浏览器打开 http://<服务器IP>:8000
```
