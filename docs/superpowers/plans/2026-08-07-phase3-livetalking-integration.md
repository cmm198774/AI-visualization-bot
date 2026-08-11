# Phase 3: LiveTalking 数字人集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 LiveTalking（MuseTalk 模型）集成到 Lisa 聊天机器人，实现写实风格数字人视频输出 + 文字聊天双通道。

**Architecture:** 前端同时维护两个连接：SSE 连接 server.py（LLM 推理 + 情绪检测 → 返回文字+情绪），WebRTC 连接 LiveTalking（文字 → TTS 语音合成 → MuseTalk 口型渲染 → 视频流输出）。server.py 移除 TTS 职责，LiveTalking 独立运行在 Docker 容器（CUDA 12.8 + PyTorch 2.9.1）。

**Tech Stack:** FastAPI (server.py), LiveTalking (Docker, MuseTalk), WebRTC, SSE, edge-tts (LiveTalking 内置)

---

## Phase 3a: Docker 镜像烘焙 + Demo 验证

**目标:** 重新构建 Docker 镜像（烘焙 torch 2.9.1），通过浏览器测试数字人说话效果。

### Task 1: 重新构建 Docker 镜像（烘焙 torch 2.9.1）

**Files:**
- 使用: `G:\JupyterProject\LiveTalking\Dockerfile.custom`

**背景:** 当前镜像 requirements.txt 的 `accelerate` 会拉取 PyPI 的 torch 2.13.0，覆盖 cu128 版本。Dockerfile 已在 requirements 之后重新安装 torch 2.9.1，但旧镜像还是有问题。需要重新 build 一次，把正确的 torch 版本烘焙进去，避免每次启动都下载 900MB。

- [ ] **Step 1: 停掉当前容器**

```bash
docker stop livetalking-demo 2>/dev/null; docker rm livetalking-demo 2>/dev/null
```

- [ ] **Step 2: 重新构建镜像**

```bash
cd /g/JupyterProject/LiveTalking
docker build -f Dockerfile.custom -t livetalking:cuda12.8 .
```

预期时间：~20-30 分钟（利用 Docker 缓存，前面的层不用重新构建）

- [ ] **Step 3: 验证 torch 版本已烘焙**

```bash
docker run --rm livetalking:cuda12.8 python -c "import torch; print(f'torch={torch.__version__}, cuda={torch.cuda.is_available()}')"
```

预期输出：`torch=2.9.1+cu128, cuda=True`

- [ ] **Step 4: 启动容器（无需 pip install 修复）**

```bash
docker run --gpus all \
  -p 8010:8010 \
  -v /g/JupyterProject/LiveTalking/models:/app/models \
  -v /g/JupyterProject/LiveTalking/data:/app/data \
  -v /g/JupyterProject/LiveTalking/logs:/app/logs \
  --name livetalking-demo \
  livetalking:cuda12.8
```

- [ ] **Step 5: 验证启动成功**

```bash
sleep 30
docker logs livetalking-demo --tail 10
```

预期日志包含：`start http server; http://<serverip>:8010`

- [ ] **Step 6: 打开浏览器测试 Demo**

在浏览器打开 `http://127.0.0.1:8010/webrtcapi.html`：
1. 点击 "Start" 建立 WebRTC 连接
2. 在输入框输入 "你好，我是 Lisa，很高兴认识你！"
3. 点击 "Send"
4. 观察：数字人是否开始说话、口型是否同步、延迟大约几秒

---

## Phase 3b: server.py 改造（移除 TTS 代码）

**目标:** 移除 server.py 中的 TTS 相关代码，简化 SSE 输出为纯文字 + 情绪。

### Task 2: 移除 TTS 相关 import

**Files:**
- Modify: `g:\JupyterProject\20260725_Agent_AI可视化机器人\server.py:30-31`

- [ ] **Step 1: 删除 tts_client 和 sentence_splitter 的 import**

将 server.py 第 30-31 行：
```python
from sentence_splitter import split_sentences
from tts_client import tts_stream
```

删除这两行。

- [ ] **Step 2: 验证 import 无误**

```bash
cd "g:/JupyterProject/20260725_Agent_AI可视化机器人"
conda run -n py310 python -c "import server"
```

预期：无报错。

### Task 3: 重写 _event_stream 的 SSE 输出逻辑

