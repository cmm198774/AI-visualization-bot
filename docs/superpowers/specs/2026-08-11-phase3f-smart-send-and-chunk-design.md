# Phase 3f: Send 按钮智能锁定 + Chunk 流水线 + 自动连接

## 日期：2026-08-11

## 概述

三个改动：
1. 取消开始/结束按钮，网页加载时自动连接 LiveTalking
2. Send 按钮根据 `isSending` + `isSpeaking` 自动锁定/解锁
3. LiveTalking 端新增 chunk 处理模块，降低首帧延迟

分三步实施，每步完成后测试通过再进入下一步。

---

## 改动一：自动连接 + 失败跳过

### 目标

去掉手动开始/结束按钮。页面加载时自动建立 WebRTC 连接，连接失败时显示提示并跳过数字人（文字聊天不受影响）。

### 前端改动

#### index.html

- 移除 `.avatar-controls` 区域（开始/结束按钮 + 状态标签）
- avatar 区域只保留 `<video>` + placeholder

#### app.js

```javascript
// 页面加载时自动连接
window.addEventListener("DOMContentLoaded", function() {
    autoConnectLiveTalking();
});

async function autoConnectLiveTalking() {
    // 复用现有 initLiveTalking() 的 WebRTC 逻辑
    // 成功后：livetalkingReady = true，placeholder 隐藏
    // 失败后：livetalkingReady = false，placeholder 显示 "数字人不可用"
}

// sendToLiveTalking() 中：
function sendToLiveTalking() {
    if (!livetalkingReady) return;  // 静默跳过
    // ... 发送逻辑
}
```

#### style.css

- 移除 `.avatar-controls`、`.btn-start`、`.btn-stop`、`.avatar-status` 样式
- placeholder 失败态样式：`.avatar-placeholder.unavailable`

### 测试验证

- [ ] 页面加载 → 视频自动出现
- [ ] LiveTalking 未启动 → placeholder 显示"数字人不可用"
- [ ] 数字人不可用时 → 文字聊天正常（SSE 文字正常显示）
- [ ] 页面关闭 → WebRTC 连接自动关闭（beforeunload）

---

## 改动二：Send 按钮智能锁定

### 目标

防止用户在 LLM 处理中或数字人说话时插话。按钮状态通过 Proxy 自动响应变量变化。

### 状态变量

```javascript
const callState = new Proxy(
    { isSending: false, isSpeaking: false },
    {
        set(target, prop, value) {
            target[prop] = value;
            updateSendButton();
            return true;
        }
    }
);
```

### 锁定规则

| LiveTalking 状态 | 锁定条件 | 解锁条件 |
|---|---|---|
| 可用 (`livetalkingReady=true`) | `isSending \|\| isSpeaking` | `!isSending && !isSpeaking` |
| 不可用 (`livetalkingReady=false`) | `isSending` | `!isSending` |

### isSpeaking 轮询

```javascript
let speakPollTimer = null;

function startSpeakPolling() {
    if (speakPollTimer) return;
    speakPollTimer = setInterval(async function() {
        if (!livetalkingReady) {
            callState.isSpeaking = false;
            return;
        }
        try {
            const res = await fetch(LIVETALKING_URL + "/is_speaking", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ sessionid: livetalkingSessionId }),
            });
            const data = await res.json();
            callState.isSpeaking = !!data.speaking;
        } catch (e) {
            callState.isSpeaking = false;
        }
    }, 50);
}

function stopSpeakPolling() {
    if (speakPollTimer) {
        clearInterval(speakPollTimer);
        speakPollTimer = null;
    }
}
```

### isSending 管理

```javascript
async function sendMessage() {
    // ...
    callState.isSending = true;

    // SSE 流处理...
    // done 事件到达时：
    callState.isSending = false;
    // 如果 LiveTalking 可用，等 isSpeaking 变 false 后按钮才解锁
}
```

### 按钮样式

```css
#send-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}
```

### 测试验证

- [ ] 点发送 → 按钮变灰禁用
- [ ] LLM 回复完成 + 数字人说完 → 按钮恢复
- [ ] 数字人不可用时 → LLM 回复完成即解锁
- [ ] 快速连点 → 不触发第二次发送
- [ ] Enter 键发送 → 同样锁定

---

## 改动三：LiveTalking Chunk 处理模块

### 目标

降低首帧延迟：LLM 完整文本到达后，LiveTalking 内部拆成 chunk 逐段处理，第一段先出画面。

### 架构

```
前端 POST /human { text: "完整文本", type: "echo" }
                    │
                    ▼
        LiveTalking: chunk_processor
        1. splitSentences(text) → 按标点分句
        2. chunkSentences(sentences, 50) → 合并为 ~50字/chunk
        3. 入 text_queue
        4. 后台线程逐 chunk → avatar.put_msg_txt(chunk)
                    │
                    ▼
        avatar 推理 → 视频帧入 WebRTC buffer
                    │
                    ▼
        WebRTC 推送给前端
```

### 新建文件：`server/chunk_processor.py`

