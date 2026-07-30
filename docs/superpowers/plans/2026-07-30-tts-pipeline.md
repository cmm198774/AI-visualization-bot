# TTS 流水线优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除句子之间的语音停顿，通过并发 TTS + 流水线架构实现流畅的连续播放体验。

**Architecture:** tts_server 用请求队列 + 单 worker 串行推理保证 GPU 安全；tts_client 新增 `tts_stream()` 异步生成器，并发调用 TTS 服务、按序 yield (text, audio) 元组；server.py 改用 `async for` 消费。

**Tech Stack:** Python asyncio (Semaphore, Queue, Future, to_thread), FastAPI, aiohttp, CosyVoice-300M-SFT

**Spec:** `docs/superpowers/specs/2026-07-30-tts-pipeline-design.md`

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `config.py` | 全局配置 | 修改：新增 `TTS_MAX_CONCURRENT` |
| `tts_server.py` | TTS 独立服务（GPU 推理） | 重写：请求队列 + 单 worker |
| `tts_client.py` | TTS 客户端（调用服务端） | 修改：新增 `tts_stream()` 异步生成器 |
| `server.py` | FastAPI 主服务（SSE） | 修改：改用 `async for ... in tts_stream()` |
| `test_tts_stream.py` | tts_stream 单元测试 | 新建：测试并发逻辑、顺序保证、错误跳过 |
| `test_tts_server.py` | tts_server 单元测试 | 新建：测试队列、worker、并发请求 |

---

### Task 1: 新增配置 TTS_MAX_CONCURRENT

**Files:**
- Modify: `config.py:75`（TTS 配置区域末尾）

- [ ] **Step 1: 在 config.py 末尾新增配置项**

在 `config.py` 的 TTS 服务配置区域（第 70-74 行之后）追加：

```python
TTS_MAX_CONCURRENT = int(os.getenv("TTS_MAX_CONCURRENT", "3"))
```

- [ ] **Step 2: 验证配置加载**

Run:
```bash
conda run -n py310 python -c "from config import TTS_MAX_CONCURRENT; print(TTS_MAX_CONCURRENT)"
```
Expected: `3`

- [ ] **Step 3: Commit**

```bash
git add config.py
git commit -m "feat(config): add TTS_MAX_CONCURRENT config"
```

---

### Task 2: 重写 tts_server.py — 请求队列 + 单 Worker

**Files:**
- Modify: `tts_server.py`（整个文件重写）
- Test: `test_tts_server.py`

- [ ] **Step 1: 写测试 test_tts_server.py**

创建 `test_tts_server.py`：

```python
"""
tts_server 请求队列 + worker 测试
"""
import asyncio
import pytest


# ==========================================
# 测试 TTSJob 数据类
# ==========================================
def test_tts_job_creation():
    """TTSJob 可以正确创建"""
    from tts_server import TTSJob
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    job = TTSJob(text="你好", speaker="中文女", future=future)
    assert job.text == "你好"
    assert job.speaker == "中文女"
    assert job.future is future
    loop.close()


# ==========================================
# 测试 run_inference 函数存在
# ==========================================
def test_run_inference_exists():
    """run_inference 函数已定义"""
    from tts_server import run_inference
    assert callable(run_inference)


# ==========================================
# 测试请求队列机制（用 mock 模型）
# ==========================================
def test_request_queue_ordering():
    """
    多个请求按 FIFO 顺序处理。
    用 mock 模型测试队列机制，不依赖真实 GPU。
    """
    from tts_server import request_queue

    loop = asyncio.new_event_loop()

    async def run_test():
        # 清空队列
        while not request_queue.empty():
            request_queue.get_nowait()

        # 创建 3 个 future
        futures = []
        for i in range(3):
            f = loop.create_future()
            futures.append(f)

        # 按顺序放入队列
        for i, f in enumerate(futures):
            from tts_server import TTSJob
            job = TTSJob(text=f"句子{i}", speaker="中文女", future=f)
            await request_queue.put(job)

        # 验证队列中有 3 个任务
        assert request_queue.qsize() == 3

        # 按顺序取出，验证 FIFO
        jobs = []
        for _ in range(3):
            job = await request_queue.get()
            jobs.append(job.text)
        assert jobs == ["句子0", "句子1", "句子2"]

    loop.run_until_complete(run_test())
    loop.close()


# ==========================================
# 测试 tts_worker 函数存在
# ==========================================
def test_tts_worker_exists():
    """tts_worker 协程函数已定义"""
    from tts_server import tts_worker
    assert asyncio.iscoroutinefunction(tts_worker)
```

