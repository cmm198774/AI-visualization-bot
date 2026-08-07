# Phase 3: LiveTalking 数字人集成 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LiveTalking 写实数字人集成到 Lisa 聊天系统，替代 edge-tts 纯文字方案，实现"文字 + 视频数字人"双输出。

**Architecture:** server.py 只负责 LLM 推理 + 情绪检测，输出纯文字 + 情绪标签（SSE）。LiveTalking 作为独立 Docker 服务，接收文字，内部完成 TTS + 口型渲染 + 视频流输出（WebRTC）。前端同时连接两个服务：SSE 拿文字，WebRTC 播视频。

**Tech Stack:**
- server.py: FastAPI + SSE（Python 3.10, conda py310）
- LiveTalking: Docker + CUDA 12.8 + PyTorch 2.9.1 + MuseTalk
- 前端: 原生 JS + WebRTC API + SSE
- 硬件: RTX 5090D 32GB VRAM, Windows 11

**Design Spec:** `docs/superpowers/specs/2026-08-07-phase3-livetalking-design.md`

---

## File Structure

```
Phase 3a (Demo 验证 — 无代码改动):
  Docker 容器内运行 LiveTalking，前端用 LiveTalking 自带页面测试

Phase 3b (server.py 改造):
  Modify: server.py           — 移除 TTS 相关代码，简化 SSE 输出
  Modify: config.py           — 移除 TTS 相关配置
  Modify: requirements.txt    — 移除 edge-tts 依赖
  Delete: tts_client.py       — 不再需要
  (保留: sentence_splitter.py  — agent.py/commands.py 可能间接引用，暂不删)

Phase 3c (前端集成):
  Modify: static/index.html   — 替换 placeholder 为视频容器，移除音频相关 UI
  Modify: static/js/app.js    — 移除音频播放逻辑，新增 WebRTC 连接 + 视频播放
  Modify: static/css/style.css — 视频区域样式，移除 audio-wave 样式

Phase 3d (Lisa 形象定制):
  用户操作: AI 生图 → 放入 LiveTalking 素材目录
```

---

## Phase 3a: Demo 验证

> **目标**: 验证 LiveTalking 在你的 RTX 5090D 上能正常运行，测试数字人说话效果和延迟。

### Task 1: 检查 Docker 环境

**Files:** 无（环境检查）

- [ ] **Step 1: 检查 Docker Desktop 是否运行**

```bash
docker --version
```

Expected: 显示 Docker 版本号（如 `Docker version 27.x.x`）

如果 Docker 未安装：
1. 下载 Docker Desktop：https://www.docker.com/products/docker-desktop/
2. 安装后启动 Docker Desktop
3. 确保 WSL2 后端已启用

- [ ] **Step 2: 检查 GPU 是否对 Docker 可见**

```bash
docker run --rm --gpus all nvidia-smi
```

Expected: 显示 RTX 5090D 信息，包含 CUDA 版本和显存 32GB

如果失败：
1. 确认 NVIDIA 驱动已安装且版本 >= 550（支持 CUDA 12.8）
2. Docker Desktop → Settings → Resources → 确认 "Use the WSL 2 based engine" 已勾选
3. 重启 Docker Desktop

- [ ] **Step 3: 检查磁盘空间**

```bash
df -h
```

Expected: 至少有 50GB 可用空间（LiveTalking 镜像 + 模型文件约 30-40GB）

- [ ] **Step 4: 记录环境信息**

```bash
docker run --rm --gpus all nvidia-smi | head -5
```

记录输出中的：
- Driver Version（驱动版本）
- CUDA Version（CUDA 版本）
- GPU Name（GPU 名称，应显示 RTX 5090D）

---

### Task 2: 克隆 LiveTalking 仓库

**Files:**
- Create: `livetalking/`（项目根目录外的独立目录）

- [ ] **Step 1: 克隆仓库到项目同级目录**

```bash
cd "g:\JupyterProject"
git clone https://github.com/lipku/LiveTalking.git
cd LiveTalking
```

Expected: 克隆成功，显示文件列表

- [ ] **Step 2: 检查仓库内容**

```bash
ls -la
```

Expected: 看到 `app.py`、`Dockerfile`、`requirements.txt` 等文件

- [ ] **Step 3: 查看 Dockerfile 确认 CUDA 版本**

```bash
head -5 Dockerfile
```