```python
class TextChunkQueue:
    """
    文本 chunk 队列管理器。
    接收完整文本 → 分句 → chunk 合并 → 逐 chunk 送入 avatar 处理。
    """

    def __init__(self, avatar, chunk_size=50):
        self.avatar = avatar
        self.chunk_size = chunk_size
        self.text_queue = []          # 待处理 chunk 列表
        self.current_chunk = None     # 正在处理的 chunk
        self._lock = threading.Lock()
        self._processing = False

    def submit(self, text):
        """接收完整文本，拆分为 chunk 入队"""
        sentences = self._split_sentences(text)
        chunks = self._chunk_sentences(sentences, self.chunk_size)
        with self._lock:
            self.text_queue.extend(chunks)
        if not self._processing:
            self._processing = True
            threading.Thread(target=self._process_loop, daemon=True).start()

    def _process_loop(self):
        """后台线程：逐 chunk 送入 avatar"""
        while True:
            with self._lock:
                if not self.text_queue:
                    self.current_chunk = None
                    self._processing = False
                    return
                chunk = self.text_queue.pop(0)
                self.current_chunk = chunk
            # 送入 avatar 处理
            self.avatar.put_msg_txt(chunk, {})
            # 等当前 chunk 处理完（音频推理结束、buffer 播完）
            self._wait_chunk_done()

    def _wait_chunk_done(self):
        """
        等待当前 chunk 的视频/音频 buffer 播完。
        轮询间隔 50ms，超时 30s 强制退出（防止死锁）。
        """
        import time
        timeout = 30.0
        start = time.time()
        while time.time() - start < timeout:
            # 条件 A：avatar.speaking 为 False（音频推理结束）
            # 条件 B：player buffer 为空（视频帧全部播完）
            if not self.avatar.speaking and self._buffer_empty():
                return
            time.sleep(0.05)
        # 超时：记录日志，强制跳过
        import logging
        logging.getLogger(__name__).warning(
            "chunk_processor: _wait_chunk_done 超时，强制跳过"
        )

    def is_busy(self) -> bool:
        """
        综合判断是否忙碌。
        三个条件任一为真 → busy:
        1. text_queue 不为空
        2. current_chunk 不为 None
        3. 视频/音频 buffer 还有未播完的帧
        """
        with self._lock:
            if self.text_queue:
                return True
            if self.current_chunk is not None:
                return True
        return not self._buffer_empty()

    def _buffer_empty(self) -> bool:
        """
        检查视频/音频 buffer 是否全部播完。
        两个子条件同时满足才算空：
        - avatar.speaking == False（无活跃音频推理）
        - player.get_buffer_size() == 0（视频帧队列清空）
        """
        return not self.avatar.speaking and self.avatar.player.get_buffer_size() == 0

    @staticmethod
    def _split_sentences(text):
        """按标点分句"""
        import re
        parts = re.split(r'(?<=[。！？；…\n])', text)
        return [s for s in parts if s.strip()]

    @staticmethod
    def _chunk_sentences(sentences, chunk_size):
        """合并小句子为 ~chunk_size 字的 chunk"""
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
```

### 改动文件

| 文件 | 改动 |
|------|------|
| `server/chunk_processor.py` | **新建** — TextChunkQueue |
| `avatars/base_avatar.py` | 新增 `chunk_processor` 属性；`put_msg_txt` 改为调用 chunk_processor.submit()；新增 `is_busy()` 方法 |
| `server/routes.py` | `/is_speaking` 改为调用 `avatar.is_busy()` |

### 前端 app.js 变化

- 移除 `pendingText` + `flushPendingText()` 缓冲逻辑
- `sendToLiveTalking()` 简化为：收到完整文本 → 一次 POST `/human`
- 轮询 `/is_speaking`（已有，改动二加入）

### 测试验证

- [ ] 短文本（<50字）→ 正常处理，不拆分
- [ ] 长文本（200字）→ 拆成 ~4 个 chunk，逐段出画面
- [ ] `/is_speaking` → chunk 处理中返回 true，全部播完返回 false
- [ ] 连续发两段文本 → 第二段排队等待，不中断第一段
- [ ] 视频帧率稳定，chunk 衔接无明显卡顿

---

## 整体文件改动清单

| 文件 | 改动类型 |
|------|----------|
| `static/index.html` | 移除按钮区域 |
| `static/js/app.js` | 自动连接 + Proxy 状态 + 轮询 + 移除按钮逻辑 + 简化 sendToLiveTalking |
| `static/css/style.css` | 移除按钮样式 + send 按钮 disabled 态 |
| `LiveTalking/server/chunk_processor.py` | **新建** |
| `LiveTalking/avatars/base_avatar.py` | 新增 chunk_processor + is_busy() |
| `LiveTalking/server/routes.py` | `/is_speaking` 改调 is_busy() |

## 依赖关系

```
改动一（自动连接）→ 改动二（send 锁定）→ 改动三（chunk 处理）
```

改动一和改动二只改前端，改动三改 LiveTalking 后端。每步独立可测试。
