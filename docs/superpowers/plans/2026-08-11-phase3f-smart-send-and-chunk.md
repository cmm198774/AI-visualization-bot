# Phase 3f: Send 按钮智能锁定 + Chunk 流水线 + 自动连接

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 取消手动开始/结束按钮实现自动连接，send 按钮根据 LLM 状态和数字人说话状态智能锁定/解锁，LiveTalking 端新增 chunk 处理模块降低首帧延迟。

**Architecture:** 三步递进：Step 1 纯前端（自动连接），Step 2 纯前端（send 锁定），Step 3 前后端联动（chunk 流水线）。每步完成后测试通过再进入下一步。

**Tech Stack:** JavaScript (vanilla), CSS, Python, LiveTalking (aiohttp + aiortc)

**Spec:** `docs/superpowers/specs/2026-08-11-phase3f-smart-send-and-chunk-design.md`

---

## Step 1：自动连接（取消开始/结束按钮）

**目标**：页面加载时自动建立 WebRTC 连接。连接失败时显示"数字人不可用"，文字聊天不受影响。

---

### Task 1：移除 index.html 中的按钮区域

**Files:**
- Modify: `static/index.html:28-33`

- [ ] **Step 1.1：删除 avatar-controls 区域**

将 `index.html` 第 28-33 行的按钮区域整块删除：

```html
<!-- 删除以下 6 行 -->
<!-- 开始/结束 控制按钮 -->
<div class="avatar-controls">
    <button id="start-btn" class="btn-avatar btn-start" onclick="startLiveTalking()">▶ 开始</button>
    <button id="stop-btn" class="btn-avatar btn-stop" onclick="stopLiveTalking()" style="display:none;">■ 结束</button>
    <span id="avatar-status" class="avatar-status">未连接</span>
</div>
```

- [ ] **Step 1.2：升级 script 版本号**

将第 52 行的 `?v=9` 改为 `?v=10`：

```html
<!-- 改前 -->
<script src="/static/js/app.js?v=9"></script>
<!-- 改后 -->
<script src="/static/js/app.js?v=10"></script>
```

- [ ] **Step 1.3：验证 index.html 结构正确**

确认 avatar 区域只剩 `<video>` + `avatar-placeholder` + `mood-indicator`，无多余元素。

---

### Task 2：重写 app.js 的 LiveTalking 管理部分

**Files:**
- Modify: `static/js/app.js`（整体重写 LiveTalking 管理区域，第 21-280 行）

**改动概述**：
- 删除：`pendingText`、`textSendTimer`、`TEXT_SEND_DELAY`、`sentenceQueue`、`isSendingSentence`、`SENTENCE_INTERVAL` 变量
- 删除：`updateAvatarButtons()`、`_resetLiveTalking()`、`startLiveTalking()`、`stopLiveTalking()` 函数
- 重写：`closeLiveTalking()` 去掉按钮操作
- 重写：`initLiveTalking()` 返回 Promise，支持连接失败处理
- 新增：`autoConnectLiveTalking()` 页面加载自动连接
- 重写：`sendToLiveTalking()` 简化，接收 text 参数，不可用时静默跳过
- 删除：`flushPendingText()` 函数

- [ ] **Step 2.1：替换第 21-280 行（LiveTalking 管理 + sendToLiveTalking）**

将 app.js 第 21-280 行（从 `LiveTalking WebRTC 管理` 注释块到 `flushPendingText()` 函数结束）替换为以下完整代码：