Expected: 看到基于 CUDA 12.8 或更高的基础镜像（如 `nvidia/cuda:12.8.x-...`）

如果 Dockerfile 中 CUDA 版本低于 12.8，需要手动修改：
```dockerfile
# 将基础镜像改为 CUDA 12.8
FROM nvidia/cuda:12.8.0-cudnn-devel-ubuntu22.04
```

---

### Task 3: 构建 Docker 镜像

**Files:**
- Modify: `livetalking/Dockerfile`（如需调整 CUDA 版本）

- [ ] **Step 1: 构建镜像**

```bash
cd "g:\JupyterProject\LiveTalking"
docker build -t livetalking:cuda12.8 .
```

Expected: 构建成功，显示 `Successfully tagged livetalking:cuda12.8`

构建过程可能需要 10-30 分钟，取决于网速（需要下载模型文件和依赖）。

如果构建失败：
1. 检查 Dockerfile 中的 CUDA 版本是否与你的驱动兼容
2. 检查网络连接（某些依赖需要从国外下载）
3. 查看构建日志，定位具体失败的步骤

- [ ] **Step 2: 验证镜像**

```bash
docker images | grep livetalking
```

Expected: 显示 `livetalking:cuda12.8` 镜像，大小约 10-20GB

---

### Task 4: 启动 LiveTalking 容器

**Files:** 无

- [ ] **Step 1: 启动容器**

```bash
cd "g:\JupyterProject\LiveTalking"
docker run --gpus all \
  -p 8010:8010 \
  -v ./data:/root/livetalking/data \
  --name livetalking-server \
  livetalking:cuda12.8 \
  python app.py --transport webrtc --model musetalk --listenport 8010
```

Expected: 容器启动，日志显示服务监听在 8010 端口

注意：
- 首次启动会下载模型文件，可能需要几分钟
- 如果端口 8010 被占用，改为其他端口（如 8011）

- [ ] **Step 2: 检查容器状态**

打开另一个终端：

```bash
docker ps | grep livetalking
```

Expected: 显示容器正在运行，端口映射 `0.0.0.0:8010->8010/tcp`

- [ ] **Step 3: 查看容器日志**

```bash
docker logs livetalking-server
```

Expected: 看到 `Running on ...` 或类似的服务启动成功信息

如果容器退出：
```bash
docker logs livetalking-server
```

查看错误日志，常见问题：
- GPU 显存不足 → 切换到 wav2lip 模型
- CUDA 版本不兼容 → 重新构建镜像，调整 CUDA 版本
- 端口冲突 → 更换端口

---

### Task 5: 测试 Demo — 数字人说话效果

**Files:** 无（使用 LiveTalking 自带前端页面）

- [ ] **Step 1: 打开 LiveTalking 前端页面**

浏览器访问：`http://localhost:8010/webrtcapi.html`

Expected: 页面加载成功，看到一个数字人形象（默认示例素材）

- [ ] **Step 2: 建立 WebRTC 连接**

在页面上点击"Start"或"Connect"按钮

Expected: 视频流开始播放，数字人画面显示

如果连接失败：
1. 检查浏览器控制台（F12）是否有 WebRTC 错误
2. 尝试使用 Chrome 浏览器
3. 检查防火墙是否允许 8010 端口

- [ ] **Step 3: 测试文字转语音 + 口型同步**

在页面的文字输入框中输入：
```
你好，我是 Lisa，很高兴认识你！
```

点击"Send"或"Submit"按钮

Expected:
- 数字人开始说话
- 嘴巴动作与语音同步
- 声音清晰可辨

- [ ] **Step 4: 记录延迟数据**

使用秒表或浏览器开发者工具（F12 → Network → WS）记录：
- **首包延迟**: 从点击"Send"到数字人开始说话的时间
- **口型同步**: 嘴巴动作是否与语音匹配（主观评价）
- **视频流畅度**: 画面是否流畅，有无卡顿（可看 WebRTC stats）

记录格式：
```
首包延迟: ____ 秒
口型同步: 好 / 一般 / 差
视频流畅度: 流畅 / 有卡顿 / 很卡
总体评价: 可接受 / 不可接受
```

- [ ] **Step 5: 测试较长文本**

输入一段更长的文字（50-100 字）：
```
今天天气真不错，我想出去走走。你喜欢什么运动呢？我个人比较喜欢游泳和跑步，尤其是早晨的慢跑，让人感觉特别清爽。
```

