"""
tts_server 请求队列 + 多 Worker 并发测试
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
# 测试请求队列机制（FIFO）
# ==========================================
def test_request_queue_ordering():
    """
    多个请求按 FIFO 顺序处理。
    不依赖真实 GPU。
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
# 测试 tts_worker 函数存在且接受 worker_id
# ==========================================
def test_tts_worker_signature():
    """tts_worker 协程函数接受 worker_id 参数"""
    from tts_server import tts_worker
    import inspect
    assert asyncio.iscoroutinefunction(tts_worker)
    sig = inspect.signature(tts_worker)
    assert "worker_id" in sig.parameters


# ==========================================
# 测试信号量存在且值正确
# ==========================================
def test_semaphore_exists():
    """信号量已创建，值为 TTS_MAX_CONCURRENT"""
    from tts_server import semaphore
    from config import TTS_MAX_CONCURRENT
    assert isinstance(semaphore, asyncio.Semaphore)
    assert semaphore._value == TTS_MAX_CONCURRENT


# ==========================================
# 测试信号量限制并发数
# ==========================================
def test_semaphore_limits_concurrency():
    """信号量确实限制了同时进行的任务数"""
    from tts_server import semaphore
    from config import TTS_MAX_CONCURRENT

    loop = asyncio.new_event_loop()
    max_concurrent = 0
    current_concurrent = 0
    lock = asyncio.Lock()

    async def worker_task():
        nonlocal max_concurrent, current_concurrent
        async with semaphore:
            async with lock:
                current_concurrent += 1
                if current_concurrent > max_concurrent:
                    max_concurrent = current_concurrent
            await asyncio.sleep(0.1)
            async with lock:
                current_concurrent -= 1

    async def run_test():
        tasks = [asyncio.create_task(worker_task()) for _ in range(6)]
        await asyncio.gather(*tasks)

    loop.run_until_complete(run_test())
    loop.close()

    # 最大并发数不应超过 TTS_MAX_CONCURRENT
    assert max_concurrent <= TTS_MAX_CONCURRENT
