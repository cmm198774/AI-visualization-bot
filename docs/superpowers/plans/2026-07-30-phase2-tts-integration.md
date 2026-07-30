# Phase 2: TTS 语音集成 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate CosyVoice2 local TTS into the Lisa chatbot so AI replies are spoken aloud sentence-by-sentence alongside text display.

**Architecture:** A standalone TTS service (tts_server.py, port 9233) wraps CosyVoice2-0.5B behind a simple HTTP API. The main server (server.py, port 8000) calls it per-sentence after LLM response, streaming audio as base64 SSE events to the frontend which plays them through a queue. TTS failure degrades silently to text-only.

**Tech Stack:** CosyVoice2-0.5B (PyTorch, GPU), FastAPI, aiohttp, Web Audio API (HTML5 Audio), base64 SSE transport

**Spec:** `docs/superpowers/specs/2026-07-30-phase2-tts-integration-design.md`

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Create | `sentence_splitter.py` | Chinese text sentence splitting by punctuation |
| Create | `tts_server.py` | Standalone TTS service wrapping CosyVoice2 |
| Create | `test_sentence_splitter.py` | Unit tests for sentence splitter |
| Modify | `config.py:60-67` | Add TTS_SERVER_URL, TTS_SPEAKER, TTS_TIMEOUT |
| Modify | `server.py:1-29,177-345` | Add TTS client function + rewrite text output loop to sentence-by-sentence |
| Modify | `static/js/app.js:104-255` | Add audio queue, playback, TTS toggle |
| Modify | `static/index.html:47-49` | Add TTS toggle button |
| Modify | `requirements.txt` | Add aiohttp |
| Modify | `.gitignore` | Add CosyVoice/ |
| Modify | `.env.example` | Add TTS config section |

---

### Task 1: Sentence Splitter

**Files:**
- Create: `sentence_splitter.py`
- Create: `test_sentence_splitter.py`

- [ ] **Step 1: Write failing tests**

Create `test_sentence_splitter.py`:

```python
"""
中文分句工具测试
"""
from sentence_splitter import split_sentences


def test_basic_split():
    """基本分句：按中文标点分隔"""
    result = split_sentences("你好呀老板～今天天气不错呢！")
    assert result == ["你好呀老板～", "今天天气不错呢！"]


def test_multiple_punctuation():
    """多个句子"""
    result = split_sentences("一句。两句。三句。")
    assert result == ["一句。", "两句。", "三句。"]


def test_no_punctuation():
    """没有标点 → 整体作为一句"""
    result = split_sentences("没有标点的文本")
    assert result == ["没有标点的文本"]


def test_empty_string():
    """空字符串 → 空列表"""
    result = split_sentences("")
    assert result == []


def test_only_punctuation():
    """只有标点 → 作为一句"""
    result = split_sentences("。。。")
    assert result == ["。。。"]


def test_mixed_content():
    """中英文混合"""
    result = split_sentences("混合,英文hello。中文！")
    assert result == ["混合,英文hello。", "中文！"]


def test_trailing_no_punctuation():
    """尾部无标点也成句"""
    result = split_sentences("第一句。第二句没标点")
    assert result == ["第一句。", "第二句没标点"]


def test_whitespace_only():
    """纯空白 → 空列表"""
    result = split_sentences("   ")
    assert result == []


def test_all_separators():
    """所有分隔符都生效"""
    result = split_sentences("a。b！c？d～e；f…g，h、i")
    assert result == ["a。", "b！", "c？", "d～", "e；", "f…", "g，", "h、", "i"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `conda run -n py310 python -m pytest test_sentence_splitter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sentence_splitter'`

- [ ] **Step 3: Implement sentence_splitter.py**

Create `sentence_splitter.py`:

```python
"""
中文分句工具模块
按中文标点将文本拆分为句子列表。
"""
import re


# ==========================================
# 分句分隔符
# ==========================================
SENTENCE_SEPARATORS = re.compile(r"([。！？～；…，、])")


# ==========================================
# 分句函数
# ==========================================
def split_sentences(text: str) -> list:
    """
    按中文标点分句，保留标点在句尾。

    Args:
        text: 输入文本 (str)

    Returns:
        list[str]: 句子列表

    Rules:
        - 分隔符: 。！？～；…，、
        - 无标点的尾部文本也作为一个句子
        - 空句子和纯空白句子过滤掉
    """
    if not text or not text.strip():
        return []

    # 用正则按分隔符拆分，保留分隔符
    parts = SENTENCE_SEPARATORS.split(text)

    # 重新组合：把分隔符粘回前面的文本
    sentences = []
    current = ""
    for part in parts:
        current += part
        if SENTENCE_SEPARATORS.match(part):
            # 当前 part 是分隔符，current 构成完整句子
            if current.strip():
                sentences.append(current)
            current = ""

    # 处理尾部没有标点的剩余文本
    if current.strip():
        sentences.append(current)

    return sentences
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `conda run -n py310 python -m pytest test_sentence_splitter.py -v`
Expected: All 9 tests PASS

- [ ] **Step 5: Commit**

```bash
git add sentence_splitter.py test_sentence_splitter.py
git commit -m "feat: add sentence splitter for TTS sentence-by-sentence output"
```

---

### Task 2: Config Updates

**Files:**
- Modify: `config.py:60-67`
- Modify: `.env.example:34-42`
- Modify: `requirements.txt:22-23`

- [ ] **Step 1: Add TTS config to config.py**

Append to `config.py` (after line 66):

```python


# ==========================================
# TTS 服务配置
# ==========================================
TTS_SERVER_URL = os.getenv("TTS_SERVER_URL", "http://127.0.0.1:9233/tts")
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "中文女")
TTS_TIMEOUT = int(os.getenv("TTS_TIMEOUT", "10"))
```

- [ ] **Step 2: Add TTS config to .env.example**

Append to `.env.example`:

```

# ==========================================
# TTS 服务配置
# ==========================================
TTS_SERVER_URL=http://127.0.0.1:9233/tts
TTS_SPEAKER=中文女
TTS_TIMEOUT=10
```

- [ ] **Step 3: Add aiohttp to requirements.txt**

Append to `requirements.txt`:

```

# TTS 语音合成（HTTP 客户端）
aiohttp==3.9.5
```

- [ ] **Step 4: Verify config loads correctly**

Run: `conda run -n py310 python -c "from config import TTS_SERVER_URL, TTS_SPEAKER, TTS_TIMEOUT; print(TTS_SERVER_URL, TTS_SPEAKER, TTS_TIMEOUT)"`
Expected: `http://127.0.0.1:9233/tts 中文女 10`

- [ ] **Step 5: Commit**

```bash
git add config.py .env.example requirements.txt
git commit -m "feat: add TTS config (server URL, speaker, timeout)"
```

---

### Task 3: TTS Client Function

**Files:**
- Modify: `server.py:1-29` (imports)
- Modify: `server.py:174-345` (_event_stream — will be done in Task 5)

This task creates the TTS HTTP client function that server.py will call. We'll put it in a new file `tts_client.py` to keep server.py focused.

- [ ] **Step 1: Create tts_client.py**

Create `tts_client.py`:

```python
"""
TTS 客户端模块
调用独立 TTS 服务进行语音合成。
"""
import base64

import aiohttp

from config import TTS_SERVER_URL, TTS_SPEAKER, TTS_TIMEOUT
from sys_logger import setup_global_logger


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()


# ==========================================
# 调用 TTS 服务
# ==========================================
async def synthesize_speech(text: str) -> bytes:
    """
    调用 TTS 服务，将文本合成为语音。

    Args:
        text: 要合成的文本 (str)

    Returns:
        bytes: WAV 格式音频数据

    Raises:
        Exception: TTS 服务不可用、超时或返回错误时抛出
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TTS_SERVER_URL,
                json={"text": text, "speaker": TTS_SPEAKER},
                timeout=aiohttp.ClientTimeout(total=TTS_TIMEOUT),
            ) as resp:
                if resp.status == 200:
                    audio_bytes = await resp.read()
                    logger.debug(f"TTS 合成完成: text={text[:20]}..., size={len(audio_bytes)} bytes")
                    return audio_bytes
                raise Exception(f"TTS 服务返回状态码 {resp.status}")
    except aiohttp.ClientError as e:
        logger.warning(f"TTS 服务连接失败: {e}")
        raise
    except TimeoutError:
        logger.warning(f"TTS 服务超时 ({TTS_TIMEOUT}s): text={text[:20]}...")
        raise
    except Exception as e:
        logger.warning(f"TTS 合成失败: {e}")
        raise


# ==========================================
# 文本转 base64 音频
# ==========================================
async def synthesize_speech_b64(text: str) -> str:
    """
    调用 TTS 服务，返回 base64 编码的音频数据。

    Args:
        text: 要合成的文本 (str)

    Returns:
        str: base64 编码的 WAV 音频字符串
    """
    audio_bytes = await synthesize_speech(text)
    return base64.b64encode(audio_bytes).decode("utf-8")
```

- [ ] **Step 2: Verify import works**

Run: `conda run -n py310 python -c "from tts_client import synthesize_speech, synthesize_speech_b64; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tts_client.py
git commit -m "feat: add TTS client with aiohttp async HTTP calls"
```

---

### Task 4: TTS Service (tts_server.py)

**Files:**
- Create: `tts_server.py`

**Prerequisites:** CosyVoice2 must be cloned and model downloaded.

- [ ] **Step 0: Setup CosyVoice2 (manual, one-time)**

Clone the official repo and download the model:

```bash
# 克隆 CosyVoice 官方仓库
git clone https://github.com/QwenAudio/CosyVoice.git

# 按官方文档安装依赖（CosyVoice/INSTALL.md）
# 下载 CosyVoice2-0.5B 模型到 CosyVoice/pretrained_models/CosyVoice2-0.5B/

# 确认目录结构
ls CosyVoice/pretrained_models/CosyVoice2-0.5B/
# 应包含: flow.model, flow.yaml, llm.model, llm.yaml, ...
```

- [ ] **Step 1: Create tts_server.py**

Create `tts_server.py`:

```python
"""
TTS 独立服务模块
封装 CosyVoice2 模型，提供 HTTP API 进行语音合成。
启动方式: python tts_server.py
端口: 9233
"""
import io
import os
import sys
import time
import wave

import numpy as np
import soundfile as sf
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn

from sys_logger import setup_global_logger


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()

# 将 CosyVoice 项目目录加入 Python path
COSYVOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CosyVoice")
if COSYVOICE_DIR not in sys.path:
    sys.path.insert(0, COSYVOICE_DIR)


# ==========================================
# 全局状态
# ==========================================
model = None
model_status = "loading"


# ==========================================
# 加载模型
# ==========================================
def load_model():
    """加载 CosyVoice2 模型到 GPU"""
    global model, model_status

    model_path = os.path.join(COSYVOICE_DIR, "pretrained_models", "CosyVoice2-0.5B")
    logger.info(f"加载 CosyVoice2 模型: {model_path}")

    t0 = time.time()
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice2
        model = CosyVoice2(model_path)
        elapsed = time.time() - t0
        model_status = "ready"
        logger.info(f"CosyVoice2 模型加载完成: 耗时 {elapsed:.1f}s")
    except Exception as e:
        model_status = "error"
        logger.error(f"CosyVoice2 模型加载失败: {e}")


# ==========================================
# numpy 音频转 WAV bytes
# ==========================================
def numpy_to_wav(audio_np: np.ndarray, sample_rate: int = 22050) -> bytes:
    """
    将 numpy 音频数组转为 WAV 格式的 bytes。

    Args:
        audio_np: numpy 音频数组 (np.ndarray)，float32 范围 [-1, 1]
        sample_rate: 采样率 (int)

    Returns:
        bytes: WAV 格式的音频数据
    """
    buf = io.BytesIO()
    sf.write(buf, audio_np, sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


# ==========================================
# Pydantic 请求模型
# ==========================================
class TTSRequest(BaseModel):
    """TTS 请求参数"""
    text: str
    speaker: str = "中文女"


# ==========================================
# FastAPI 应用
# ==========================================
app = FastAPI(title="Lisa TTS Service")


# ==========================================
# 健康检查
# ==========================================
@app.get("/health")
async def health():
    """健康检查端点"""
    return {"status": model_status}


# ==========================================
# TTS 合成端点
# ==========================================
@app.post("/tts")
async def tts(request: TTSRequest):
    """
    语音合成端点。
    将文本合成为 WAV 音频并返回。
    """
    if model_status != "ready" or model is None:
        return Response(
            content='{"error": "模型未就绪"}',
            media_type="application/json",
            status_code=503,
        )

    if not request.text or not request.text.strip():
        return Response(
            content='{"error": "文本不能为空"}',
            media_type="application/json",
            status_code=400,
        )

    t0 = time.time()
    try:
        logger.info(f"TTS 合成请求: text={request.text[:30]}..., speaker={request.speaker}")

        # 调用 CosyVoice2 推理
        audio_chunks = []
        for chunk in model.inference_sft(request.text, request.speaker):
            audio_chunks.append(chunk["tts_speech"].numpy().flatten())

        if not audio_chunks:
            return Response(
                content='{"error": "合成失败：无音频输出"}',
                media_type="application/json",
                status_code=500,
            )

        # 拼接音频块
        audio_np = np.concatenate(audio_chunks)

        # 转为 WAV
        wav_bytes = numpy_to_wav(audio_np)

        elapsed = time.time() - t0
        logger.info(f"TTS 合成完成: duration={elapsed:.1f}s, size={len(wav_bytes)} bytes")

        return Response(content=wav_bytes, media_type="audio/wav")

    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"TTS 合成异常 ({elapsed:.1f}s): {e}")
        return Response(
            content=f'{{"error": "合成异常: {str(e)[:100]}"}}',
            media_type="application/json",
            status_code=500,
        )


# ==========================================
# 启动入口
# ==========================================
if __name__ == "__main__":
    # 启动时加载模型
    load_model()

    # 启动 FastAPI 服务
    uvicorn.run(app, host="127.0.0.1", port=9233)
```

- [ ] **Step 2: Add CosyVoice/ to .gitignore**

Append to `.gitignore`:

```

# ==========================================
# CosyVoice2 模型（体积大，不上传）
# ==========================================
CosyVoice/
```

- [ ] **Step 3: Add soundfile + numpy to requirements.txt**

Append to `requirements.txt`:

```

# TTS 语音合成（服务端）
numpy
soundfile
```

- [ ] **Step 4: Start and test TTS service manually**

```bash
# 终端 1：启动 TTS 服务
conda run -n py310 python tts_server.py
# 等待 "CosyVoice2 模型加载完成" 日志出现

# 终端 2：测试健康检查
curl http://127.0.0.1:9233/health
# 预期: {"status":"ready"}

# 测试语音合成
curl -X POST http://127.0.0.1:9233/tts -H "Content-Type: application/json" -d "{\"text\": \"你好，我是Lisa\", \"speaker\": \"中文女\"}" --output test_tts_output.wav
# 预期: 生成 test_tts_output.wav，可播放

# 测试空文本
curl -X POST http://127.0.0.1:9233/tts -H "Content-Type: application/json" -d "{\"text\": \"\", \"speaker\": \"中文女\"}"
# 预期: {"error":"文本不能为空"}
```

- [ ] **Step 5: Commit**

```bash
git add tts_server.py .gitignore requirements.txt
git commit -m "feat: add standalone TTS service wrapping CosyVoice2"
```

