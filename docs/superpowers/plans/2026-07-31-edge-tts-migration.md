# edge-tts 迁移实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 TTS 引擎从本地 CosyVoice 切换为 Microsoft edge-tts 云端服务，消除语音流畅度问题。

**Architecture:** 删除独立的 tts_server.py（CosyVoice GPU 推理），改写 tts_client.py 直接调用 edge-tts 云端 API。保留 tts_stream() 的 chunk 合并 + 预缓冲架构不变。前端 Blob 类型从 WAV 改为 MPEG。

**Tech Stack:** edge-tts (Python), FastAPI, JavaScript (前端音频播放)

**设计文档:** `docs/superpowers/specs/2026-07-31-edge-tts-migration-design.md`

---

## 文件结构

| 操作 | 文件 | 职责 |
|------|------|------|
| 改写 | `tts_client.py` | edge-tts 直接调用 + tts_stream 流式生成 |
| 删除 | `tts_server.py` | 不再需要独立 TTS 服务 |
| 改写 | `config.py:70-77` | 清理旧 TTS 配置，新增 EDGE_TTS_VOICE |
| 改写 | `static/js/app.js:152` | Blob type WAV → MPEG |
| 改写 | `CLAUDE.md` | 更新文件结构和运行方式 |
| 新建 | `tests/test_edge_tts.py` | edge-tts 集成测试 |

---

### Task 1: 安装 edge-tts 依赖

**Files:**
- 无文件变更，仅安装 pip 包

- [ ] **Step 1: 安装 edge-tts**

```bash
export PATH="/c/ProgramData/Anaconda3/Scripts:/c/ProgramData/Anaconda3:$PATH"
conda run -n py310 pip install edge-tts
```

Expected: `Successfully installed edge-tts-x.x.x`

- [ ] **Step 2: 验证安装**

```bash
conda run -n py310 python -c "import edge_tts; print(edge_tts.__version__)"
```

Expected: 输出版本号（如 `7.0.0`），无报错。

- [ ] **Step 3: 提交**

无需提交（无文件变更）。

---

### Task 2: 更新 config.py — 清理旧配置，新增 EDGE_TTS_VOICE

**Files:**
- Modify: `config.py:70-77`

- [ ] **Step 1: 改写 TTS 配置段**

打开 `config.py`，将第 70-77 行的 TTS 配置段替换为：

```python
# ==========================================
# TTS 配置（edge-tts 云端合成）
# ==========================================
EDGE_TTS_VOICE = os.getenv("EDGE_TTS_VOICE", "zh-CN-XiaoxiaoNeural")
TTS_CHUNK_SIZE = int(os.getenv("TTS_CHUNK_SIZE", "40"))
TTS_PREBUFFER = int(os.getenv("TTS_PREBUFFER", "4"))
```

删除的行：
- `TTS_SERVER_URL`
- `TTS_SPEAKER`
- `TTS_TIMEOUT`
- `TTS_MAX_CONCURRENT`

保留的行：
- `TTS_CHUNK_SIZE`
- `TTS_PREBUFFER`

- [ ] **Step 2: 验证 config 可正常导入**

```bash
conda run -n py310 python -c "from config import EDGE_TTS_VOICE, TTS_CHUNK_SIZE, TTS_PREBUFFER; print(EDGE_TTS_VOICE, TTS_CHUNK_SIZE, TTS_PREBUFFER)"
```

Expected: `zh-CN-XiaoxiaoNeural 40 4`

- [ ] **Step 3: 提交**

```bash
git add config.py
git commit -m "refactor(config): replace CosyVoice config with edge-tts config"
```

---

### Task 3: 编写 edge-tts 集成测试

**Files:**
- Create: `tests/test_edge_tts.py`

- [ ] **Step 1: 编写测试文件**