```javascript
/* ==========================================
   LiveTalking WebRTC 管理
   ========================================== */
const LIVETALKING_URL = "http://localhost:8010";

let pc = null;
let livetalkingReady = false;
let livetalkingSessionId = "0";


/* ==========================================
   关闭 WebRTC 连接
   ========================================== */
function closeLiveTalking() {
    console.log("[LiveTalking] closing connection...");
    livetalkingReady = false;

    if (pc) {
        pc.close();
        pc = null;
    }

    const video = document.getElementById("livetalking-video");
    if (video) video.srcObject = null;

    const placeholder = document.getElementById("avatar-placeholder");
    if (placeholder) {
        placeholder.innerHTML = '<div class="icon">📡</div><div><small>数字人未连接</small></div>';
        placeholder.style.display = "flex";
        placeholder.classList.remove("unavailable");
    }
}


/* ==========================================
   初始化 LiveTalking WebRTC 连接（返回 Promise）
   ========================================== */
function initLiveTalking() {
    return new Promise(function(resolve, reject) {
        const videoElement = document.getElementById("livetalking-video");
        const placeholder = document.getElementById("avatar-placeholder");

        if (!videoElement) {
            reject(new Error("video element not found"));
            return;
        }

        // 重置占位符
        if (placeholder) {
            placeholder.innerHTML = '<div class="icon">📡</div><div><small>连接 LiveTalking...</small></div>';
            placeholder.style.display = "flex";
            placeholder.classList.remove("unavailable");
        }

        try {
            pc = new RTCPeerConnection({ sdpSemantics: "unified-plan" });

            pc.addEventListener("track", function(evt) {
                console.log("[LiveTalking] received track:", evt.track.kind);
                if (evt.track.kind === "video") {
                    videoElement.srcObject = evt.streams[0];
                }
            });

            pc.onconnectionstatechange = function() {
                console.log("[LiveTalking] connection state:", pc.connectionState);
                if (pc.connectionState === "connected") {
                    livetalkingReady = true;
                    if (placeholder) placeholder.style.display = "none";
                    console.log("[LiveTalking] WebRTC connected, sessionid:", livetalkingSessionId);
                    resolve();
                } else if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
                    livetalkingReady = false;
                    reject(new Error("connection " + pc.connectionState));
                }
            };

            pc.addTransceiver("video", { direction: "recvonly" });
            pc.addTransceiver("audio", { direction: "recvonly" });

            pc.createOffer().then(function(offer) {
                return pc.setLocalDescription(offer);
            }).then(function() {
                return waitForIceGathering(pc);
            }).then(function() {
                console.log("[LiveTalking] sending offer, SDP length:", pc.localDescription.sdp.length);
                return fetch(LIVETALKING_URL + "/offer", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        sdp: pc.localDescription.sdp,
                        type: pc.localDescription.type,
                    }),
                });
            }).then(function(response) {
                if (!response.ok) {
                    return response.text().then(function(t) {
                        throw new Error("/offer HTTP " + response.status + ": " + t.substring(0, 200));
                    });
                }
                return response.json();
            }).then(function(answer) {
                if (answer.sessionid) {
                    livetalkingSessionId = String(answer.sessionid);
                }
                return pc.setRemoteDescription(new RTCSessionDescription(answer));
            }).then(function() {
                console.log("[LiveTalking] SDP exchange complete");
                // resolve 由 onconnectionstatechange 触发
            }).catch(function(err) {
                reject(err);
            });

        } catch (err) {
            reject(err);
        }
    });
}


/* ==========================================
   页面加载时自动连接 LiveTalking
   ========================================== */
function autoConnectLiveTalking() {
    initLiveTalking().then(function() {
        console.log("[LiveTalking] auto connect success");
    }).catch(function(err) {
        console.warn("[LiveTalking] auto connect failed:", err.message);
        livetalkingReady = false;
        var placeholder = document.getElementById("avatar-placeholder");
        if (placeholder) {
            placeholder.innerHTML = '<div class="icon">⚠️</div><div><small>数字人不可用</small></div>';
            placeholder.style.display = "flex";
            placeholder.classList.add("unavailable");
        }
    });
}


/* ==========================================
   等待 ICE 收集完成
   ========================================== */
function waitForIceGathering(pc) {
    return new Promise(function(resolve) {
        if (pc.iceGatheringState === "complete") {
            resolve();
        } else {
            function checkState() {
                if (pc.iceGatheringState === "complete") {
                    pc.removeEventListener("icegatheringstatechange", checkState);
                    resolve();
                }
            }
            pc.addEventListener("icegatheringstatechange", checkState);
            setTimeout(resolve, 5000);
        }
    });
}


/* ==========================================
   发送文字到 LiveTalking（不可用时静默跳过）
   ========================================== */
function sendToLiveTalking(text) {
    if (!livetalkingReady || !text) return;

    console.log("[LiveTalking] sending text:", text.substring(0, 50) + "...");

    fetch(LIVETALKING_URL + "/human", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            text: text,
            type: "echo",
            interrupt: false,
            sessionid: livetalkingSessionId,
        }),
    })
    .then(function(res) {
        if (!res.ok) {
            console.error("[LiveTalking] /human HTTP error:", res.status);
            return null;
        }
        return res.json();
    })
    .then(function(data) {
        if (data) console.log("[LiveTalking] /human done");
    })
    .catch(function(err) {
        console.error("[LiveTalking] /human error:", err);
    });
}
```

- [ ] **Step 2.2：更新 sendMessage() 中移除 pendingText 相关代码**

找到 `sendMessage()` 函数（约第 367 行），删除第 376-377 行的 pendingText 重置代码：

```javascript
// 删除以下 2 行
    pendingText = "";
    flushPendingText();
```

- [ ] **Step 2.3：更新 handleSSEEvent() 中移除文字缓冲逻辑**

找到 `handleSSEEvent()` 中的 `case "text":` 分支（约第 443-455 行），删除底部的缓冲逻辑（第 451-454 行）：

