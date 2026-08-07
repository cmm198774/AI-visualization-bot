# Phase 3 设计文档：LiveTalking 集成

**版本**: 1.0  
**日期**: 2026-08-07  
**状态**: 待审核

---

## 1. 背景与目标

### 1.1 背景

项目当前已完成 Phase 1（核心聊天机器人）和 Phase 2（TTS 语音合成）。Phase 3 的目标是为 AI 助手 Lisa 添加可视化虚拟形象。

最初 Phase 3 方案是 Live2D 卡通风格（纯前端 JS，零延迟），但在探索过程中发现 LiveTalking 这个开源项目，它提供写实真人风格的数字人，支持实时口型同步和 AI 驱动的表情。经过评估，决定从 Live2D 方案转向 LiveTalking 方案。

### 1.2 目标

1. **为 Lisa 创建写实风格的虚拟形象**（30 岁女性，成熟漂亮）
2. **实现实时数字人驱动**（文字输入 → 语音合成 → 口型同步 → 视频输出）
3. **验证延迟和效果**（先 Demo，再集成）
4. **最终集成到现有聊天系统**（前端同时连接 server.py 和 LiveTalking）

### 1.3 方案对比

| 维度 | Live2D 卡通 | LiveTalking 写实 |
|------|------------|------------------|
| 形象风格 | 二次元卡通 | 写实真人 |
| 技术栈 | 纯前端 JS | Docker + GPU |
| GPU 需求 | 无 | NVIDIA 8GB+ VRAM |
| 延迟 | 0ms（前端渲染） | < 3s（全链路） |
| 部署复杂度 | 低 | 中 |
| 用户选择 | ❌ 放弃 | ✅ 采用 |

**决策**：选择 LiveTalking 方案，因为用户更倾向于写实真人风格的数字人形象。

---

## 2. 系统架构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────┐
│                    前端 (index.html)              │
│                                                   │
│  ┌───────────────┐    ┌───────────────────────┐  │
│  │  SSE 连接      │    │  WebSocket/WebRTC     │  │
│  │  → server.py   │    │  → LiveTalking        │  │
│  │  (文字+情绪)    │    │  (发送文字, 接收视频流) │  │
│  └───────────────┘    └───────────────────────┘  │
│                                                   │
│  ┌─────────────────────────────────────────────┐ │
│  │  视频播放区域（WebRTC 视频流）                │ │
│  │  + 聊天气泡（SSE 文字）                       │ │
│  └─────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────┘
          │ SSE                        │ WebSocket/WebRTC
          ▼                            ▼
┌──────────────────┐      ┌──────────────────────────┐
│   server.py       │      │  LiveTalking (Docker)     │
│   (FastAPI)       │      │  ┌──────────────────────┐ │
│                   │      │  │ TTS（语音合成）        │ │
│  职责：            │      │  │ 口型渲染（MuseTalk）  │ │
│  - LLM 推理       │      │  │ 视频流输出            │ │
│  - 情绪检测       │      │  └──────────────────────┘ │
│  - RAG 工具       │      │                           │
│  - 上下文管理     │      │  端口: 8010 (HTTP)         │
│                   │      │  WebRTC: 动态端口          │
│  职责外：          │      └──────────────────────────┘
│  ✗ TTS（已移除）  │
│  ✗ 音频处理       │
└──────────────────┘
```

### 2.2 数据流

```
用户输入 → server.py(LLM) → "文字 + 情绪"
                              │
                    ┌─────────┴──────────┐
                    ▼ SSE                 ▼ WebSocket/WebRTC
              前端显示文字        LiveTalking TTS + 口型渲染
              前端显示情绪动画     → WebRTC 视频流输出到前端
```

### 2.3 职责划分

**server.py（大脑）**：
- 接收用户消息
- LangGraph Agent 推理（detect_mood → compact → model → tools）
- 生成回复文字 + 情绪标签
- 通过 SSE 流式推送文字和情绪

**LiveTalking（嘴巴 + 脸）**：
- 接收文字
- 调用 TTS 合成语音
- 用 MuseTalk 做口型同步渲染
- 通过 WebRTC 输出数字人视频流 + 音频流

**前端（协调者）**：
- 同时维护两个连接（SSE + WebRTC）
- 显示文字聊天气泡
- 播放数字人视频流
- 可选：根据情绪标签显示动画效果

---

## 3. 技术细节

### 3.1 LiveTalking 部署

**部署方式**：Docker（推荐）

**硬件要求**：
- GPU：NVIDIA 16GB+ VRAM（已确认用户满足）
- RAM：16GB+
- 磁盘：100GB（模型文件较大）
- CUDA：12.0+

**Docker 镜像**：
```bash
# 官方镜像（含 CUDA 12.4 + Python 3.12 + 所有依赖）
docker pull <livetalking镜像>
```

**启动命令**：
```bash
docker run --gpus all \
  -p 8010:8010 \
  -v ./livetalking_data:/root/livetalking/data \
  livetalking-image \
  python app.py --transport webrtc --model musetalk --listenport 8010