```python
"""
edge-tts 集成测试
测试 synthesize_speech() 函数的基本功能和错误处理。
"""
import asyncio
import pytest

from tts_client import synthesize_speech, synthesize_speech_b64, tts_stream


# ==========================================
# synthesize_speech 测试
# ==========================================
class TestSynthesizeSpeech:
    """测试 synthesize_speech() 函数"""

    def test_returns_bytes(self):
        """合成结果应为 bytes 类型"""
        result = asyncio.get_event_loop().run_until_complete(
            synthesize_speech("你好")
        )
        assert isinstance(result, bytes)

    def test_non_empty_audio(self):
        """合成结果不应为空"""
        result = asyncio.get_event_loop().run_until_complete(
            synthesize_speech("你好，这是一个测试。")
        )
        assert len(result) > 1000  # MP3 音频至少几 KB

    def test_empty_text_raises(self):
        """空文本应抛出异常"""
        with pytest.raises(Exception):
            asyncio.get_event_loop().run_until_complete(
                synthesize_speech("")
            )


# ==========================================
# synthesize_speech_b64 测试
# ==========================================
class TestSynthesizeSpeechB64:
    """测试 synthesize_speech_b64() 函数"""

    def test_returns_string(self):
        """base64 结果应为 str 类型"""
        result = asyncio.get_event_loop().run_until_complete(
            synthesize_speech_b64("你好")
        )
        assert isinstance(result, str)

    def test_valid_base64(self):
        """结果应为有效的 base64 编码"""
        import base64
        result = asyncio.get_event_loop().run_until_complete(
            synthesize_speech_b64("你好")
        )
        decoded = base64.b64decode(result)
        assert len(decoded) > 1000


# ==========================================
# tts_stream 测试
# ==========================================
class TestTtsStream:
    """测试 tts_stream() 流式生成器"""

    def test_yields_tuples(self):
        """tts_stream 应 yield (text, audio_b64) 元组"""
        sentences = ["你好。", "世界。"]
        results = []
        async for item in tts_stream(sentences):
            results.append(item)

        assert len(results) > 0
        for text, audio_b64 in results:
            assert isinstance(text, str)
            assert isinstance(audio_b64, str)
            assert len(text) > 0
            assert len(audio_b64) > 0

    def test_empty_sentences(self):
        """空句子列表应直接返回"""
        results = []
        async for item in tts_stream([]):
            results.append(item)
        assert len(results) == 0

    def test_preserves_order(self):
        """输出顺序应与输入顺序一致"""
        sentences = ["第一句话。", "第二句话。", "第三句话。"]
        texts = []
        async for item in tts_stream(sentences):
            texts.append(item[0])
        # chunk 合并后可能变成 1 个 chunk，但内容应包含所有句子
        combined = " ".join(texts)
        assert "第一句话" in combined
        assert "第二句话" in combined
        assert "第三句话" in combined
```

- [ ] **Step 2: 运行测试，确认失败（tts_client 尚未改写）**

```bash
conda run -n py310 python -m pytest tests/test_edge_tts.py -v
```

Expected: FAIL — `tts_client.py` 仍使用 aiohttp 调用 tts_server（未启动），连接失败。

- [ ] **Step 3: 提交测试文件**

```bash
git add tests/test_edge_tts.py
git commit -m "test: add edge-tts integration tests"
```

---

### Task 4: 改写 tts_client.py — 替换为 edge-tts 直接调用

**Files:**
- Modify: `tts_client.py`（整体改写）

- [ ] **Step 1: 用以下内容完整替换 tts_client.py**

