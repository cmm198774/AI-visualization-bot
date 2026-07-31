"""
tts_server 独立模型实例 + 多 Worker 测试
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
    """run_inference 函数已定义，接受 model 参数"""
    from tts_server import run_inference
    import inspect
    assert callable(run_inference)
    sig = inspect.signature(run_inference)
    assert "model_instance" in sig.parameters


# ==========================================
# 测试请求队列机制（FIFO）
# ==========================================
def test_request_queue_ordering():
    """
    多个请求按 FIFO 顺序处理。
    """
    from tts_server import request_queue

    loop = asyncio.new_event_loop()

    async def run_test():
        while not request_queue.empty():
            request_queue.get_nowait()

        futures = []
        for i in range(3):
            f = loop.create_future()
            futures.append(f)

        for i, f in enumerate(futures):
            from tts_server import TTSJob
            job = TTSJob(text=f"句子{i}", speaker="中文女", future=f)
            await request_queue.put(job)

        assert request_queue.qsize() == 3

        jobs = []
        for _ in range(3):
            job = await request_queue.get()
            jobs.append(job.text)
        assert jobs == ["句子0", "句子1", "句子2"]

    loop.run_until_complete(run_test())
    loop.close()


# ==========================================
# 测试 tts_worker 函数签名
# ==========================================
def test_tts_worker_signature():
    """tts_worker 接受 worker_id 参数"""
    from tts_server import tts_worker
    import inspect
    assert asyncio.iscoroutinefunction(tts_worker)
    sig = inspect.signature(tts_worker)
    assert "worker_id" in sig.parameters


# ==========================================
# 测试信号量存在
# ==========================================
def test_semaphore_exists():
    """信号量已创建，值为 TTS_MAX_CONCURRENT"""
    from tts_server import semaphore
    from config import TTS_MAX_CONCURRENT
    assert isinstance(semaphore, asyncio.Semaphore)
    assert semaphore._value == TTS_MAX_CONCURRENT


# ==========================================
# 测试模型路径存在
# ==========================================
def test_model_path_exists():
    """模型路径已配置"""
    from tts_server import MODEL_PATH
    import os
    assert os.path.isdir(MODEL_PATH)
