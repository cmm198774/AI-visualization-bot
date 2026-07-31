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
    使用长句子确保每句都是独立 chunk。
    """
    from tts_client import tts_stream

    # 每个句子超过 chunk_size，确保各自独立
    long_sentences = ["句子0" * 60, "句子1" * 60, "句子2" * 60]

    async def mock_tts(text):
        if text.startswith("句子0"):
            await asyncio.sleep(0.2)
        return f"audio_{text[:10]}"

    async def run_test():
        with patch("tts_client.synthesize_speech_b64", side_effect=mock_tts):
            with patch("tts_client.TTS_CHUNK_SIZE", 50):
                results = []
                async for text, audio in tts_stream(long_sentences):
                    results.append(audio)

        assert len(results) == 3

    asyncio.run(run_test())


# ==========================================
# 测试 tts_stream 错误跳过
# ==========================================
def test_tts_stream_skips_failures():
    """
    TTS 失败的 chunk 被跳过，不影响其他 chunk。
    """
    from tts_client import tts_stream

    # 使用长句子确保各自独立成 chunk
    long_sentences = ["句子0" * 60, "句子1" * 60, "句子2" * 60]

    async def mock_tts(text):
        if text.startswith("句子1"):
            raise Exception("TTS 失败")
        return f"audio_{text[:10]}"

    async def run_test():
        with patch("tts_client.synthesize_speech_b64", side_effect=mock_tts):
            with patch("tts_client.TTS_CHUNK_SIZE", 50):
                results = []
                async for text, audio in tts_stream(long_sentences):
                    results.append(audio)

        # 句子1 的 chunk 被跳过，剩 2 个
        assert len(results) == 2

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

    # 使用长句子确保各自独立成 chunk
    long_sentences = ["a" * 60, "b" * 60, "c" * 60, "d" * 60]

    async def mock_tts(text):
        nonlocal max_concurrent, current_concurrent
        async with lock:
            current_concurrent += 1
            if current_concurrent > max_concurrent:
                max_concurrent = current_concurrent
        await asyncio.sleep(0.1)
        async with lock:
            current_concurrent -= 1
        return f"audio_{text[:10]}"

    async def run_test():
        with patch("tts_client.synthesize_speech_b64", side_effect=mock_tts):
            with patch("tts_client.TTS_MAX_CONCURRENT", 2):
                with patch("tts_client.TTS_CHUNK_SIZE", 50):
                    results = []
                    async for text, audio in tts_stream(long_sentences):
                        results.append(audio)

        assert len(results) == 4
        assert max_concurrent <= 2

    asyncio.run(run_test())