```python
"""
TTS 客户端模块
使用 edge-tts 进行云端语音合成。
"""
import asyncio
import base64
from typing import AsyncGenerator

import edge_tts

from config import EDGE_TTS_VOICE, TTS_CHUNK_SIZE, TTS_PREBUFFER
from sys_logger import setup_global_logger


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()


# ==========================================
# 调用 edge-tts 云端合成语音
# ==========================================
async def synthesize_speech(text: str) -> bytes:
    """
    调用 edge-tts 云端合成语音。

    Args:
        text: 要合成的文本 (str)

    Returns:
        bytes: MP3 格式音频数据

    Raises:
        Exception: 合成失败时抛出
    """
    if not text or not text.strip():
        raise ValueError("文本不能为空")

    communicate = edge_tts.Communicate(text, voice=EDGE_TTS_VOICE)
    audio_bytes = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes += chunk["data"]

    if not audio_bytes:
        raise RuntimeError("edge-tts 合成失败：无音频输出")

    logger.debug(f"TTS 合成完成: text={text[:20]}..., size={len(audio_bytes)} bytes")
    return audio_bytes


# ==========================================
# 文本转 base64 音频
# ==========================================
async def synthesize_speech_b64(text: str) -> str:
    """
    调用 edge-tts 合成语音，返回 base64 编码的音频数据。

    Args:
        text: 要合成的文本 (str)

    Returns:
        str: base64 编码的 MP3 音频字符串
    """
    audio_bytes = await synthesize_speech(text)
    return base64.b64encode(audio_bytes).decode("utf-8")


# ==========================================
# TTS 跳过标记
# ==========================================
TTS_SKIP = object()


# ==========================================
# TTS 流式生成器（并发 + 预缓冲 + 按序 yield）
# ==========================================
async def tts_stream(sentences: list) -> AsyncGenerator:
    """
    异步生成器，按顺序 yield (text, audio_b64) 元组。
    内部并发处理 TTS，预缓冲后按序 yield。

    Args:
        sentences: 句子列表 (list[str])

    Yields:
        tuple[str, str]: (句子文本, base64 音频)

    Notes:
        - 句子先按 TTS_CHUNK_SIZE 合并为 chunk
        - 预缓冲 TTS_PREBUFFER 个 chunk 后再开始 yield
        - TTS 失败的 chunk 静默跳过
    """
    from sentence_splitter import chunk_sentences

    if not sentences:
        return

    # 将小句子合并为 chunk
    chunks = chunk_sentences(sentences, TTS_CHUNK_SIZE)
    if not chunks:
        return

    buffer = [None] * len(chunks)

    async def process_one(idx: int, chunk: str):
        """处理单个 chunk 的 TTS"""
        try:
            audio_b64 = await synthesize_speech_b64(chunk)
            buffer[idx] = audio_b64
        except Exception as e:
            logger.warning(f"tts_stream: chunk {idx} TTS 失败: {e}")
            buffer[idx] = TTS_SKIP

    # 并发启动所有 TTS 任务
    tasks = [asyncio.create_task(process_one(i, c))
             for i, c in enumerate(chunks)]

    # 预缓冲：等待前 TTS_PREBUFFER 个 chunk 完成
    prebuffer_count = min(TTS_PREBUFFER, len(chunks))
    for i in range(prebuffer_count):
        while buffer[i] is None:
            await asyncio.sleep(0.05)

    # 预缓冲完成，开始按序 yield
    for i, chunk in enumerate(chunks):
        while buffer[i] is None:
            await asyncio.sleep(0.05)
        if buffer[i] is not TTS_SKIP:
            yield chunk, buffer[i]

    # 确保所有任务完成（清理）
    await asyncio.gather(*tasks, return_exceptions=True)
```

**与旧版的关键差异：**
- 删除：Windows SSL monkey-patch、aiohttp import、`TTS_MAX_CONCURRENT` semaphore
- 替换：`synthesize_speech()` 从 aiohttp HTTP 调用改为 edge-tts 直接调用
- 简化：`tts_stream()` 移除 Semaphore 并发控制（edge-tts 无 GPU 限制，直接并发）
- 保留：`TTS_SKIP`、`synthesize_speech_b64()`、chunk 合并 + 预缓冲 + 按序 yield

- [ ] **Step 2: 运行测试，确认通过**

```bash
conda run -n py310 python -m pytest tests/test_edge_tts.py -v
```

Expected: 全部 PASS（需要联网）。

- [ ] **Step 3: 提交**

```bash
git add tts_client.py
git commit -m "feat(tts_client): replace CosyVoice with edge-tts direct call"
```