```

**模型选择**：
- **MuseTalk**（推荐）：显存 ~5GB，质量高
- 备选：Wav2Lip（显存 ~2GB，质量较低）

**端口**：
- 8010：HTTP API + WebSocket
- WebRTC：动态端口（P2P 连接）

### 3.2 LiveTalking API 接口

**1. WebSocket `/human`**：
- 用途：发送文字命令，触发 TTS + 口型渲染
- 示例：
  ```javascript
  const ws = new WebSocket('ws://localhost:8010/human');
  ws.send(JSON.stringify({
    type: 'text',
    text: '你好，我是 Lisa！'
  }));
  ```

**2. WebRTC `/offer`**：
- 用途：建立视频+音频流连接
- 流程：
  1. 前端创建 RTCPeerConnection
  2. 发送 SDP offer 到 `/offer`
  3. 接收 SDP answer
  4. 播放视频流（数字人画面）

**3. 前端页面**：
- `http://localhost:8010/webrtcapi.html`：自带测试页面
- 可以直接在浏览器打开，手动输入文字测试

### 3.3 server.py 改动

**移除的内容**：
- `tts_client.py` 的导入和调用
- `sentence_splitter.py` 的使用（不再需要分句）
- `EDGE_TTS_VOICE`、`TTS_CHUNK_SIZE`、`TTS_PREBUFFER` 等配置
- SSE 中 `{"type": "audio", "data": "<base64 MP3>"}` 事件
- SSE 中 `{"type": "audio_done"}` 事件

**保留的内容**：
- SSE 中 `{"type": "text", "content": "..."}` 事件
- SSE 中 `{"type": "mood", "mood": "..."}` 事件
- SSE 中 `{"type": "status", "status": "..."}` 事件
- SSE 中 `{"type": "done"}` 事件
- 所有 LangGraph Agent 逻辑
- 用户认证、命令系统

**改动幅度**：主要是删除代码，server.py 会变得更简洁。

### 3.4 前端改动

**新增功能**：
1. WebRTC 连接管理
2. 视频播放区域
3. 同时维护 SSE 和 WebRTC 连接

**布局**：
```
┌─────────────────────────────────────┐
│                                     │
│    ┌───────────────────────┐        │
│    │                       │        │
│    │   视频播放区域         │        │
│    │   （WebRTC 视频流）    │        │
│    │                       │        │
│    └───────────────────────┘        │
│                                     │
│    ┌───────────────────────────┐    │
│    │ 聊天气泡区域               │    │
│    │ （SSE 文字 + 情绪动画）    │    │
│    └───────────────────────────┘    │
│                                     │
│    ┌───────────────────────────┐    │
│    │ 输入框                     │    │
│    └───────────────────────────┘    │
└─────────────────────────────────────┘
```

### 3.5 Lisa 形象素材

**要求**：
- 30 岁女性，成熟漂亮
- 正面照，嘴巴清晰可见
- 纯色背景（白色或浅灰）
- 分辨率：至少 512x512
- 格式：JPG 或 PNG

**获取方式**：用户用 AI 生图工具（Midjourney / Stable Diffusion / 通义万相）生成。

**使用流程**：
1. 先用 LiveTalking 默认示例形象跑通 Demo
2. 用户生成 Lisa 形象照片
3. 将照片放入 LiveTalking 的素材目录
4. 重新训练/配置数字人（参考 LiveTalking 文档）

---

## 4. 实施计划

### 4.1 阶段划分

**Phase 3a：Demo 验证**（当前阶段）
1. Docker 部署 LiveTalking（MuseTalk 模型）
2. 用默认示例形象测试
3. 打开 `webrtcapi.html`，手动输入文字
4. 观察数字人说话效果、延迟、口型同步
5. 如果效果可接受，进入 Phase 3b

**Phase 3b：server.py 改造**
1. 移除 TTS 相关代码
2. 简化 SSE 输出（只保留文字 + 情绪）
3. 测试现有聊天功能是否正常（无音频）