Expected: 数字人连续说话，中间无明显停顿

- [ ] **Step 6: 评估结果**

根据测试结果决定下一步：

**如果效果可接受**（首包延迟 < 5 秒，口型同步好，视频流畅）：
→ 继续 Phase 3b（server.py 改造）

**如果效果不可接受**：
1. 尝试切换到 Wav2Lip 模型（重启容器时改 `--model wav2lip`）
2. 如果延迟过高，考虑优化 TTS 配置或降低分辨率
3. 如果仍不可接受，考虑回退到 Live2D 方案

---

## Phase 3b: server.py 改造

> **目标**: 移除 edge-tts 相关代码，server.py 只输出纯文字 + 情绪标签。

### Task 6: 修改 server.py — 移除 TTS 相关导入

**Files:**
- Modify: `server.py:30-31`

- [ ] **Step 1: 移除 TTS 相关的 import 语句**

打开 `server.py`，删除以下两行：

```python
from sentence_splitter import split_sentences
from tts_client import tts_stream
```

- [ ] **Step 2: 验证文件语法**

```bash
conda run -n py310 python -c "import server"
```

Expected: 无报错（可能会缺少依赖，但不应该有 ImportError 关于 tts_client 或 sentence_splitter）

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "refactor(server): remove TTS imports for LiveTalking integration"
```

---

### Task 7: 修改 server.py — 简化 _event_stream 函数

**Files:**
- Modify: `server.py:340-356`

- [ ] **Step 1: 替换 TTS 流水线为纯文字输出**

在 `_event_stream` 函数中，找到以下代码块（约 340-356 行）：

```python
        # 分句
        sentences = split_sentences(final_message)
        if not sentences:
            sentences = [final_message]

        # 流水线发送文字 + 音频（tts_stream 并发处理，按序 yield）
        async for sentence, audio_b64 in tts_stream(sentences):
            # 1. 先 yield 文字（前端立即显示）
            text_data = json.dumps({"type": "text", "content": sentence}, ensure_ascii=False)
            yield "data: " + text_data + "\n\n"

            # 2. yield 音频
            audio_data = json.dumps({"type": "audio", "data": audio_b64}, ensure_ascii=False)
            yield "data: " + audio_data + "\n\n"

        # 发送音频结束标记
        yield "data: " + json.dumps({"type": "audio_done"}) + "\n\n"
```

替换为：

```python
        # 发送完整文本（LiveTalking 会通过 WebSocket 接收文字做 TTS + 口型渲染）
        text_data = json.dumps({"type": "text", "content": final_message}, ensure_ascii=False)
        yield "data: " + text_data + "\n\n"
```

- [ ] **Step 2: 验证文件语法**

```bash
conda run -n py310 python -c "import server"
```

Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "refactor(server): simplify SSE output, remove TTS pipeline"
```

---

### Task 8: 修改 config.py — 移除 TTS 配置

**Files:**
- Modify: `config.py:88-93`

- [ ] **Step 1: 删除 TTS 配置部分**

打开 `config.py`，删除以下代码块（约 88-93 行）：

```python
# ==========================================
# TTS 配置（edge-tts 云端合成）
# ==========================================
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
TTS_CHUNK_SIZE = int(os.getenv("TTS_CHUNK_SIZE", "40"))
TTS_PREBUFFER = int(os.getenv("TTS_PREBUFFER", "4"))
```

- [ ] **Step 2: 验证文件语法**

```bash
conda run -n py310 python -c "import config"
```

Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "refactor(config): remove edge-tts configuration"
```

---

### Task 9: 删除 tts_client.py

**Files:**
- Delete: `tts_client.py`

- [ ] **Step 1: 删除文件**

```bash
rm tts_client.py
```

- [ ] **Step 2: 验证无其他文件引用 tts_client**

```bash
grep -r "tts_client" --include="*.py" .
```

Expected: 无输出（或只有注释/文档中的引用）

如果有其他文件引用 `tts_client`，需要移除这些引用。

- [ ] **Step 3: Commit**

```bash
git add -A tts_client.py
git commit -m "refactor: remove tts_client.py (TTS now handled by LiveTalking)"
```

---

### Task 10: 更新 requirements.txt — 移除 edge-tts

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 移除 edge-tts 依赖**

打开 `requirements.txt`，删除以下行：

```
edge-tts
```

（如果存在的话）

- [ ] **Step 2: 验证依赖安装**

```bash
conda run -n py310 python -c "import server; print('OK')"
```

Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add requirements.txt
git commit -m "refactor: remove edge-tts from requirements"
```