- [ ] **Step 2: 运行测试，确认全部失败**

Run:
```bash
conda run -n py310 python -m pytest test_tts_server.py -v
```
Expected: FAIL（`TTSJob`, `request_queue`, `tts_worker`, `run_inference` 未定义）

- [ ] **Step 3: 重写 tts_server.py**

用以下内容**完整替换** `tts_server.py`：

```python
"""
TTS 独立服务模块
封装 CosyVoice-300M-SFT 模型，提供 HTTP API 进行语音合成。
使用请求队列 + 单 worker 架构，保证 GPU 推理串行安全。
启动方式: python tts_server.py
端口: 9233
"""
import asyncio
import io
import os
import sys
import time

import numpy as np
import soundfile as sf
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn

from config import TTS_MAX_CONCURRENT
from sys_logger import setup_global_logger


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()

# 将 CosyVoice 项目目录加入 Python path
COSYVOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CosyVoice")
MATCHA_TTS_DIR = os.path.join(COSYVOICE_DIR, "third_party", "Matcha-TTS")
if COSYVOICE_DIR not in sys.path:
    sys.path.insert(0, COSYVOICE_DIR)
if MATCHA_TTS_DIR not in sys.path:
    sys.path.insert(0, MATCHA_TTS_DIR)


# ==========================================
# 全局状态
# ==========================================
model = None
model_status = "loading"


# ==========================================
# 加载模型
# ==========================================
def load_model():
    """加载 CosyVoice-300M-SFT 模型到 GPU"""
    global model, model_status

    model_path = os.path.join(COSYVOICE_DIR, "pretrained_models", "CosyVoice-300M-SFT")
    logger.info(f"加载 CosyVoice 模型: {model_path}")

    t0 = time.time()
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice
        model = CosyVoice(model_path)
        elapsed = time.time() - t0
        model_status = "ready"
        logger.info(f"CosyVoice 模型加载完成: 耗时 {elapsed:.1f}s, 音色: {model.list_available_spks()}")
    except Exception as e:
        model_status = "error"
        logger.error(f"CosyVoice 模型加载失败: {e}")


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
# 同步推理函数（在线程池中运行）
# ==========================================
def run_inference(text: str, speaker: str) -> bytes:
    """
    调用 CosyVoice 模型进行语音合成（同步函数）。
    在 tts_worker 中通过 asyncio.to_thread() 调用。

    Args:
        text: 要合成的文本 (str)
        speaker: 音色名称 (str)

    Returns:
        bytes: WAV 格式音频数据

    Raises:
        RuntimeError: 模型未就绪
        Exception: 推理失败
    """
    if model_status != "ready" or model is None:
        raise RuntimeError("模型未就绪")

    audio_chunks = []
    for chunk in model.inference_sft(text, speaker):
        audio_chunks.append(chunk["tts_speech"].numpy().flatten())

    if not audio_chunks:
        raise RuntimeError("合成失败：无音频输出")

    audio_np = np.concatenate(audio_chunks)
    return numpy_to_wav(audio_np, sample_rate=model.sample_rate)


# ==========================================
# TTS 请求队列 & Job
# ==========================================
request_queue = asyncio.Queue()


class TTSJob:
    """TTS 请求任务"""
    def __init__(self, text: str, speaker: str, future: asyncio.Future):
        self.text = text
        self.speaker = speaker
        self.future = future


# ==========================================
# 后台 worker（串行处理 TTS 请求）
# ==========================================
async def tts_worker():
    """
    后台 worker 协程。
    从 request_queue 中逐个取出请求，串行调用 run_inference。
    用 asyncio.to_thread() 避免阻塞事件循环。
    """
    logger.info("TTS worker 启动")
    while True:
        job = await request_queue.get()
        try:
            logger.info(f"TTS worker 处理: text={job.text[:20]}...")
            wav_bytes = await asyncio.to_thread(run_inference, job.text, job.speaker)
            if not job.future.done():
                job.future.set_result(wav_bytes)
        except Exception as e:
            logger.error(f"TTS worker 错误: {e}")
            if not job.future.done():
                job.future.set_exception(e)


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
# 启动时创建 worker
# ==========================================
@app.on_event("startup")
async def startup():
    """启动时创建后台 TTS worker"""
    asyncio.create_task(tts_worker())


# ==========================================
# 健康检查
# ==========================================
@app.get("/health")
async def health():
    """健康检查端点"""
    return {
        "status": model_status,
        "queue_size": request_queue.qsize(),
    }


# ==========================================
# TTS 合成端点
# ==========================================
@app.post("/tts")
async def tts(request: TTSRequest):
    """
    语音合成端点。
    接收请求 → 放入队列 → 等待 worker 处理 → 返回音频。
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
        logger.info(f"TTS 请求入队: text={request.text[:30]}..., speaker={request.speaker}")

        # 创建 Future，放入队列等待 worker 处理
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        job = TTSJob(text=request.text, speaker=request.speaker, future=future)
        await request_queue.put(job)

        # 等待 worker 返回结果
        wav_bytes = await future

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

- [ ] **Step 4: 运行测试，确认通过**

Run:
```bash
conda run -n py310 python -m pytest test_tts_server.py -v
```
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tts_server.py test_tts_server.py
git commit -m "feat(tts_server): rewrite with request queue + single worker

- asyncio.Queue for incoming TTS requests
- Single worker processes requests serially (GPU safe)
- asyncio.to_thread() prevents event loop blocking
- run_inference() extracted from old endpoint
- /health now reports queue_size"
```

