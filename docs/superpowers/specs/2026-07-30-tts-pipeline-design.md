# TTS 流水线优化设计

## 背景

当前 Phase 2 TTS 集成中，句子和句子之间有明显停顿。原因是后端对每句话串行调用 TTS：
第 N 句 TTS 完成后才开始第 N+1 句的 TTS，前端播放队列"喂不饱"。

## 目标

消除句子之间的语音停顿，实现流畅的连续播放体验。

## 设计原则

- 关注点分离：server.py 只管 SSE，tts 模块管并发逻辑
- tts_server 保证并发安全（请求队列 + 单 worker 串行推理）
- tts_client 保证流畅度（并发调用 + 按序 yield + 预生成）
- 错误静默跳过，不影响整体体验

## 架构

```
server.py
    │
    │  async for text, audio in tts_stream(sentences)
    ↓
tts_client.py (tts_stream)
    │
    │  并发调用 synthesize_speech_b64 (Semaphore 控制并发数)
    │  按序号填充 buffer
    │  按序 yield (text, audio)
    ↓ (HTTP)
tts_server.py
    │
    │  请求进入 asyncio.Queue
    │  单 worker 串行推理 (asyncio.to_thread)
    │  用 Future 返回结果
    ↓
CosyVoice 模型 (GPU)
```

## 详细设计

### 1. tts_server.py — 重写

**核心改动**：内部用请求队列 + 单 worker，保证并发请求安全处理。

```python
# 请求队列
request_queue = asyncio.Queue()

class TTSJob:
    text: str
    speaker: str
    future: asyncio.Future

async def tts_worker():
    """后台 worker，串行处理 TTS 请求"""
    while True:
        job = await request_queue.get()
        try:
            audio = await asyncio.to_thread(run_inference, job.text, job.speaker)
            job.future.set_result(audio)
        except Exception as e:
            job.future.set_exception(e)

@app.post("/tts")
async def tts(request: TTSRequest):
    """接收请求 → 放入队列 → 等待结果 → 返回"""
    future = asyncio.get_event_loop().create_future()
    job = TTSJob(text=request.text, speaker=request.speaker, future=future)
    await request_queue.put(job)
    wav_bytes = await future
    return Response(content=wav_bytes, media_type="audio/wav")

@app.on_event("startup")
async def startup():
    asyncio.create_task(tts_worker())
```

**`run_inference` 函数**：从现有 `tts()` 端点提取的推理逻辑：
```python
def run_inference(text: str, speaker: str) -> bytes:
    """同步推理函数（在线程池中运行）"""
    audio_chunks = []
    for chunk in model.inference_sft(text, speaker):
        audio_chunks.append(chunk["tts_speech"].numpy().flatten())
    audio_np = np.concatenate(audio_chunks)
    return numpy_to_wav(audio_np, sample_rate=model.sample_rate)
```

**要点**：
- FastAPI 持续接收请求（不阻塞）
- 实际推理串行（GPU 安全）
- API 不变，tts_client 无感知
- `asyncio.to_thread()` 把同步 GPU 推理放到线程池，不阻塞事件循环

### 2. tts_client.py — 新增 tts_stream

**核心逻辑**：并发调用 TTS + 共享 buffer + 按序 yield。

```python
TTS_SKIP = object()  # 标记跳过的句子

async def tts_stream(sentences: list) -> AsyncGenerator:
    """
    异步生成器，按顺序 yield (text, audio_b64) 元组。
    内部并发处理 TTS，保证返回顺序。
    """
    buffer = [None] * len(sentences)
    semaphore = asyncio.Semaphore(TTS_MAX_CONCURRENT)

    async def process_one(idx, sentence):
        async with semaphore:
            try:
                audio_b64 = await synthesize_speech_b64(sentence)
                buffer[idx] = audio_b64
            except Exception:
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
```

**要点**：
- 所有句子的 TTS 任务同时启动（受 Semaphore 控制并发数）
- 主循环按序号等待 buffer，有结果就 yield
- 失败标记为 TTS_SKIP，跳过该句
- 保证顺序：第 i 次 yield 就是第 i 句的 text + audio

### 3. server.py — 简化调用

**改动前**（串行）：
```python
for sentence in sentences:
    yield text_data
    audio_b64 = await synthesize_speech_b64(sentence)
    yield audio_data
```

**改动后**（流水线）：
```python
async for sentence, audio_b64 in tts_stream(sentences):
    yield text_event(sentence)
    yield audio_event(audio_b64)
```

### 4. config.py — 新增配置

```python
TTS_MAX_CONCURRENT = int(os.getenv("TTS_MAX_CONCURRENT", "3"))
```

控制 tts_client 同时进行的 TTS 请求数量。

## 错误处理

- 单句 TTS 失败 → 标记 TTS_SKIP，跳过该句音频
- 文字正常显示，只是没有语音
- 不影响后续句子处理

## 不改动的文件

- `sentence_splitter.py` — 分句逻辑不变
- `app.js` — 前端 audioQueue 机制够用，不需要改
- `/health` 端点 — 保持不变

## 文件改动清单

| 文件 | 改动 |
|------|------|
| `tts_server.py` | 重写：请求队列 + 单 worker 串行推理 |
| `tts_client.py` | 新增 `tts_stream()` 异步生成器 |
| `config.py` | 新增 `TTS_MAX_CONCURRENT` |
| `server.py` | 改用 `async for ... in tts_stream(sentences)` |