```javascript
// 删除以下 4 行（保留 scrollToBottom()）
            pendingText += data.content;
            if (textSendTimer) clearTimeout(textSendTimer);
            textSendTimer = setTimeout(flushPendingText, TEXT_SEND_DELAY);
```

找到 `case "done":` 分支（约第 469-474 行），删除 `flushPendingText()` 调用：

```javascript
// 删除这一行
            flushPendingText();
```

- [ ] **Step 2.4：在文件末尾添加自动连接触发**

将文件末尾（第 537-540 行）的注释替换为：

```javascript
/* ==========================================
   页面加载时自动连接 LiveTalking
   ========================================== */
window.addEventListener("DOMContentLoaded", function() {
    autoConnectLiveTalking();
});
```

- [ ] **Step 2.5：验证 app.js 中无残留引用**

在 app.js 中搜索以下字符串，确认已全部删除：
- `updateAvatarButtons`
- `startLiveTalking`
- `stopLiveTalking`
- `_resetLiveTalking`
- `pendingText`
- `flushPendingText`
- `sentenceQueue`
- `isSendingSentence`

---

### Task 3：更新 style.css

**Files:**
- Modify: `static/css/style.css:135-182`

- [ ] **Step 3.1：删除按钮相关样式**

删除第 135-182 行（从 `/* 控制按钮 */` 到 `.avatar-status.connected {}` 结束）：

```css
/* 删除以下全部内容（约 48 行） */
/* 控制按钮（开始/结束） */
.avatar-controls { ... }
.btn-avatar { ... }
.btn-start { ... }
.btn-start:hover { ... }
.btn-stop { ... }
.btn-stop:hover { ... }
.avatar-status { ... }
.avatar-status.connected { ... }
```

- [ ] **Step 3.2：添加 placeholder 不可用样式**

在 `.avatar-placeholder .icon {}` 后面（约第 133 行之后）添加：

```css
/* 数字人不可用状态 */
.avatar-placeholder.unavailable {
    background: #fef2f2;
}

.avatar-placeholder.unavailable .icon {
    filter: grayscale(0.5);
}
```

---

### Task 4：Step 1 测试验证

- [ ] **Step 4.1：启动 LiveTalking 服务**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe app.py --model musetalk --avatar_id musetalk_avatar1 --transport webrtc --listenport 8010 --pool_size 2
```

- [ ] **Step 4.2：启动 Lisa 主服务**

```bash
cd g:\JupyterProject\20260725_Agent_AI可视化机器人
conda run -n py310 python server.py
```

- [ ] **Step 4.3：浏览器验证（Ctrl+Shift+R 强制刷新）**

1. 打开 `http://localhost:8000`，登录后进入聊天页面
2. **验证**：页面加载后视频自动出现（无需手动点按钮）
3. **验证**：开始/结束按钮已消失
4. 输入文字发送，**验证**：文字回复正常，数字人说话正常

- [ ] **Step 4.4：连接失败场景验证**

1. 关闭 LiveTalking 服务
2. 刷新页面
3. **验证**：placeholder 显示 ⚠️ "数字人不可用"（红色背景）
4. 输入文字发送，**验证**：文字回复正常（数字人被跳过）

---

### Task 5：Step 1 提交

- [ ] **Step 5.1：提交代码**

```bash
git add static/index.html static/js/app.js static/css/style.css
git commit -m "feat(phase3f-step1): auto-connect LiveTalking, remove start/stop buttons"
```

---

## Step 2：Send 按钮智能锁定

**目标**：send 按钮根据 `isSending`（LLM 是否在处理）和 `isSpeaking`（数字人是否在说话）自动锁定/解锁。通过 Proxy 监听状态变化，按钮自动响应。

**前置条件**：Step 1 测试通过。

---

### Task 6：添加 callState Proxy + updateSendButton()

**Files:**
- Modify: `static/js/app.js`
- Modify: `static/css/style.css`

- [ ] **Step 6.1：在 app.js 的 LiveTalking 管理区域之后、情绪映射之前，添加 callState Proxy**

在 `sendToLiveTalking()` 函数之后、`MOOD_EMOJI` 定义之前，插入以下代码：