- [ ] **Step 6: 单独验证 tts_server**

启动 TTS 服务并验证：

```bash
# 终端 1：启动 TTS 服务
conda run -n py310 python tts_server.py

# 终端 2：检查健康状态
curl http://127.0.0.1:9233/health
# Expected: {"status":"ready","queue_size":0}

# 发送测试 TTS 请求
curl -X POST http://127.0.0.1:9233/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "你好，这是一个测试。", "speaker": "中文女"}' \
  --output test_output.wav
# Expected: 返回 WAV 文件，可以播放

# 验证队列机制（快速发多个请求）
for i in 1 2 3; do
  curl -X POST http://127.0.0.1:9233/tts \
    -H "Content-Type: application/json" \
    -d "{\"text\": \"句子$i\", \"speaker\": \"中文女\"}" \
    --output "test_$i.wav" &
done
wait
# Expected: 3 个文件都生成成功，queue_size 回到 0
```

确认无误后关闭 TTS 服务。

---

### Task 3: 新增 tts_stream() 异步生成器到 tts_client.py

**Files:**
- Modify: `tts_client.py`（追加 `tts_stream` 函数）
- Test: `test_tts_stream.py`

- [ ] **Step 1: 写测试 test_tts_stream.py**

创建 `test_tts_stream.py`：

