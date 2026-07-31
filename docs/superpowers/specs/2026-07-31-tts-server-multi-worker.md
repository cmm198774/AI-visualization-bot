# TTS Server 多 Worker 并发推理

## 背景

当前 tts_server 使用单 Worker 串行处理 TTS 请求，GPU 利用率低。在 5090 GPU 上，4 个 chunk 串行需要 ~48s，chunk 间隔 ~12s，导致语音播放不流畅。

## 目标

通过多 Worker 并发推理，充分利用 5090 GPU 算力，将 chunk 间隔从 ~12s 降至 ~3-4s。

## 设计原则

- 只改 tts_server.py 一个文件
- 共享同一个 model 实例（PyTorch 推理多线程安全）
- 用 Semaphore 控制 GPU 并发数
- API 不变，tts_client 无感知

## 改动内容

### 1. import 区域
新增 `from config import TTS_MAX_CONCURRENT`

### 2. 新增信号量
```python
request_queue = asyncio.Queue()
semaphore = asyncio.Semaphore(TTS_MAX_CONCURRENT)
```

### 3. Worker 函数加信号量
```python
async def tts_worker(worker_id: int):
    while True:
        job = await request_queue.get()
        async with semaphore:
            wav_bytes = await asyncio.to_thread(run_inference, job.text, job.speaker)
        job.future.set_result(wav_bytes)
```

### 4. 启动多个 Worker
```python
for i in range(TTS_MAX_CONCURRENT):
    asyncio.create_task(tts_worker(i))
```

### 5. 健康检查新增 workers 字段
```python
return {"status": model_status, "queue_size": ..., "workers": TTS_MAX_CONCURRENT}
```

## 测试方案

### 单元测试（test_tts_server.py）
- test_tts_job_creation（已有）
- test_run_inference_exists（已有）
- test_request_queue_ordering（已有，更新验证 FIFO）
- test_tts_worker_exists（已有，更新验证多 worker）
- test_semaphore_limits_concurrency（新增）
- test_multiple_workers_start（新增）

### 集成测试
并发 4 个请求，验证响应时间接近（并行）而非递增（串行）

### 压力测试
3 用户 × 8 请求 = 24 并发请求，验证：
- 全部成功，无错误
- 响应时间 P50/P95/P99 分布
- 无超时

### 端到端测试（test_e2e.py）
4 个对话场景，验证 chunk 间隔 <= 2s

## 不改的文件
- tts_client.py
- server.py
- sentence_splitter.py
- config.py
- app.js

## 预期效果
```
串行（现在）: 4 chunk × 12s = 48s, 间隔 ~12s
并行（目标）: 4 chunk 同时处理 ~15s, 间隔 ~3-4s
```