---

### Task 11: 测试 server.py 改造后功能

**Files:** 无

- [ ] **Step 1: 启动 server.py**

```bash
conda run -n py310 python server.py
```

Expected: 服务启动成功，监听 8000 端口

- [ ] **Step 2: 测试聊天功能（curl）**

```bash
curl -X POST http://127.0.0.1:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"query": "你好", "user_id": "test"}' \
  --no-buffer
```

Expected: SSE 流输出，包含以下事件：
- `data: {"type": "status", "status": "detecting_mood"}`
- `data: {"type": "status", "status": "thinking"}`
- `data: {"type": "text", "content": "..."}`  ← 完整文本（不再分句）
- `data: {"type": "mood", "mood": "..."}`
- `data: {"type": "done"}`

**不应该出现**: `{"type": "audio", ...}` 或 `{"type": "audio_done", ...}`

- [ ] **Step 3: 验证无 TTS 相关日志**

查看 server.py 的终端输出，确认没有 TTS 相关的错误或警告。

- [ ] **Step 4: Commit（如有修复）**

```bash
git add -A
git commit -m "fix: resolve any issues from TTS removal"
```

---

## Phase 3c: 前端集成

> **目标**: 前端同时连接 server.py（SSE 文字 + 情绪）和 LiveTalking（WebRTC 视频流）。

### Task 12: 修改 index.html — 替换 placeholder 为视频容器

**Files:**
- Modify: `static/index.html:19-39`

- [ ] **Step 1: 替换 avatar 占位区为视频容器**

打开 `static/index.html`，找到 `<!-- Avatar 占位区 -->` 部分（约 19-39 行），替换为：

```html
            <!-- Avatar 视频区 (Phase 3: LiveTalking WebRTC) -->
            <div class="avatar-section">
                <div class="avatar-area">
                    <video id="livetalking-video" autoplay playsinline></video>
                    <div class="avatar-placeholder" id="avatar-placeholder">
                        <div class="icon">📡</div>
                        <div><small>连接 LiveTalking...</small></div>
                    </div>
                </div>
                <div class="mood-indicator">
                    <span class="emoji">😄</span>
                    <span id="mood-text">Lisa 心情：等待中</span>
                </div>
                <!-- 移除 audio-wave，LiveTalking 自带音频 -->
            </div>
```

- [ ] **Step 2: 移除 TTS 开关按钮**

在同一文件中，找到：
```html
<button id="tts-toggle" onclick="toggleTTS()" title="语音开关">🔊</button>
```

删除这一行。

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat(frontend): replace avatar placeholder with LiveTalking video container"
```

---

### Task 13: 修改 app.js — 移除音频播放逻辑

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: 移除音频相关变量和函数**

打开 `static/js/app.js`，删除以下内容：

1. 删除音频队列相关变量（约 108-113 行）：
```javascript
// 音频队列 + 文字队列（同步显示）
let audioQueue = [];
let textQueue = [];
let isPlaying = false;
let ttsEnabled = true;
```

替换为：
```javascript
// 文字队列（LiveTalking 处理语音，前端只显示文字）
let textQueue = [];
```

2. 删除 `showAudioWave()`、`hideAudioWave()`、`playNextAudio()`、`toggleTTS()` 函数（约 115-183 行）。

- [ ] **Step 2: 修改 sendMessage 函数 — 移除音频队列初始化**

在 `sendMessage` 函数中，找到：
```javascript
    audioQueue = [];
    textQueue = [];
    isPlaying = false;
```

替换为：
```javascript
    textQueue = [];
```

- [ ] **Step 3: 修改 handleSSEEvent — 移除 audio 和 audio_done 处理**

在 `handleSSEEvent` 函数中，删除 `case "audio":` 和 `case "audio_done":` 分支（约 278-299 行）。

修改 `case "text":` 分支，简化为：
```javascript
        case "text":
            hideStatus()
            currentBotText += data.content;
            if (currentBotMsg) {
                currentBotMsg.textContent = currentBotText;
                if (cursor) currentBotMsg.appendChild(cursor);
            }
            scrollToBottom();
            break;