```python
"""
tts_stream 异步生成器测试
测试并发 TTS、顺序保证、错误跳过。
"""
import asyncio
from unittest.mock import patch, AsyncMock

import pytest


# ==========================================
# 测试 tts_stream 顺序保证
# ==========================================
def test_tts_stream_preserves_order():
    """
    即使 TTS 完成顺序不同，yield 顺序与句子顺序一致。
    """
    from tts_client import tts_stream

    # mock synthesize_speech_b64：第 0 句慢，第 1 句快
    async def mock_tts(text):
        if text == "句子0":
            await asyncio.sleep(0.2)  # 慢
        return f"audio_{text}"

    async def run_test():
        with patch("tts_client.synthesize_speech_b64", side_effect=mock_tts):
            results = []
            async for text, audio in tts_stream(["句子0", "句子1", "句子2"]):
                results.append((text, audio))

        assert results == [
            ("句子0", "audio_句子0"),
            ("句子1", "audio_句子1"),
            ("句子2", "audio_句子2"),
        ]

    asyncio.run(run_test())


# ==========================================
# 测试 tts_stream 错误跳过
# ==========================================
def test_tts_stream_skips_failures():
    """
    TTS 失败的句子被跳过，不影响其他句子。
    """
    from tts_client import tts_stream

    call_count = 0

    async def mock_tts(text):
        nonlocal call_count
        call_count += 1
        if text == "句子1":
            raise Exception("TTS 失败")
        return f"audio_{text}"

    async def run_test():
        with patch("tts_client.synthesize_speech_b64", side_effect=mock_tts):
            results = []
            async for text, audio in tts_stream(["句子0", "句子1", "句子2"]):
                results.append((text, audio))

        # 句子1 被跳过
        assert results == [
            ("句子0", "audio_句子0"),
            ("句子2", "audio_句子2"),
        ]

    asyncio.run(run_test())


# ==========================================
# 测试 tts_stream 空列表
# ==========================================
def test_tts_stream_empty_sentences():
    """空句子列表 → 无输出"""
    from tts_client import tts_stream

    async def run_test():
        results = []
        async for text, audio in tts_stream([]):
            results.append((text, audio))
        assert results == []

    asyncio.run(run_test())


# ==========================================
# 测试 tts_stream 单句
# ==========================================
def test_tts_stream_single_sentence():
    """单句正常工作"""
    from tts_client import tts_stream

    async def mock_tts(text):
        return f"audio_{text}"

    async def run_test():
        with patch("tts_client.synthesize_speech_b64", side_effect=mock_tts):
            results = []
            async for text, audio in tts_stream(["你好"]):
                results.append((text, audio))

        assert results == [("你好", "audio_你好")]

    asyncio.run(run_test())


# ==========================================
# 测试 tts_stream 全部失败
# ==========================================
def test_tts_stream_all_fail():
    """所有句子 TTS 失败 → 无输出"""
    from tts_client import tts_stream

    async def mock_tts(text):
        raise Exception("TTS 服务不可用")

    async def run_test():
        with patch("tts_client.synthesize_speech_b64", side_effect=mock_tts):
            results = []
            async for text, audio in tts_stream(["句子0", "句子1"]):
                results.append((text, audio))

        assert results == []

    asyncio.run(run_test())


# ==========================================
# 测试 tts_stream 并发控制
# ==========================================
def test_tts_stream_respects_semaphore():
    """
    Semaphore 控制同时进行的 TTS 数量。
    设置 TTS_MAX_CONCURRENT=2，验证不会超过 2 个并发。
    """
    from tts_client import tts_stream

    max_concurrent = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    async def mock_tts(text):
        nonlocal max_concurrent, current_concurrent
        async with lock:
            current_concurrent += 1
            if current_concurrent > max_concurrent:
                max_concurrent = current_concurrent
        await asyncio.sleep(0.1)
        async with lock:
            current_concurrent -= 1
        return f"audio_{text}"

    async def run_test():
        with patch("tts_client.synthesize_speech_b64", side_effect=mock_tts):
            with patch("tts_client.TTS_MAX_CONCURRENT", 2):
                results = []
                async for text, audio in tts_stream(["a", "b", "c", "d"]):
                    results.append((text, audio))

        assert len(results) == 4
        assert max_concurrent <= 2

    asyncio.run(run_test())
```

- [ ] **Step 2: 运行测试，确认全部失败**

Run:
```bash
conda run -n py310 python -m pytest test_tts_stream.py -v
```
Expected: FAIL（`tts_stream` 不存在）

- [ ] **Step 3: 在 tts_client.py 末尾追加 tts_stream 函数**

在 `tts_client.py` 文件末尾（第 90 行之后）追加以下代码：