**Files:**
- Modify: `g:\JupyterProject\20260725_Agent_AI可视化机器人\server.py:340-356`

**改动:** 原来 SSE 输出是 `text + audio 交替流`，现在改为纯 `text` 流。

- [ ] **Step 1: 替换 SSE 输出段落**

将 `_event_stream()` 函数中从 `# 分句` 到 `yield "data: " + json.dumps({"type": "audio_done"}) + "\n\n"` 的部分（原 340-356 行），替换为：

```python
        # 直接输出完整文本（不再分句 + TTS）
        text_data = json.dumps({"type": "text", "content": final_message}, ensure_ascii=False)
        yield "data: " + text_data + "\n\n"
```

改动说明：
- 删除 `split_sentences(final_message)` 调用
- 删除 `tts_stream(sentences)` 循环
- 删除 `audio_done` 事件
- 直接 yield 整段文字

- [ ] **Step 2: 验证 SSE 事件类型**

SSE 现在只输出：
- `{"type": "status", "status": "..."}` — 状态提示
- `{"type": "text", "content": "..."}` — 文字回复（一次性）
- `{"type": "mood", "mood": "..."}` — 情绪标签
- `{"type": "error", "content": "..."}` — 错误
- `{"type": "done"}` — 结束标记

- [ ] **Step 3: 启动 server.py 验证**

```bash
cd "g:/JupyterProject/20260725_Agent_AI可视化机器人"
conda run -n py310 python server.py
```

打开浏览器测试聊天，确认文字正常输出（无音频）。

### Task 4: 前端移除音频播放逻辑

**Files:**
- Modify: `g:\JupyterProject\20260725_Agent_AI可视化机器人\static\js\app.js`
- Modify: `g:\JupyterProject\20260725_Agent_AI可视化机器人\static\index.html`

- [ ] **Step 1: 删除 app.js 中的音频相关代码**

删除以下代码块（保留其他逻辑）：

```javascript
// 删除：音频队列变量（109-112行）
let audioQueue = [];
let textQueue = [];
let isPlaying = false;
let ttsEnabled = true;

// 删除：showAudioWave / hideAudioWave / playNextAudio 函数（118-171行）

// 删除：toggleTTS 函数（173-183行）

// 删除：handleSSEEvent 中的 case "audio" 和 case "audio_done"（278-299行）
```

- [ ] **Step 2: 删除 index.html 中的音频相关元素**

```html
<!-- 删除：🔊 按钮 -->
<button id="tts-toggle" onclick="toggleTTS()" title="语音开关">🔊</button>

<!-- 删除：声波动画 -->
<div class="audio-wave" id="audio-wave" style="display:none;">...</div>
```

- [ ] **Step 3: 简化 sendMessage() 中的队列初始化**

删除：
```javascript
audioQueue = [];
textQueue = [];
isPlaying = false;
```

- [ ] **Step 4: Ctrl+Shift+R 刷新浏览器，验证纯文字聊天正常**

---

## Phase 3c: 前端集成 LiveTalking（WebRTC + SSE 双连接）

**目标:** 前端同时连接 server.py（SSE 文字）和 LiveTalking（WebRTC 视频），用户输入文字后：
1. server.py 返回 LLM 回复文字 + 情绪
2. 前端将回复文字通过 `/human` API 发送给 LiveTalking
3. LiveTalking 合成语音 + 渲染口型 → WebRTC 视频流输出

### Task 5: 前端新增 WebRTC 连接模块

**Files:**
- Create: `g:\JupyterProject\20260725_Agent_AI可视化机器人\static\js\livetalking.js`

- [ ] **Step 1: 创建 WebRTC 连接管理模块**