---

### Task 5: Integrate TTS into _event_stream

**Files:**
- Modify: `server.py:1-29` (add imports)
- Modify: `server.py:306-329` (replace single text yield with sentence loop)

- [ ] **Step 1: Add imports to server.py**

At the top of `server.py`, add after line 28:

```python
from sentence_splitter import split_sentences
from tts_client import synthesize_speech_b64
```

- [ ] **Step 2: Replace text output section in _event_stream**

Replace lines 306-329 (from `# 获取 ainvoke 结果` to `yield "data: " + mood_data + "\n\n"`) with:

```python
        # 获取 ainvoke 结果
        result = await agent_task

        # 提取情绪标签
        mood = result.get("mood", "default")

        # 提取最终文本
        messages = result.get("messages", [])
        final_message = None
        for msg in reversed(messages):
            if msg.__class__.__name__ == "AIMessage" and msg.content:
                final_message = msg.content
                break

        if not final_message:
            final_message = "抱歉，我暂时无法回复。"

        # 分句
        sentences = split_sentences(final_message)
        if not sentences:
            sentences = [final_message]

        # 逐句发送文字 + 音频
        for sentence in sentences:
            # 1. 先 yield 文字（前端立即显示）
            text_data = json.dumps({"type": "text", "content": sentence}, ensure_ascii=False)
            yield "data: " + text_data + "\n\n"

            # 2. 调 TTS 服务获取音频（失败则静默跳过）
            try:
                audio_b64 = await synthesize_speech_b64(sentence)
                audio_data = json.dumps({"type": "audio", "data": audio_b64}, ensure_ascii=False)
                yield "data: " + audio_data + "\n\n"
            except Exception as e:
                logger.debug(f"[{user_id}] TTS 跳过: {e}")

        # 发送音频结束标记
        yield "data: " + json.dumps({"type": "audio_done"}) + "\n\n"

        # 发送情绪标签
        mood_data = json.dumps({"type": "mood", "mood": mood}, ensure_ascii=False)
        yield "data: " + mood_data + "\n\n"
```

- [ ] **Step 3: Verify server starts without errors**

Run: `conda run -n py310 python -c "from server import app; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Integration test with TTS service running**

```bash
# 确保 TTS 服务已启动 (终端 1)
# 启动主服务 (终端 2)
conda run -n py310 python server.py

# 发送消息测试
conda run -n py310 python test_chat.py
# 在日志中验证: status → text(句1) → audio(句1) → text(句2) → audio(句2) → audio_done → mood → done
```

- [ ] **Step 5: Test degradation (TTS service not running)**

```bash
# 只启动主服务，不启动 TTS
conda run -n py310 python server.py

# 发送消息
# 预期: 文字正常显示，日志有 TTS 连接失败的 warning，无报错
```

- [ ] **Step 6: Commit**

```bash
git add server.py
git commit -m "feat: integrate TTS into _event_stream with sentence-by-sentence output"
```

---

### Task 6: Frontend Audio Playback (app.js)

**Files:**
- Modify: `static/js/app.js:104-255`

- [ ] **Step 1: Add audio queue variables**

In `static/js/app.js`, after line 106 (`let currentBotText = "";`), add:

```javascript
let audioQueue = [];
let isPlaying = false;
let ttsEnabled = true;
```

- [ ] **Step 2: Add audio playback functions**

Before the `sendMessage()` function (before line 112), add:

```javascript
/* ==========================================
   音频播放
   ========================================== */
function showAudioWave() {
    const wave = document.getElementById("audio-wave");
    if (wave) wave.style.display = "flex";
}

function hideAudioWave() {
    const wave = document.getElementById("audio-wave");
    if (wave) wave.style.display = "none";
}