```python
import asyncio
from typing import AsyncGenerator
from config import TTS_MAX_CONCURRENT


# ==========================================
# TTS 跳过标记
# ==========================================
TTS_SKIP = object()


# ==========================================
# TTS 流式生成器（并发 + 按序 yield）
# ==========================================
async def tts_stream(sentences: list) -> AsyncGenerator:
    """
    异步生成器，按顺序 yield (text, audio_b64) 元组。
    内部并发处理 TTS，保证返回顺序与句子顺序一致。

    Args:
        sentences: 句子列表 (list[str])

    Yields:
        tuple[str, str]: (句子文本, base64 音频)

    Notes:
        - TTS 失败的句子静默跳过
        - 并发数由 TTS_MAX_CONCURRENT 控制
    """
    if not sentences:
        return

    buffer = [None] * len(sentences)
    semaphore = asyncio.Semaphore(TTS_MAX_CONCURRENT)

    async def process_one(idx: int, sentence: str):
        """处理单个句子的 TTS"""
        async with semaphore:
            try:
                audio_b64 = await synthesize_speech_b64(sentence)
                buffer[idx] = audio_b64
            except Exception as e:
                logger.warning(f"tts_stream: 句子 {idx} TTS 失败: {e}")
                buffer[idx] = TTS_SKIP

    # 并发启动所有 TTS 任务
    tasks = [asyncio.create_task(process_one(i, s))
             for i, s in enumerate(sentences)]

    # 按序 yield
    for i, sentence in enumerate(sentences):
        while buffer[i] is None:
            await asyncio.sleep(0.05)
        if buffer[i] is not TTS_SKIP:
            yield sentence, buffer[i]

    # 确保所有任务完成（清理）
    await asyncio.gather(*tasks, return_exceptions=True)
```

**注意：** `import asyncio` 和 `from config import TTS_MAX_CONCURRENT` 需要加到文件顶部。把 `tts_client.py` 顶部的 import 区域修改为：

```python
"""
TTS 客户端模块
调用独立 TTS 服务进行语音合成。
"""
import asyncio
import base64
import ssl
from typing import AsyncGenerator

# ==========================================
# Windows SSL 证书加载 bug 修复
# aiohttp 导入时会调用 ssl.create_default_context()，
# Windows 下 _load_windows_store_certs 可能抛出 NOT_ENOUGH_DATA，
# 改为使用 certifi 的 CA 证书包。
# ==========================================
_orig_load_default_certs = ssl.SSLContext.load_default_certs


def _patched_load_default_certs(self, purpose=ssl.Purpose.SERVER_AUTH):
    import certifi
    self.load_verify_locations(certifi.where())


ssl.SSLContext.load_default_certs = _patched_load_default_certs

import aiohttp

from config import TTS_SERVER_URL, TTS_SPEAKER, TTS_TIMEOUT, TTS_MAX_CONCURRENT
from sys_logger import setup_global_logger
```

- [ ] **Step 4: 运行测试，确认通过**

Run:
```bash
conda run -n py310 python -m pytest test_tts_stream.py -v
```
Expected: 6 tests PASS

- [ ] **Step 5: 运行分句测试，确认没有破坏原有功能**

Run:
```bash
conda run -n py310 python -m pytest test_sentence_splitter.py -v
```
Expected: 9 tests PASS

- [ ] **Step 6: Commit**

```bash
git add tts_client.py test_tts_stream.py
git commit -m "feat(tts_client): add tts_stream async generator

- Concurrent TTS with asyncio.Semaphore control
- Ordered yield: buffer indexed by sentence number
- Silent skip on TTS failure (TTS_SKIP sentinel)
- 6 unit tests: order, skip, empty, single, all-fail, concurrency"
```

- [ ] **Step 7: 单独验证 tts_client**

启动 TTS 服务，然后用测试脚本验证 tts_client：

```bash
# 终端 1：启动 TTS 服务（如果还没启动）
conda run -n py310 python tts_server.py

# 终端 2：创建并运行验证脚本
```

创建临时测试脚本 `verify_tts_client.py`：