```

- [ ] **Step 4: 验证语法**

在浏览器控制台（F12）中检查是否有 JS 语法错误。

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js
git commit -m "refactor(frontend): remove audio playback logic (TTS handled by LiveTalking)"
```

---

### Task 14: 修改 app.js — 新增 WebRTC 连接逻辑

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: 在文件顶部（认证检查之后）添加 WebRTC 配置**

在 `const userId = username;` 之后，添加：

```javascript

/* ==========================================
   LiveTalking WebRTC 配置
   ========================================== */
const LIVETALKING_URL = "http://localhost:8010";
const LIVETALKING_WS_URL = "ws://localhost:8010/human";

let pc = null;           // RTCPeerConnection
let wsHuman = null;      // WebSocket for sending text to LiveTalking
let videoElement = null; // <video> element


/* ==========================================
   初始化 WebRTC 连接
   ========================================== */
async function initLiveTalking() {
    videoElement = document.getElementById("livetalking-video");
    const placeholder = document.getElementById("avatar-placeholder");

    if (!videoElement) {
        console.error("[LiveTalking] video element not found");
        return;
    }

    try {
        // 1. 创建 RTCPeerConnection
        pc = new RTCPeerConnection();

        // 2. 监听视频流
        pc.ontrack = function(event) {
            console.log("[LiveTalking] received track:", event.track.kind);
            if (event.track.kind === "video") {
                videoElement.srcObject = event.streams[0];
                if (placeholder) placeholder.style.display = "none";
            }
        };

        // 3. 监听连接状态
        pc.onconnectionstatechange = function() {
            console.log("[LiveTalking] connection state:", pc.connectionState);
            if (pc.connectionState === "failed") {
                if (placeholder) {
                    placeholder.innerHTML = '<div class="icon">❌</div><div><small>连接失败</small></div>';
                    placeholder.style.display = "flex";
                }
            }
        };

        // 4. 创建 SDP offer
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        // 5. 发送 offer 到 LiveTalking
        const response = await fetch(LIVETALKING_URL + "/offer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                sdp: offer.sdp,
                type: offer.type,
            }),
        });

        const answer = await response.json();
        await pc.setRemoteDescription(new RTCSessionDescription(answer));

        console.log("[LiveTalking] WebRTC connected");

        // 6. 建立 WebSocket 连接（用于发送文字）
        wsHuman = new WebSocket(LIVETALKING_WS_URL);
        wsHuman.onopen = function() {
            console.log("[LiveTalking] WebSocket connected");
        };
        wsHuman.onerror = function(err) {
            console.error("[LiveTalking] WebSocket error:", err);
        };
        wsHuman.onclose = function() {
            console.log("[LiveTalking] WebSocket closed");
        };

    } catch (err) {
        console.error("[LiveTalking] init failed:", err);
        if (placeholder) {
            placeholder.innerHTML = '<div class="icon">❌</div><div><small>连接失败: ' + err.message + '</small></div>';
        }
    }
}

// 页面加载时初始化
initLiveTalking();
```

- [ ] **Step 2: 修改 sendMessage — 发送文字到 LiveTalking**

在 `sendMessage` 函数中，在 `handleSSEEvent` 处理完 `text` 事件后，需要把文字也发给 LiveTalking。

修改 `handleSSEEvent` 函数的 `case "text":` 分支：

```javascript
        case "text":
            hideStatus()
            currentBotText += data.content;
            if (currentBotMsg) {
                currentBotMsg.textContent = currentBotText;
                if (cursor) currentBotMsg.appendChild(cursor);
            }
            scrollToBottom();

            // 发送文字到 LiveTalking（触发 TTS + 口型渲染）
            if (wsHuman && wsHuman.readyState === WebSocket.OPEN) {
                wsHuman.send(JSON.stringify({
                    type: "text",
                    text: data.content,
                }));
                console.log("[LiveTalking] sent text:", data.content);
            }
            break;
```

- [ ] **Step 3: 验证语法**

在浏览器控制台（F12）中检查是否有 JS 语法错误。

- [ ] **Step 4: Commit**

```bash
git add static/js/app.js
git commit -m "feat(frontend): add WebRTC connection to LiveTalking"
```

---

### Task 15: 修改 style.css — 视频区域样式

**Files:**
- Modify: `static/css/style.css`

- [ ] **Step 1: 修改 .avatar-area 样式 — 支持视频**