```javascript
/* ==========================================
   Send 按钮状态管理（Proxy 自动响应）
   ========================================== */
var callState = new Proxy(
    { isSending: false, isSpeaking: false },
    {
        set: function(target, prop, value) {
            target[prop] = value;
            updateSendButton();
            return true;
        }
    }
);

var speakPollTimer = null;


/* ==========================================
   更新 send 按钮状态
   LiveTalking 可用时：isSending || isSpeaking → 锁定
   LiveTalking 不可用时：仅 isSending → 锁定
   ========================================== */
function updateSendButton() {
    var btn = document.getElementById("send-btn");
    if (!btn) return;
    var locked;
    if (livetalkingReady) {
        locked = callState.isSending || callState.isSpeaking;
    } else {
        locked = callState.isSending;
    }
    btn.disabled = locked;
}


/* ==========================================
   启动/停止 isSpeaking 轮询（50ms）
   ========================================== */
function startSpeakPolling() {
    if (speakPollTimer) return;
    speakPollTimer = setInterval(function() {
        if (!livetalkingReady) {
            callState.isSpeaking = false;
            return;
        }
        fetch(LIVETALKING_URL + "/is_speaking", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ sessionid: livetalkingSessionId }),
        })
        .then(function(res) { return res.json(); })
        .then(function(data) {
            callState.isSpeaking = !!(data && data.speaking);
        })
        .catch(function() {
            callState.isSpeaking = false;
        });
    }, 50);
}

function stopSpeakPolling() {
    if (speakPollTimer) {
        clearInterval(speakPollTimer);
        speakPollTimer = null;
    }
}
```

- [ ] **Step 6.2：修改 sendMessage() 添加 isSending 控制**

在 `sendMessage()` 函数中：

**函数开头**（`if (!text) return;` 之后）添加：

```javascript
    // 锁定按钮
    callState.isSending = true;
```

**函数末尾**（`currentBotText = "";` 之后）添加：

```javascript
    // LLM 回复完成，解锁 isSending
    callState.isSending = false;
```

- [ ] **Step 6.3：修改回车发送，增加按钮锁定检查**

找到回车发送监听器（约第 516-521 行），添加 `send-btn` disabled 检查：

```javascript
// 改前
document.getElementById("chat-input").addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// 改后
document.getElementById("chat-input").addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        var sendBtn = document.getElementById("send-btn");
        if (!sendBtn.disabled) {
            sendMessage();
        }
    }
});
```

- [ ] **Step 6.4：在 autoConnectLiveTalking 成功回调中启动轮询**

修改 `autoConnectLiveTalking()` 的成功回调：

```javascript
// 改前
    initLiveTalking().then(function() {
        console.log("[LiveTalking] auto connect success");
    }).catch(function(err) {

// 改后
    initLiveTalking().then(function() {
        console.log("[LiveTalking] auto connect success");
        startSpeakPolling();
    }).catch(function(err) {
```

- [ ] **Step 6.5：在 initLiveTalking() 的 connected 回调中也启动轮询**

在 `initLiveTalking()` 的 `pc.onconnectionstatechange` 中，`resolve()` 之前添加 `startSpeakPolling()`：

```javascript
// 改前
                if (pc.connectionState === "connected") {
                    livetalkingReady = true;
                    if (placeholder) placeholder.style.display = "none";
                    console.log("[LiveTalking] WebRTC connected, sessionid:", livetalkingSessionId);
                    resolve();

// 改后
                if (pc.connectionState === "connected") {
                    livetalkingReady = true;
                    if (placeholder) placeholder.style.display = "none";
                    console.log("[LiveTalking] WebRTC connected, sessionid:", livetalkingSessionId);
                    startSpeakPolling();
                    resolve();
```

在 `failed/disconnected` 分支中，`reject()` 之前添加 `stopSpeakPolling()`：

```javascript
// 改前
                } else if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
                    livetalkingReady = false;
                    reject(new Error("connection " + pc.connectionState));

// 改后
                } else if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
                    livetalkingReady = false;
                    stopSpeakPolling();
                    reject(new Error("connection " + pc.connectionState));
```

- [ ] **Step 6.6：在 closeLiveTalking() 中停止轮询**

在 `closeLiveTalking()` 函数的 `livetalkingReady = false;` 之后添加：

```javascript
    stopSpeakPolling();
    callState.isSpeaking = false;
    callState.isSending = false;
```

- [ ] **Step 6.7：添加 send 按钮 disabled 样式**

在 `style.css` 的 `.chat-input-area button:hover {}` 后面添加：

```css
.chat-input-area button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    background: #4f8cff;
}
```

- [ ] **Step 6.8：升级 script 版本号**

将 `index.html` 中 `app.js?v=10` 改为 `app.js?v=11`。

---

### Task 7：Step 2 测试验证

- [ ] **Step 7.1：启动两个服务**

同 Step 1 的启动命令。

- [ ] **Step 7.2：浏览器验证（Ctrl+Shift+R 强制刷新）**

1. 打开页面，视频自动出现
2. 输入文字点发送 → **验证**：按钮立即变灰（opacity: 0.5），不可点击
3. 等待 LLM 回复完成 + 数字人说完话 → **验证**：按钮恢复正常颜色
4. 在按钮锁定期间按 Enter → **验证**：不触发发送
5. 在按钮锁定期间点击按钮 → **验证**：无反应

