"""
TTS 客户端模块
使用 edge-tts 进行云端语音合成。
"""
import asyncio
import base64
import ssl
from typing import AsyncGenerator

# ==========================================
# Windows SSL 证书加载 bug 修复
# edge-tts 内部依赖 aiohttp，导入时触发 SSL bug。
# 必须在 import edge_tts 之前 patch。
# ==========================================
_orig_load_default_certs = ssl.SSLContext.load_default_certs


def _patched_load_default_certs(self, purpose=ssl.Purpose.SERVER_AUTH):
    import certifi
    self.load_verify_locations(certifi.where())


ssl.SSLContext.load_default_certs = _patched_load_default_certs

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
