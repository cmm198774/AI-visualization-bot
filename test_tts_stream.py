"""
tts_stream 异步生成器测试
测试并发 TTS、顺序保证、错误跳过。
"""
import asyncio
from unittest.mock import patch

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

    async def mock_tts(text):
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