```javascript
// static/js/livetalking.js
// LiveTalking WebRTC 连接管理

const LIVETALKING_URL = 'http://127.0.0.1:8010';

let pc = null; // RTCPeerConnection
let liveTalkingSessionId = '0';

/**
 * 建立 WebRTC 连接（视频 + 音频）
 * @param {HTMLVideoElement} videoEl - 视频播放元素
 * @param {HTMLAudioElement} audioEl - 音频播放元素（可选）
 */
async function connectLiveTalking(videoEl, audioEl) {
    const config = { sdpSemantics: 'unified-plan' };

    pc = new RTCPeerConnection(config);

    pc.addEventListener('track', (evt) => {
        if (evt.track.kind === 'video' && videoEl) {
            videoEl.srcObject = evt.streams[0];
        } else if (evt.track.kind === 'audio' && audioEl) {
            audioEl.srcObject = evt.streams[0];
        }
    });

    pc.addTransceiver('video', { direction: 'recvonly' });
    pc.addTransceiver('audio', { direction: 'recvonly' });

    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);

    // 等待 ICE gathering 完成
    await new Promise((resolve) => {
        if (pc.iceGatheringState === 'complete') {
            resolve();
        } else {
            const checkState = () => {
                if (pc.iceGatheringState === 'complete') {
                    pc.removeEventListener('icegatheringstatechange', checkState);
                    resolve();
                }
            };
            pc.addEventListener('icegatheringstatechange', checkState);
        }
    });

    const response = await fetch(`${LIVETALKING_URL}/offer`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            sdp: pc.localDescription.sdp,
            type: pc.localDescription.type,
        }),
    });

    const answer = await response.json();
    liveTalkingSessionId = answer.sessionid;
    await pc.setRemoteDescription(answer);

    console.log('[LiveTalking] WebRTC connected, session:', liveTalkingSessionId);
}

/**
 * 发送文字到 LiveTalking（触发 TTS + 口型渲染）
 * @param {string} text - 要朗读的文字
 */
async function sendToLiveTalking(text) {
    if (!pc || pc.connectionState !== 'connected') {
        console.warn('[LiveTalking] not connected, skip');
        return;
    }

    await fetch(`${LIVETALKING_URL}/human`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            text: text,
            type: 'echo',
            interrupt: true,
            sessionid: String(liveTalkingSessionId),
        }),
    });

    console.log('[LiveTalking] sent text:', text.substring(0, 30));
}

/**
 * 断开 WebRTC 连接
 */
function disconnectLiveTalking() {
    if (pc) {
        setTimeout(() => pc.close(), 500);
        pc = null;
    }
}
```

- [ ] **Step 2: 在 index.html 引入脚本**

在 `</body>` 前添加：
```html
<script src="/static/js/livetalking.js"></script>
```

### Task 6: 前端集成视频播放区域 + 双连接逻辑

**Files:**
- Modify: `g:\JupyterProject\20260725_Agent_AI可视化机器人\static\index.html`
- Modify: `g:\JupyterProject\20260725_Agent_AI可视化机器人\static\js\app.js`
- Modify: `g:\JupyterProject\20260725_Agent_AI可视化机器人\static\css\style.css`

- [ ] **Step 1: 修改 index.html 布局**

将 avatar-section 的占位区替换为视频区域：

```html
<!-- Avatar 区域：WebRTC 视频 -->
<div class="avatar-section">
    <div class="avatar-area">
        <video id="livetalking-video" autoplay playsinline muted></video>
        <audio id="livetalking-audio" autoplay></audio>
        <div id="livetalking-status" class="livetalking-status">连接中...</div>
    </div>
    <div class="mood-indicator">
        <span class="emoji">😄</span>
        <span id="mood-text">Lisa 心情：等待中</span>
    </div>
</div>
```

- [ ] **Step 2: 修改 app.js — 建立双连接**

在 app.js 顶部（认证检查之后）添加：

```javascript
// 页面加载时建立 LiveTalking WebRTC 连接
const videoEl = document.getElementById('livetalking-video');
const audioEl = document.getElementById('livetalking-audio');
const ltStatus = document.getElementById('livetalking-status');

(async function initLiveTalking() {
    try {
        await connectLiveTalking(videoEl, audioEl);
        if (ltStatus) ltStatus.style.display = 'none';
    } catch (e) {
        console.error('[LiveTalking] connect failed:', e);
        if (ltStatus) ltStatus.textContent = '数字人未连接';
    }
})();
```

- [ ] **Step 3: 修改 app.js — SSE 收到文字时同步发送给 LiveTalking**

在 `handleSSEEvent()` 的 `case "text"` 中，文字显示后同时发送给 LiveTalking：