在 `style.css` 中，找到 `.avatar-area` 样式块（约 91-102 行），替换为：

```css
.avatar-area {
    width: 300px;
    height: 400px;
    border: 2px dashed #d0d7de;
    border-radius: 16px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #8b949e;
    font-size: 14px;
    background: #fff;
    position: relative;
    overflow: hidden;
}

.avatar-area video {
    width: 100%;
    height: 100%;
    object-fit: cover;
    border-radius: 14px;
}

.avatar-area .avatar-placeholder {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #fff;
    z-index: 1;
}
```

- [ ] **Step 2: 移除 audio-wave 样式**

删除以下样式块（约 127-154 行）：

```css
/* 语音波形动画 */
.audio-wave {
    display: flex;
    align-items: center;
    gap: 3px;
    margin-top: 16px;
    height: 30px;
}

.audio-wave .bar {
    width: 4px;
    background: rgba(79, 140, 255, 0.6);
    border-radius: 2px;
    animation: wave 1.2s ease-in-out infinite;
}

.audio-wave .bar:nth-child(1) { height: 10px; animation-delay: 0s; }
.audio-wave .bar:nth-child(2) { height: 20px; animation-delay: 0.1s; }
.audio-wave .bar:nth-child(3) { height: 15px; animation-delay: 0.2s; }
.audio-wave .bar:nth-child(4) { height: 25px; animation-delay: 0.3s; }
.audio-wave .bar:nth-child(5) { height: 12px; animation-delay: 0.4s; }
.audio-wave .bar:nth-child(6) { height: 18px; animation-delay: 0.5s; }
.audio-wave .bar:nth-child(7) { height: 8px; animation-delay: 0.6s; }

@keyframes wave {
    0%, 100% { transform: scaleY(1); }
    50% { transform: scaleY(0.4); }
}
```

- [ ] **Step 3: 移除 TTS 开关按钮样式**

删除以下样式块（约 284-299 行）：

```css
/* ==========================================
   TTS 语音开关按钮
   ========================================== */
#tts-toggle {
    background: none;
    border: 1px solid #ddd;
    border-radius: 8px;
    padding: 6px 10px;
    cursor: pointer;
    font-size: 18px;
    transition: background 0.2s;
}

#tts-toggle:hover {
    background: #f0f0f0;
}
```

- [ ] **Step 4: Commit**

```bash
git add static/css/style.css
git commit -m "style(frontend): add video container styles, remove audio-wave and TTS toggle"
```

---

### Task 16: 端到端测试 — 完整流程

**Files:** 无

- [ ] **Step 1: 确保 LiveTalking 容器运行**

```bash
docker ps | grep livetalking
```

Expected: 容器正在运行

如果未运行：
```bash
docker start livetalking-server
```

- [ ] **Step 2: 启动 server.py**

```bash
conda run -n py310 python server.py
```

- [ ] **Step 3: 登录前端页面**

浏览器访问：`http://localhost:8000`

Expected:
- 左侧视频区域显示 LiveTalking 数字人（WebRTC 连接成功）
- 如果连接失败，显示"连接失败"提示

- [ ] **Step 4: 发送消息测试**

在聊天框输入：
```
你好，Lisa！
```

Expected:
1. 右侧聊天气泡显示 Lisa 的回复文字
2. 左侧数字人开始说话（口型同步）
3. 声音从 LiveTalking 视频流播放（不是浏览器本地 Audio 对象）

- [ ] **Step 5: 检查浏览器控制台**

打开 F12 → Console，查看日志：
- `[LiveTalking] WebRTC connected`
- `[LiveTalking] WebSocket connected`
- `[LiveTalking] sent text: ...`

如果有错误，记录错误信息并修复。

- [ ] **Step 6: 测试命令系统**

输入 `/help`，验证命令系统正常工作（命令不经过 LiveTalking，直接由 server.py 处理）。

- [ ] **Step 7: 测试情绪显示**

输入能触发不同情绪的消息，观察情绪指示器是否更新。

- [ ] **Step 8: Commit（如有修复）**

```bash
git add -A
git commit -m "fix: resolve integration issues from e2e testing"
```

---

## Phase 3d: Lisa 形象定制

> **目标**: 用 AI 生成 Lisa 的写实形象，配置到 LiveTalking。

### Task 17: 生成 Lisa 形象照片

**Files:**
- Create: `livetalking_data/avatars/lisa/`（LiveTalking 素材目录）

