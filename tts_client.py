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

from config import TTS_SERVER_URL, TTS_SPEAKER, TTS_TIMEOUT, TTS_MAX_CONCURRENT, TTS_CHUNK_SIZE, TTS_PREBUFFER
from sys_logger import setup_global_logger


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()


# ==========================================
# 调用 TTS 服务
# ==========================================
async def synthesize_speech(text: str) -> bytes:
    """
    调用 TTS 服务，将文本合成为语音。

    Args:
        text: 要合成的文本 (str)

    Returns:
        bytes: WAV 格式音频数据

    Raises:
        Exception: TTS 服务不可用、超时或返回错误时抛出
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                TTS_SERVER_URL,
                json={"text": text, "speaker": TTS_SPEAKER},
                timeout=aiohttp.ClientTimeout(total=TTS_TIMEOUT),
            ) as resp:
                if resp.status == 200:
                    audio_bytes = await resp.read()
                    logger.debug(f"TTS 合成完成: text={text[:20]}..., size={len(audio_bytes)} bytes")
                    return audio_bytes
                raise Exception(f"TTS 服务返回状态码 {resp.status}")
    except aiohttp.ClientError as e:
        logger.warning(f"TTS 服务连接失败: {e}")
        raise
    except TimeoutError:
        logger.warning(f"TTS 服务超时 ({TTS_TIMEOUT}s): text={text[:20]}...")
        raise
    except Exception as e:
        logger.warning(f"TTS 合成失败: {e}")
        raise


# ==========================================
# 文本转 base64 音频
# ==========================================
async def synthesize_speech_b64(text: str) -> str:
    """
    调用 TTS 服务，返回 base64 编码的音频数据。

    Args:
        text: 要合成的文本 (str)

    Returns:
        str: base64 编码的 WAV 音频字符串
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
        - 并发数由 TTS_MAX_CONCURRENT 控制
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
    semaphore = asyncio.Semaphore(TTS_MAX_CONCURRENT)

    async def process_one(idx: int, chunk: str):
        """处理单个 chunk 的 TTS"""
        async with semaphore:
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

    # 按序 yield
    for i, chunk in enumerate(chunks):
        while buffer[i] is None:
            await asyncio.sleep(0.05)
        if buffer[i] is not TTS_SKIP:
            yield chunk, buffer[i]

    # 确保所有任务完成（清理）
    await asyncio.gather(*tasks, return_exceptions=True)