```javascript
case "text":
    hideStatus()
    currentBotText += data.content;
    if (currentBotMsg) {
        currentBotMsg.textContent = currentBotText;
        if (cursor) currentBotMsg.appendChild(cursor);
    }
    scrollToBottom();
    // 发送给 LiveTalking（触发 TTS + 口型渲染）
    sendToLiveTalking(data.content);
    break;
```

- [ ] **Step 4: 添加 CSS 样式**

在 style.css 中添加：

```css
/* LiveTalking 视频区域 */
#livetalking-video {
    width: 100%;
    max-width: 400px;
    border-radius: 12px;
    background: #1a1a2e;
}

.livetalking-status {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    color: #888;
    font-size: 14px;
}

.avatar-area {
    position: relative;
    display: flex;
    justify-content: center;
}
```

- [ ] **Step 5: 启动两个服务，端到端测试**

终端 1 — LiveTalking（如果还没启动）：
```bash
docker start livetalking-demo
```

终端 2 — server.py：
```bash
cd "g:/JupyterProject/20260725_Agent_AI可视化机器人"
conda run -n py310 python server.py
```

打开 `http://127.0.0.1:8000`，登录后：
1. 页面加载 → WebRTC 连接 LiveTalking（视频画面出现）
2. 输入消息 → SSE 返回文字 → 文字显示在聊天气泡 + LiveTalking 开始说话
3. 观察：视频口型与文字是否基本同步

---

## Phase 3d: Lisa 形象定制

**目标:** 将 LiveTalking 默认形象替换为用户生成的 Lisa 形象。

### Task 7: 生成 Lisa 形象素材并配置

**Files:**
- 用户操作：生成 Lisa 照片（30 岁女性，正面，嘴巴清晰，纯色背景）
- 操作目录: `G:\JupyterProject\LiveTalking\data\avatars\`

- [ ] **Step 1: 用户生成 Lisa 照片**

使用 AI 生图工具生成一张 Lisa 照片，要求：
- 正面照，面部清晰
- 嘴巴自然张开或闭合
- 纯色背景（白色/浅灰）
- 分辨率至少 512x512
- 保存为 `lisa_portrait.jpg`

- [ ] **Step 2: 将照片放入 avatar 目录**

参考 LiveTalking 文档创建自定义 avatar：
```bash
# 复制照片到 LiveTalking 数据目录
cp lisa_portrait.jpg /g/JupyterProject/LiveTalking/data/avatars/lisa_avatar/

# 参考 LiveTalking 文档处理素材（可能需要运行预处理脚本）
```

具体步骤参考 LiveTalking 官方文档的 "Custom Avatar" 部分。

- [ ] **Step 3: 修改启动命令使用自定义 avatar**

更新 Dockerfile.custom 的 CMD 或启动参数：
```bash
docker run --gpus all \
  -p 8010:8010 \
  -v /g/JupyterProject/LiveTalking/models:/app/models \
  -v /g/JupyterProject/LiveTalking/data:/app/data \
  -v /g/JupyterProject/LiveTalking/logs:/app/logs \
  --name livetalking-lisa \
  livetalking:cuda12.8 \
  python app.py --transport webrtc --model musetalk --avatar_id lisa_avatar --listenport 8010
```

- [ ] **Step 4: 测试 Lisa 形象效果**

打开浏览器测试，确认 Lisa 形象显示正确，口型同步正常。

---

## Phase 3e: 更新项目记忆

### Task 8: 更新 CLAUDE.md

- [ ] **Step 1: 更新 CLAUDE.md Phase 3 部分**

将 Phase 3 状态从"待完成"更新为"已完成"，记录：
- LiveTalking Docker 部署方式
- server.py 改动内容
- 前端改动内容
- 新增配置项
- 启动方式（两个服务）

---

## 关键决策记录

1. **TTS 职责转移**: server.py 不再负责 TTS，完全交给 LiveTalking 内部的 edge-tts。这简化了 server.py，也消除了双端音频同步的复杂度。

2. **文字触发方式**: 前端 SSE 收到文字后，通过 HTTP POST `/human` 发给 LiveTalking（不是 WebSocket），因为 LiveTalking 的 webrtcapi.html 就是这么做的。

3. **双连接架构**: SSE（server.py:8000）负责文字+情绪，WebRTC（LiveTalking:8010）负责视频+音频。前端是协调者。

4. **端口分配**: server.py 用 8000，LiveTalking 用 8010，不冲突。