- [ ] **Step 7.3：数字人不可用场景测试**

1. 关闭 LiveTalking，刷新页面
2. placeholder 显示"数字人不可用"
3. 输入文字点发送 → **验证**：按钮变灰
4. LLM 回复完成 → **验证**：按钮**立即**恢复（因为不需要等 isSpeaking）

---

### Task 8：Step 2 提交

- [ ] **Step 8.1：提交代码**

```bash
git add static/js/app.js static/css/style.css static/index.html
git commit -m "feat(phase3f-step2): smart send button lock via Proxy state + isSpeaking polling"
```

---

## Step 3：LiveTalking Chunk 处理模块

**目标**：在 LiveTalking 端新增 `chunk_processor.py`，接收完整文本后拆分为 chunk 逐段送入 avatar 处理，降低首帧延迟。前端简化为一次性发送完整文本。

**前置条件**：Step 2 测试通过。

---

### Task 9：创建 chunk_processor.py

**Files:**
- Create: `G:/JupyterProject/LiveTalking/server/chunk_processor.py`

**背景**：
- `BaseTTS.msgqueue`（Queue）存放待处理的文本消息
- `BaseAvatar.speaking`（bool）标记是否正在输出音频帧
- `WebRTCOutput.get_buffer_size()`（int）返回视频帧队列中的待播帧数

- [ ] **Step 9.1：创建 chunk_processor.py**

在 `G:/JupyterProject/LiveTalking/server/` 目录下创建 `chunk_processor.py`：

```python
###############################################################################
#  Chunk Processor — 文本分句 + chunk 合并 + 逐 chunk 送入 avatar
###############################################################################

import re
import time
import threading
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 按标点分句
# ==========================================
def split_sentences(text):
    """
    按中文标点分句。
    Args:
        text: 完整文本 (str)
    Returns:
        list[str]: 分句后的列表
    """
    parts = re.split(r'(?<=[。！？；…\n])', text)
    return [s for s in parts if s.strip()]


# ==========================================
# 合并小句子为 chunk
# ==========================================
def chunk_sentences(sentences, chunk_size=50):
    """
    将小句子按字数累积合并为较大的 chunk。
    Args:
        sentences: 小句子列表 (list[str])
        chunk_size: 每个 chunk 的目标字数 (int)
    Returns:
        list[str]: 合并后的 chunk 列表
    """
    if not sentences:
        return []

    chunks = []
    current = ""

    for s in sentences:
        current += s
        if len(current) >= chunk_size:
            chunks.append(current)
            current = ""

    if current:
        chunks.append(current)

    return chunks


# ==========================================
# 文本 chunk 队列管理器
# ==========================================
class TextChunkQueue:
    """
    管理文本 chunk 的队列和后台处理。
    接收完整文本 → 分句 → chunk 合并 → 逐 chunk 送入 avatar 处理。
    """

    def __init__(self, avatar, chunk_size=50):
        """
        Args:
            avatar: BaseAvatar 实例
            chunk_size: 每个 chunk 的目标字数 (int)
        """
        self.avatar = avatar
        self.chunk_size = chunk_size
        self.text_queue = []
        self.current_chunk = None
        self._lock = threading.Lock()
        self._processing = False

    # ------------------------------------------
    # 提交文本
    # ------------------------------------------
    def submit(self, text, datainfo=None):
        """
        接收完整文本，拆分为 chunk 入队并启动后台处理。
        Args:
            text: 完整文本 (str)
            datainfo: 附加信息 (dict)，透传给 avatar.put_msg_txt
        """
        if datainfo is None:
            datainfo = {}

        sentences = split_sentences(text)
        chunks = chunk_sentences(sentences, self.chunk_size)
        if not chunks:
            return

        logger.info(
            "[ChunkProcessor] submit: %d chars → %d sentences → %d chunks",
            len(text), len(sentences), len(chunks)
        )

        with self._lock:
            self.text_queue.extend(chunks)
            if not self._processing:
                self._processing = True
                t = threading.Thread(target=self._process_loop, daemon=True)
                t.start()

    # ------------------------------------------
    # 后台处理循环
    # ------------------------------------------
    def _process_loop(self):
        """后台线程：逐 chunk 送入 avatar，等待每个 chunk 播完再送下一个"""
        while True:
            with self._lock:
                if not self.text_queue:
                    self.current_chunk = None
                    self._processing = False
                    return
                chunk = self.text_queue.pop(0)
                self.current_chunk = chunk

            logger.debug("[ChunkProcessor] feeding chunk: %d chars", len(chunk))
            self.avatar.put_msg_txt(chunk, {})
            self._wait_chunk_done()

    # ------------------------------------------
    # 等待当前 chunk 处理完成
    # ------------------------------------------
    def _wait_chunk_done(self):
        """
        等待当前 chunk 的音视频全部播完。
        阶段 1：等 TTS msgqueue 排空（文本被 TTS 线程取走）
        阶段 2：等 avatar.speaking=False 且 buffer 清空
        超时 30s 强制退出。
        """
        timeout = 30.0
        start = time.time()

        # 阶段 1：等文本被 TTS 取走
        while time.time() - start < timeout:
            tts_qsize = 0
            if hasattr(self.avatar, 'tts') and hasattr(self.avatar.tts, 'msgqueue'):
                tts_qsize = self.avatar.tts.msgqueue.qsize()
            if tts_qsize == 0:
                break
            time.sleep(0.05)

        # 阶段 2：等 speaking 结束 + buffer 清空
        while time.time() - start < timeout:
            if not self.avatar.speaking and self._buffer_empty():
                return
            time.sleep(0.05)

        logger.warning(
            "[ChunkProcessor] _wait_chunk_done timeout (%.1fs), force skip",
            time.time() - start
        )

    # ------------------------------------------
    # 综合忙碌状态
    # ------------------------------------------
    def is_busy(self):
        """
        判断 chunk_processor 本身是否忙碌（不含 TTS/avatar 状态）。
        条件：队列不为空 或 当前有 chunk 在处理。
        """
        with self._lock:
            return bool(self.text_queue) or self.current_chunk is not None

    # ------------------------------------------
    # buffer 检查
    # ------------------------------------------
    def _buffer_empty(self):
        """
        检查输出 buffer 是否为空。
        通过 avatar.output.get_buffer_size() 获取视频帧队列大小。
        """
        if hasattr(self.avatar, 'output') and hasattr(self.avatar.output, 'get_buffer_size'):
            return self.avatar.output.get_buffer_size() == 0
        return True

    # ------------------------------------------
    # 清理
    # ------------------------------------------
    def flush(self):
        """清空队列，停止处理"""
        with self._lock:
            self.text_queue.clear()
            self.current_chunk = None
            self._processing = False
```