---

### Task 5: 更新前端 app.js — 音频格式 WAV → MPEG

**Files:**
- Modify: `static/js/app.js:152`

- [ ] **Step 1: 修改 Blob MIME 类型**

在 `static/js/app.js` 第 152 行，将：

```javascript
const blob = new Blob([audioBytes], { type: "audio/wav" });
```

改为：

```javascript
const blob = new Blob([audioBytes], { type: "audio/mpeg" });
```

- [ ] **Step 2: 提交**

```bash
git add static/js/app.js
git commit -m "fix(frontend): change audio blob type from wav to mpeg for edge-tts"
```

---

### Task 6: 删除 tts_server.py

**Files:**
- Delete: `tts_server.py`

- [ ] **Step 1: 删除文件**

```bash
git rm tts_server.py
```

- [ ] **Step 2: 提交**

```bash
git commit -m "refactor: remove tts_server.py (CosyVoice no longer needed)"
```

---

### Task 7: 更新 CLAUDE.md — 反映新架构

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 更新 TTS 相关描述**

在 CLAUDE.md 中进行以下修改：

1. **技术栈**部分：将 TTS 描述改为 `edge-tts（Microsoft 云端语音合成）`

2. **Phase 2 TTS 集成**部分：更新已完成项：
   - `CosyVoice-300M-SFT 语音合成` → `edge-tts 云端语音合成（zh-CN-XiaoxiaoNeural 音色）`
   - 删除 `tts_server 重写` 相关描述
   - 删除 `tts_client 新增 tts_stream` 中的 "chunk_sentences 合并" 前的 "并发合成" 描述中的 GPU 相关内容

3. **运行方式**部分：删除终端 1（tts_server.py），只保留一个终端：
   ```bash
   conda run -n py310 python server.py
   ```

4. **重要配置**部分：
   - 删除 `TTS_MAX_CONCURRENT`、`TTS_TIMEOUT`、`MODELSCOPE_OFFLINE`
   - 新增 `EDGE_TTS_VOICE="zh-CN-XiaoxiaoNeural"`

5. **文件结构**部分：删除 `tts_server.py` 行

6. **已知问题**部分：
   - 删除 CosyVoice 相关问题（NumPy 版本冲突、模型加载慢、多 worker 失败率、句子间停顿）
   - 新增：edge-tts 需要联网

- [ ] **Step 2: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md for edge-tts migration"
```

---

### Task 8: 端到端验证

**Files:**
- 无新文件

- [ ] **Step 1: 启动服务器（只需一个终端）**

```bash
conda run -n py310 python server.py
```

Expected: 服务器在 8000 端口启动，无报错。不再需要启动 tts_server.py。

- [ ] **Step 2: 在浏览器中测试聊天 + 语音**

1. 打开 `http://127.0.0.1:8000`
2. 登录
3. 发送一条消息（如 "你好"）
4. 确认：
   - ✅ 文字正常显示
   - ✅ 语音正常播放（zh-CN-XiaoxiaoNeural 女声）
   - ✅ 句子间无明显停顿
   - ✅ 🔊 开关正常工作

- [ ] **Step 3: 测试命令系统（确保没有破坏）**

```
/clear
/status
/help
```

Expected: 命令正常响应。

- [ ] **Step 4: 最终提交（如有遗漏修改）**

```bash
git add -A
git status
# 如有未提交变更：
git commit -m "chore: final cleanup for edge-tts migration"
```

---

## 执行顺序总结

```
Task 1: pip install edge-tts
    │
    ▼
Task 2: 更新 config.py
    │
    ▼
Task 3: 编写测试（预期失败）
    │
    ▼
Task 4: 改写 tts_client.py（测试通过）
    │
    ▼
Task 5: 更新 app.js（WAV → MPEG）
    │
    ▼
Task 6: 删除 tts_server.py
    │
    ▼
Task 7: 更新 CLAUDE.md
    │
    ▼
Task 8: 端到端验证
```