- [ ] **Step 1: 用 AI 生图工具生成照片**

使用 Midjourney / Stable Diffusion / 通义万相等工具，生成一张写实风格的女性照片。

Prompt 建议：
```
A professional portrait photo of a 30-year-old Asian woman, elegant and mature, 
clear visible mouth, neutral expression, clean white background, 
high resolution, studio lighting, front-facing view
```

要求：
- 正面照（不要侧脸）
- 嘴巴清晰可见（不要遮挡）
- 纯色背景（白色或浅灰）
- 分辨率至少 512x512
- 格式：JPG 或 PNG

- [ ] **Step 2: 将照片放入 LiveTalking 素材目录**

```bash
mkdir -p "g:\JupyterProject\LiveTalking\data\avatars\lisa"
cp <生成的照片路径> "g:\JupyterProject\LiveTalking\data\avatars\lisa\lisa.jpg"
```

- [ ] **Step 3: 配置 LiveTalking 使用自定义形象**

参考 LiveTalking 文档配置自定义数字人：
https://livetalking-doc.readthedocs.io/zh-cn/latest/usage.html

通常需要修改启动参数或配置文件，指定新的 avatar 路径。

- [ ] **Step 4: 重启 LiveTalking 容器**

```bash
docker restart livetalking-server
```

- [ ] **Step 5: 验证 Lisa 形象**

浏览器访问 `http://localhost:8010/webrtcapi.html`，确认数字人形象已替换为 Lisa。

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "feat(avatar): add Lisa custom avatar for LiveTalking"
```

---

## 后续优化（可选）

### 文字和视频时间同步优化

当前方案中，server.py 的 SSE 文字和 LiveTalking 的视频是独立的，可能存在时间差。

优化方向：
1. **前端协调**：收到 SSE 文字后，延迟 100-200ms 再发给 LiveTalking，给视频渲染留缓冲
2. **WebSocket 同步**：server.py 直接通过 WebSocket 发文字给 LiveTalking，而不是前端中转
3. **情绪联动**：根据 SSE 中的 mood 事件，触发 LiveTalking 的表情切换（如果支持）

### LiveTalking 直接对接 LLM

当前方案中，server.py 作为中间层。可以考虑让 LiveTalking 直接调用 LLM API，减少一层转发。

但这会失去 server.py 的情绪检测、上下文管理、RAG 工具等功能，不推荐。

---

## 验收标准

### Phase 3a 验收
- [ ] LiveTalking Docker 容器正常启动
- [ ] 可以通过 `webrtcapi.html` 访问
- [ ] 输入文字后，数字人说话
- [ ] 首包延迟 < 5 秒
- [ ] 口型同步效果可接受
- [ ] 视频流畅（> 15 FPS）

### Phase 3b 验收
- [ ] server.py 移除 TTS 代码后，聊天功能正常
- [ ] SSE 输出只有 text/mood/status/done 事件，无 audio 事件
- [ ] 无 tts_client.py 文件

### Phase 3c 验收
- [ ] 前端同时连接 server.py 和 LiveTalking
- [ ] 文字和视频基本同步（延迟 < 1 秒差异）
- [ ] WebRTC 连接稳定，无频繁断线

### Phase 3d 验收
- [ ] Lisa 形象配置完成
- [ ] 数字人形象为写实女性（30 岁左右）

---

## 风险与缓解

**风险 1: Docker GPU 支持问题**
- 缓解：先运行 `docker run --rm --gpus all nvidia-smi` 验证
- 如果失败，检查 NVIDIA 驱动版本和 Docker 配置

**风险 2: WebRTC 连接失败**
- 缓解：检查浏览器控制台日志，确认端口 8010 可访问
- 如果 P2P 失败，考虑配置 TURN 服务器

**风险 3: LiveTalking 构建失败**
- 缓解：检查 Dockerfile 中的 CUDA 版本，确保与驱动兼容
- 如果网络问题，使用国内镜像源

**风险 4: 延迟过高**
- 缓解：尝试切换到 Wav2Lip 模型（更快但质量较低）
- 如果仍不可接受，考虑回退到 Live2D 方案

**已消除的风险: RTX 5090D 兼容性**
- LiveTalking 官方已升级到 CUDA 12.8 + PyTorch 2.9.1，完全兼容 RTX 5090D

---

**计划完成，等待用户确认后开始实施。**