- [ ] **Step 9.2：验证文件无语法错误**

```bash
cd G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from server.chunk_processor import TextChunkQueue, split_sentences, chunk_sentences; print('OK')"
```

预期输出：`OK`

---

### Task 10：集成 chunk_processor 到 base_avatar.py

**Files:**
- Modify: `G:/JupyterProject/LiveTalking/avatars/base_avatar.py`

- [ ] **Step 10.1：在 `__init__` 末尾创建 chunk_processor**

在 `BaseAvatar.__init__` 的最后（约第 127 行，`else: logger.error(...)` 之后）添加：

```python
        # Chunk processor（Phase 3f）
        from server.chunk_processor import TextChunkQueue
        self.chunk_processor = TextChunkQueue(self, chunk_size=50)
```

- [ ] **Step 10.2：重写 put_msg_txt 委托给 chunk_processor**

找到 `put_msg_txt` 方法（约第 129 行），替换为：

```python
    def put_msg_txt(self, msg, datainfo:dict={}):
        """
        接收文本，委托给 chunk_processor 处理。
        chunk_processor 会分句 → 合并 chunk → 逐 chunk 调用 _feed_text_to_tts。
        """
        self.last_active_time = time.time()
        self.chunk_processor.submit(msg, datainfo)
```

- [ ] **Step 10.3：添加 _feed_text_to_tts 方法（原 put_msg_txt 逻辑）**

在 `put_msg_txt` 方法之后添加：

```python
    def _feed_text_to_tts(self, msg, datainfo:dict={}):
        """
        将文本直接送入 TTS 模块（chunk_processor 内部调用）。
        """
        if hasattr(self, 'tts'):
            self.tts.put_msg_txt(msg, datainfo)
```

- [ ] **Step 10.4：修改 is_speaking 为综合状态**

找到 `is_speaking` 方法（约第 226 行），替换为：

```python
    def is_speaking(self) -> bool:
        """
        综合判断是否忙碌（供 /is_speaking API 使用）。
        任一条件为真 → busy:
        1. chunk_processor 有排队/处理中的 chunk
        2. TTS msgqueue 有未处理的文本
        3. avatar.speaking 为 True（正在输出音频帧）
        4. output buffer 有未播放的视频帧
        """
        # 条件 1：chunk_processor
        if self.chunk_processor.is_busy():
            return True
        # 条件 2：TTS 队列
        if hasattr(self, 'tts') and hasattr(self.tts, 'msgqueue'):
            if self.tts.msgqueue.qsize() > 0:
                return True
        # 条件 3+4：speaking 或 buffer
        if self.speaking:
            return True
        if hasattr(self, 'output') and hasattr(self.output, 'get_buffer_size'):
            if self.output.get_buffer_size() > 0:
                return True
        return False
```

