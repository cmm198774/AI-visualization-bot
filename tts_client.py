"""
TTS 客户端模块
调用独立 TTS 服务进行语音合成。
"""
import base64
import ssl

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

from config import TTS_SERVER_URL, TTS_SPEAKER, TTS_TIMEOUT
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