**Phase 3c：前端集成**
1. 前端新增 WebRTC 连接
2. 视频播放区域
3. 同时连接 server.py（SSE）和 LiveTalking（WebRTC）
4. 文字和视频的时间同步优化

**Phase 3d：Lisa 形象定制**
1. 用户生成 Lisa 形象照片
2. 配置到 LiveTalking
3. 测试效果

### 4.2 当前任务（Phase 3a）

1. **检查 Docker 环境**：
   - 确认 Docker Desktop 已安装
   - 确认 NVIDIA Container Toolkit 可用（`docker run --gpus all nvidia-smi`）

2. **部署 LiveTalking**：
   - 拉取官方镜像
   - 启动容器（MuseTalk 模型）
   - 映射端口 8010

3. **测试 Demo**：
   - 打开 `http://localhost:8010/webrtcapi.html`
   - 输入测试文字（"你好，我是 Lisa，很高兴认识你！"）
   - 记录延迟数据：
     - 从点击"发送"到数字人开始说话的时间
     - 口型同步效果
     - 视频流畅度（帧率）

4. **评估结果**：
   - 如果延迟 < 3 秒，可接受
   - 如果口型同步效果好，可接受
   - 如果视频流畅（> 15 FPS），可接受

### 4.3 风险与缓解

**风险 1：Docker GPU 支持问题**
- 可能原因：NVIDIA Container Toolkit 未安装或配置错误
- 缓解：先运行 `docker run --gpus all nvidia-smi` 验证

**风险 2：WebRTC 连接失败**
- 可能原因：P2P 连接被防火墙或 NAT 阻断
- 缓解：配置 TURN 服务器，或使用 WebSocket 降级方案

**风险 3：MuseTalk 显存不足**
- 可能原因：16GB 显存不够（虽然理论上足够）
- 缓解：切换到 Wav2Lip（只需 2GB）

**风险 4：延迟过高**
- 可能原因：全链路（TTS + 口型渲染）延迟超过 3 秒
- 缓解：
  - 优化 TTS 模型（用更轻量的 TTS）
  - 减少渲染分辨率
  - 如果延迟无法接受，考虑回退到 Live2D 方案

---

## 5. 验收标准

### 5.1 Demo 阶段验收

- [ ] LiveTalking Docker 容器正常启动
- [ ] 可以通过 `webrtcapi.html` 访问
- [ ] 输入文字后，数字人说话
- [ ] 首包延迟 < 5 秒（可接受范围）
- [ ] 口型同步效果可接受（主观评价）
- [ ] 视频流畅（> 15 FPS）

### 5.2 集成阶段验收

- [ ] server.py 移除 TTS 代码后，聊天功能正常
- [ ] 前端同时连接 server.py 和 LiveTalking
- [ ] 文字和视频基本同步（延迟 < 1 秒差异）
- [ ] Lisa 形象配置完成

---

## 6. 参考资源

- **LiveTalking GitHub**: https://github.com/lipku/livetalking
- **LiveTalking 文档**: https://livetalking-doc.readthedocs.io/zh-cn/latest/
- **API 接口文档**: https://livetalking-doc.readthedocs.io/zh-cn/latest/api.html
- **Docker 部署**: https://livetalking-doc.readthedocs.io/zh-cn/latest/docker.html
- **Windows 部署教程**: https://blog.csdn.net/JustZzer/article/details/144294919

---

## 7. 附录

### 7.1 LiveTalking 支持的模型

| 模型 | 显存需求 | 质量 | 速度 |
|------|---------|------|------|
| Wav2Lip | ~2GB | 中 | 快 |
| MuseTalk | ~5GB | 高 | 中 |
| ERNeRF | ~8GB | 高 | 慢 |

### 7.2 端口映射

| 服务 | 端口 | 用途 |
|------|------|------|
| server.py | 8000 | FastAPI 主服务（SSE） |
| LiveTalking | 8010 | HTTP API + WebSocket |
| LiveTalking WebRTC | 动态 | 视频流（P2P） |

### 7.3 环境变量

**server.py**（保留）：
- `MEMORY_TOKEN_LIMIT=20000`
- `MAX_CHECKPOINTS=5`
- LLM 超时: 60 秒
- 工具超时: 20 秒

**server.py**（移除）：
- `EDGE_TTS_VOICE`
- `TTS_CHUNK_SIZE`
- `TTS_PREBUFFER`

**LiveTalking**：
- `--transport webrtc`
- `--model musetalk`
- `--listenport 8010`

---

**下一步**：审核此设计文档，确认后转入实施计划阶段。