function playNextAudio() {
    if (audioQueue.length === 0) {
        isPlaying = false;
        hideAudioWave();
        return;
    }

    isPlaying = true;
    showAudioWave();

    const base64Data = audioQueue.shift();
    const audioBytes = Uint8Array.from(atob(base64Data), function(c) { return c.charCodeAt(0); });
    const blob = new Blob([audioBytes], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);

    const audio = new Audio(url);
    audio.onended = function() {
        URL.revokeObjectURL(url);
        playNextAudio();
    };
    audio.onerror = function() {
        URL.revokeObjectURL(url);
        playNextAudio();
    };
    audio.play();
}

function toggleTTS() {
    ttsEnabled = !ttsEnabled;
    var btn = document.getElementById("tts-toggle");
    if (btn) btn.textContent = ttsEnabled ? "🔊" : "🔇";
    if (!ttsEnabled) {
        audioQueue = [];
        isPlaying = false;
        hideAudioWave();
    }
}
```

- [ ] **Step 3: Add audio/audio_done cases to handleSSEEvent**

In the `handleSSEEvent` function's switch statement (around line 178), add two new cases before the `case "done":` block:

```javascript
        case "audio":
            if (ttsEnabled) {
                audioQueue.push(data.data);
                if (!isPlaying) playNextAudio();
            }
            break;

        case "audio_done":
            // 队列会在播完后自动隐藏声波动画
            break;
```

- [ ] **Step 4: Reset audio state on new message**

In the `sendMessage()` function, after `currentBotText = "";` (line 122), add:

```javascript
    audioQueue = [];
    isPlaying = false;
```

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js
git commit -m "feat: add audio queue, playback, and TTS toggle to frontend"
```

---

### Task 7: Frontend TTS Toggle Button (index.html)

**Files:**
- Modify: `static/index.html:47-49`

- [ ] **Step 1: Add TTS toggle button to chat input area**

Replace the chat-input-area div (lines 47-49):

```html
            <div class="chat-input-area">
                <button id="tts-toggle" onclick="toggleTTS()" title="语音开关">🔊</button>
                <input type="text" id="chat-input" placeholder="输入消息...">
                <button id="send-btn" onclick="sendMessage()">发送</button>
            </div>
```

- [ ] **Step 2: Add CSS for the toggle button**

Append to `static/css/style.css`:

```css

/* TTS 语音开关按钮 */
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

- [ ] **Step 3: Browser test**

Open `http://127.0.0.1:8000` in browser (with both services running):
1. Send a message
2. Verify: text appears sentence by sentence, audio plays for each sentence
3. Click 🔊 → should toggle to 🔇 and mute
4. Click 🔇 → should toggle back to 🔊 and unmute
5. Verify audio wave animation shows during playback, hides when done

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/css/style.css
git commit -m "feat: add TTS toggle button with audio wave animation"
```

---

### Task 8: Final Integration Test & Push

**Files:**
- Modify: `CLAUDE.md` (update progress)

- [ ] **Step 1: Full integration test**

```bash
# 启动 TTS 服务 (终端 1)
conda run -n py310 python tts_server.py

# 启动主服务 (终端 2)
conda run -n py310 python server.py

# 浏览器测试 (http://127.0.0.1:8000)
# 1. 发送消息 → 验证文字逐句出现 + 语音播放
# 2. 关闭 TTS → 只启动主服务 → 发消息 → 验证只有文字，无报错
# 3. 测试命令 /help → 验证命令不走 TTS
# 4. 测试 /clear → 验证清除后正常
```

- [ ] **Step 2: Update CLAUDE.md Phase 2 status**

In `CLAUDE.md`, update the Phase 2 section:

```markdown
### Phase 2: TTS 集成
- [x] CosyVoice2 语音合成（独立服务 tts_server.py）
- [x] 语音流式输出（句子队列逐句播放）
- [x] 错误处理（TTS 失败降级为文本）
- [x] 前端音频播放（队列 + 声波动画 + 开关）
```

- [ ] **Step 3: Commit and push**

```bash
git add CLAUDE.md
git commit -m "docs: update Phase 2 TTS integration progress"
git push origin main
```