- [ ] **Step 10.5：修改 flush_talk 同步清理 chunk_processor**

找到 `flush_talk` 方法（约第 216 行），在最前面添加 chunk_processor.flush()：

```python
    def flush_talk(self):
        # 清理 chunk_processor 队列
        if hasattr(self, 'chunk_processor'):
            self.chunk_processor.flush()
        if hasattr(self, 'tts') and hasattr(self.tts, 'flush_talk'):
            self.tts.flush_talk()
        if hasattr(self, 'asr') and hasattr(self.asr, 'flush_talk'):
            self.asr.flush_talk()
        self.custom_audiotype = 0
```

- [ ] **Step 10.6：修改 reset_for_reuse 同步清理 chunk_processor**

找到 `reset_for_reuse` 方法（约第 134 行），在 `self.speaking = False` 之后添加：

```python
        # 清理 chunk_processor
        if hasattr(self, 'chunk_processor'):
            self.chunk_processor.flush()
```

- [ ] **Step 10.7：修改 chunk_processor._process_loop 中的调用**

回到 `chunk_processor.py`，将 `_process_loop` 中的 `self.avatar.put_msg_txt(chunk, {})` 改为 `self.avatar._feed_text_to_tts(chunk, {})`（避免递归调用 chunk_processor.submit）。

```python
# 改前
            self.avatar.put_msg_txt(chunk, {})
# 改后
            self.avatar._feed_text_to_tts(chunk, {})
```

- [ ] **Step 10.8：验证 LiveTalking 无导入错误**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from avatars.base_avatar import BaseAvatar; print('OK')"
```

预期输出：`OK`

---

### Task 11：简化前端 sendToLiveTalking

**Files:**
- Modify: `static/js/app.js`
- Modify: `static/index.html`

**目标**：移除前端的 `pendingText` 缓冲逻辑，改为在 `handleSSEEvent` 的 `done` 事件中收集完整文本后一次性发送。

- [ ] **Step 11.1：添加 botTextBuffer 变量**

在 `app.js` 的 `currentBotMsg` / `currentBotText` 变量附近（约第 360 行），添加：

```javascript
let botTextBuffer = "";
```

- [ ] **Step 11.2：修改 handleSSEEvent 的 case "text" 分支**

在 `case "text":` 的 `scrollToBottom();` 之后添加：

```javascript
            botTextBuffer += data.content;
```

- [ ] **Step 11.3：修改 handleSSEEvent 的 case "done" 分支**

在 `case "done":` 的 `cursor.remove()` 之后、`break;` 之前，添加发送逻辑：

```javascript
            // 将完整文本一次性发送给 LiveTalking
            if (botTextBuffer) {
                sendToLiveTalking(botTextBuffer);
                botTextBuffer = "";
            }
```

- [ ] **Step 11.4：在 sendMessage() 开头重置 botTextBuffer**

在 `sendMessage()` 的 `callState.isSending = true;` 之后添加：

```javascript
    botTextBuffer = "";
```

- [ ] **Step 11.5：升级 script 版本号**

将 `index.html` 中 `app.js?v=11` 改为 `app.js?v=12`。

---

### Task 12：chunk_processor 单元测试

**Files:**
- Create: `G:/JupyterProject/LiveTalking/tests/test_chunk_processor.py`

- [ ] **Step 12.1：创建单元测试**

在 `G:/JupyterProject/LiveTalking/tests/` 目录下创建 `test_chunk_processor.py`：

```python
###############################################################################
#  chunk_processor 单元测试
###############################################################################

import sys
import os
import pytest

# 添加 LiveTalking 根目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.chunk_processor import split_sentences, chunk_sentences, TextChunkQueue


# ==========================================
# split_sentences 测试
# ==========================================
class TestSplitSentences:

    def test_basic_split(self):
        text = "你好。我是Lisa。"
        result = split_sentences(text)
        assert result == ["你好。", "我是Lisa。"]

    def test_multiple_punctuation(self):
        text = "真的吗？太好了！再见。"
        result = split_sentences(text)
        assert result == ["真的吗？", "太好了！", "再见。"]

    def test_no_punctuation(self):
        text = "你好世界"
        result = split_sentences(text)
        assert result == ["你好世界"]

    def test_empty_text(self):
        result = split_sentences("")
        assert result == []

    def test_newline_split(self):
        text = "第一行\n第二行\n"
        result = split_sentences(text)
        assert result == ["第一行\n", "第二行\n"]


