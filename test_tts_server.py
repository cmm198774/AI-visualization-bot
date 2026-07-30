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