```python
"""单独验证 tts_client.tts_stream"""
import asyncio
from tts_client import tts_stream

async def main():
    sentences = ["你好，我是Lisa。", "今天天气不错呢！", "有什么可以帮你的吗？"]
    print(f"开始测试，共 {len(sentences)} 句")

    idx = 0
    async for text, audio in tts_stream(sentences):
        idx += 1
        print(f"[{idx}] 收到: text={text[:20]}..., audio_size={len(audio)} bytes")

    print(f"完成！共收到 {idx} 句音频")

if __name__ == "__main__":
    asyncio.run(main())
```

运行：
```bash
conda run -n py310 python verify_tts_client.py
# Expected: 按顺序输出 3 句，每句都有 audio_size
# 验证：顺序正确、无停顿（几乎是瞬间完成）

# 清理临时文件
rm verify_tts_client.py
```

确认无误后关闭 TTS 服务。

---

### Task 4: 修改 server.py — 改用 tts_stream

**Files:**
- Modify: `server.py:31`（import 行）
- Modify: `server.py:330-345`（逐句 TTS 逻辑）

- [ ] **Step 1: 修改 server.py 的 import**

将 `server.py` 第 31 行：
```python
from tts_client import synthesize_speech_b64
```

改为：
```python
from tts_client import tts_stream
```

- [ ] **Step 2: 修改 server.py 的逐句 TTS 逻辑**

将 `server.py` 第 330-342 行（从 `# 逐句发送文字 + 音频` 到 `logger.debug(...)` 的 for 循环）：

```python
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
```

替换为：
```python
        # 流水线发送文字 + 音频（tts_stream 并发处理，按序 yield）
        async for sentence, audio_b64 in tts_stream(sentences):
            # 1. 先 yield 文字（前端立即显示）
            text_data = json.dumps({"type": "text", "content": sentence}, ensure_ascii=False)
            yield "data: " + text_data + "\n\n"

            # 2. yield 音频
            audio_data = json.dumps({"type": "audio", "data": audio_b64}, ensure_ascii=False)
            yield "data: " + audio_data + "\n\n"
```

- [ ] **Step 3: 验证 server.py 可以正常导入（无语法错误）**

Run:
```bash
conda run -n py310 python -c "import server; print('OK')"
```
Expected: 输出 `OK`（可能会有一些启动日志，但不应该报 ImportError 或 SyntaxError）

- [ ] **Step 4: Commit**

```bash
git add server.py
git commit -m "feat(server): use tts_stream for pipeline TTS

- Replace serial for-loop with async for ... in tts_stream()
- Remove direct synthesize_speech_b64 call
- TTS concurrency now handled by tts_client module"
```

---

### Task 5: 集成验证

**Files:** 无新增文件

- [ ] **Step 1: 运行所有相关测试**

Run:
```bash
conda run -n py310 python -m pytest test_tts_server.py test_tts_stream.py test_sentence_splitter.py -v
```
Expected: 所有测试 PASS（4 + 6 + 9 = 19 个测试）

- [ ] **Step 2: 手动验证 TTS 流水线（需要 GPU）**

启动 TTS 服务和主服务，在浏览器中发送消息，确认：
1. 语音播放流畅，句子之间无明显停顿
2. 文字和音频同步
3. TTS 失败时静默降级（文字正常显示，无音频）
4. `/health` 端点返回 `queue_size` 字段

```bash
# 终端 1：启动 TTS 服务
conda run -n py310 python tts_server.py

# 终端 2：启动主服务
conda run -n py310 python server.py

# 终端 3：检查健康状态
curl http://127.0.0.1:9233/health
# Expected: {"status":"ready","queue_size":0}
```

- [ ] **Step 3: 最终 Commit**

```bash
git add -A
git commit -m "docs: TTS pipeline integration verified"
```

---

## 完成标准

1. `config.py` 包含 `TTS_MAX_CONCURRENT = 3`
2. `tts_server.py` 使用请求队列 + 单 worker 架构
3. `tts_client.py` 提供 `tts_stream()` 异步生成器
4. `server.py` 使用 `async for ... in tts_stream(sentences)` 消费
5. 所有单元测试通过（19 个）
6. 手动验证语音播放流畅、无停顿