# ==========================================
# chunk_sentences 测试
# ==========================================
class TestChunkSentences:

    def test_basic_chunk(self):
        sentences = ["你好。", "我是Lisa。", "很高兴认识你。"]
        result = chunk_sentences(sentences, chunk_size=10)
        assert len(result) >= 1
        assert "".join(result) == "".join(sentences)

    def test_small_chunk_size(self):
        sentences = ["短。", "也短。", "还是短。"]
        result = chunk_sentences(sentences, chunk_size=3)
        assert len(result) >= 2

    def test_large_chunk_size(self):
        sentences = ["一句话。"]
        result = chunk_sentences(sentences, chunk_size=100)
        assert result == ["一句话。"]

    def test_empty_list(self):
        result = chunk_sentences([], chunk_size=50)
        assert result == []

    def test_content_preserved(self):
        sentences = ["A" * 20, "B" * 20, "C" * 20]
        result = chunk_sentences(sentences, chunk_size=30)
        assert "".join(result) == "A" * 20 + "B" * 20 + "C" * 20


# ==========================================
# TextChunkQueue 测试
# ==========================================
class TestTextChunkQueue:

    def _make_mock_avatar(self):
        """创建 mock avatar"""
        from unittest.mock import MagicMock
        avatar = MagicMock()
        avatar.speaking = False
        avatar.tts = MagicMock()
        avatar.tts.msgqueue = MagicMock()
        avatar.tts.msgqueue.qsize.return_value = 0
        avatar.output = MagicMock()
        avatar.output.get_buffer_size.return_value = 0
        return avatar

    def test_submit_creates_chunks(self):
        avatar = self._make_mock_avatar()
        cq = TextChunkQueue(avatar, chunk_size=10)
        cq.submit("你好。我是Lisa。很高兴认识你。今天天气不错。")
        # 等待后台线程启动
        import time
        time.sleep(0.3)
        # 应该调用了 avatar._feed_text_to_tts
        assert avatar._feed_text_to_tts.called

    def test_is_busy_empty_queue(self):
        avatar = self._make_mock_avatar()
        cq = TextChunkQueue(avatar)
        assert cq.is_busy() == False

    def test_is_busy_with_queue(self):
        avatar = self._make_mock_avatar()
        cq = TextChunkQueue(avatar)
        cq.text_queue = ["chunk1"]
        assert cq.is_busy() == True

    def test_flush_clears_queue(self):
        avatar = self._make_mock_avatar()
        cq = TextChunkQueue(avatar)
        cq.text_queue = ["chunk1", "chunk2"]
        cq.current_chunk = "chunk0"
        cq.flush()
        assert cq.text_queue == []
        assert cq.current_chunk is None
        assert cq._processing == False
```

- [ ] **Step 12.2：运行单元测试**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -m pytest tests/test_chunk_processor.py -v
```

预期：全部 PASS

---

### Task 13：Step 3 集成测试

- [ ] **Step 13.1：启动 LiveTalking 服务**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe app.py --model musetalk --avatar_id musetalk_avatar1 --transport webrtc --listenport 8010 --pool_size 2
```

- [ ] **Step 13.2：启动 Lisa 主服务**

```bash
cd g:\JupyterProject\20260725_Agent_AI可视化机器人
conda run -n py310 python server.py
```

- [ ] **Step 13.3：浏览器集成验证（Ctrl+Shift+R）**

1. 打开页面，视频自动出现
2. 发送短消息（如"你好"）→ **验证**：数字人正常说话，说完后按钮解锁
3. 发送长消息（>100字）→ **验证**：数字人分段说话，chunk 衔接无明显卡顿
4. 发送第二条消息（在第一条说完后）→ **验证**：第二条正常处理

- [ ] **Step 13.4：检查 LiveTalking 日志**

确认日志中出现 `[ChunkProcessor] submit: N chars → M sentences → K chunks`，验证 chunk 拆分正常。

---

### Task 14：Step 3 提交

- [ ] **Step 14.1：提交代码**

```bash
# LiveTalking 改动
cd G:\JupyterProject\LiveTalking
git add server/chunk_processor.py avatars/base_avatar.py tests/test_chunk_processor.py
git commit -m "feat(phase3f-step3): add chunk_processor for text splitting and sequential avatar feeding"

# Lisa 前端改动
cd g:\JupyterProject\20260725_Agent_AI可视化机器人
git add static/js/app.js static/index.html
git commit -m "feat(phase3f-step3): simplify frontend, send full text to LiveTalking chunk_processor"
```

---

## 完成标准

所有三个 Step 测试通过后，以下功能应正常工作：

1. **自动连接**：页面加载自动建立 WebRTC，失败时显示提示
2. **Send 锁定**：LLM 处理中或数字人说话时按钮禁用，说完自动解锁
3. **Chunk 流水线**：长文本自动分 chunk 处理，降低首帧延迟
4. **无按钮**：开始/结束按钮已移除
