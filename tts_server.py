"""
TTS 独立服务模块
封装 CosyVoice-300M-SFT 模型，提供 HTTP API 进行语音合成。
使用请求队列 + 多 Worker 并发架构，充分利用 GPU 算力。
启动方式: python tts_server.py
端口: 9233
"""
import asyncio
import io
import os
import sys
import time

import numpy as np
import soundfile as sf
from fastapi import FastAPI
from fastapi.responses import Response
from pydantic import BaseModel
import uvicorn

from config import TTS_MAX_CONCURRENT
from sys_logger import setup_global_logger


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()

# 将 CosyVoice 项目目录加入 Python path
COSYVOICE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "CosyVoice")
MATCHA_TTS_DIR = os.path.join(COSYVOICE_DIR, "third_party", "Matcha-TTS")
if COSYVOICE_DIR not in sys.path:
    sys.path.insert(0, COSYVOICE_DIR)
if MATCHA_TTS_DIR not in sys.path:
    sys.path.insert(0, MATCHA_TTS_DIR)


# ==========================================
# 全局状态
# ==========================================
model = None
model_status = "loading"


# ==========================================
# 加载模型
# ==========================================
def load_model():
    """加载 CosyVoice-300M-SFT 模型到 GPU"""
    global model, model_status

    model_path = os.path.join(COSYVOICE_DIR, "pretrained_models", "CosyVoice-300M-SFT")
    logger.info(f"加载 CosyVoice 模型: {model_path}")

    t0 = time.time()
    try:
        from cosyvoice.cli.cosyvoice import CosyVoice
        model = CosyVoice(model_path)
        elapsed = time.time() - t0
        model_status = "ready"
        logger.info(f"CosyVoice 模型加载完成: 耗时 {elapsed:.1f}s, 音色: {model.list_available_spks()}")
    except Exception as e:
        model_status = "error"
        logger.error(f"CosyVoice 模型加载失败: {e}")


# ==========================================
# numpy 音频转 WAV bytes
# ==========================================
def numpy_to_wav(audio_np: np.ndarray, sample_rate: int = 22050) -> bytes:
    """
    将 numpy 音频数组转为 WAV 格式的 bytes。

    Args:
        audio_np: numpy 音频数组 (np.ndarray)，float32 范围 [-1, 1]
        sample_rate: 采样率 (int)

    Returns:
        bytes: WAV 格式的音频数据
    """
    buf = io.BytesIO()
    sf.write(buf, audio_np, sample_rate, format="WAV", subtype="PCM_16")
    buf.seek(0)
    return buf.read()


# ==========================================
# 同步推理函数（在线程池中运行）
# ==========================================
def run_inference(text: str, speaker: str) -> bytes:
    """
    调用 CosyVoice 模型进行语音合成（同步函数）。
    在 tts_worker 中通过 asyncio.to_thread() 调用。

    Args:
        text: 要合成的文本 (str)
        speaker: 音色名称 (str)

    Returns:
        bytes: WAV 格式音频数据

    Raises:
        RuntimeError: 模型未就绪
        Exception: 推理失败
    """
    if model_status != "ready" or model is None:
        raise RuntimeError("模型未就绪")

    audio_chunks = []
    for chunk in model.inference_sft(text, speaker):
        audio_chunks.append(chunk["tts_speech"].numpy().flatten())

    if not audio_chunks:
        raise RuntimeError("合成失败：无音频输出")

    audio_np = np.concatenate(audio_chunks)
    return numpy_to_wav(audio_np, sample_rate=model.sample_rate)


# ==========================================
# TTS 请求队列 & Job
# ==========================================
request_queue = asyncio.Queue()
semaphore = asyncio.Semaphore(TTS_MAX_CONCURRENT)


class TTSJob:
    """TTS 请求任务"""
    def __init__(self, text: str, speaker: str, future: asyncio.Future):
        self.text = text
        self.speaker = speaker
        self.future = future


# ==========================================
# 后台 Worker（多 Worker 并发，信号量控制 GPU 占用）
# ==========================================
async def tts_worker(worker_id: int):
    """
    后台 worker 协程。
    从 request_queue 中逐个取出请求，通过信号量控制 GPU 并发数。
    多个 worker 同时运行，但同时最多 TTS_MAX_CONCURRENT 个在执行推理。
    """
    logger.info(f"TTS worker #{worker_id} 启动")
    while True:
        job = await request_queue.get()
        try:
            async with semaphore:
                logger.info(f"Worker #{worker_id} 处理: text={job.text[:20]}...")
                wav_bytes = await asyncio.to_thread(run_inference, job.text, job.speaker)
            if not job.future.done():
                job.future.set_result(wav_bytes)
        except Exception as e:
            logger.error(f"Worker #{worker_id} 错误: {e}")
            if not job.future.done():
                job.future.set_exception(e)


# ==========================================
# Pydantic 请求模型
# ==========================================
class TTSRequest(BaseModel):
    """TTS 请求参数"""
    text: str
    speaker: str = "中文女"


# ==========================================
# FastAPI 应用
# ==========================================
app = FastAPI(title="Lisa TTS Service")


# ==========================================
# 启动时创建多个 Worker
# ==========================================
@app.on_event("startup")
async def startup():
    """启动时创建 TTS_MAX_CONCURRENT 个后台 worker"""
    for i in range(TTS_MAX_CONCURRENT):
        asyncio.create_task(tts_worker(i))
    logger.info(f"启动 {TTS_MAX_CONCURRENT} 个 TTS workers")


# ==========================================
# 健康检查
# ==========================================
@app.get("/health")
async def health():
    """健康检查端点"""
    return {
        "status": model_status,
        "queue_size": request_queue.qsize(),
        "workers": TTS_MAX_CONCURRENT,
    }


# ==========================================
# TTS 合成端点
# ==========================================
@app.post("/tts")
async def tts(request: TTSRequest):
    """
    语音合成端点。
    接收请求 → 放入队列 → 等待 worker 处理 → 返回音频。
    """
    if model_status != "ready" or model is None:
        return Response(
            content='{"error": "模型未就绪"}',
            media_type="application/json",
            status_code=503,
        )

    if not request.text or not request.text.strip():
        return Response(
            content='{"error": "文本不能为空"}',
            media_type="application/json",
            status_code=400,
        )

    t0 = time.time()
    try:
        logger.info(f"TTS 请求入队: text={request.text[:30]}..., speaker={request.speaker}")

        # 创建 Future，放入队列等待 worker 处理
        loop = asyncio.get_event_loop()
        future = loop.create_future()
        job = TTSJob(text=request.text, speaker=request.speaker, future=future)
        await request_queue.put(job)

        # 等待 worker 返回结果
        wav_bytes = await future

        elapsed = time.time() - t0
        logger.info(f"TTS 合成完成: duration={elapsed:.1f}s, size={len(wav_bytes)} bytes")

        return Response(content=wav_bytes, media_type="audio/wav")

    except Exception as e:
        elapsed = time.time() - t0
        logger.error(f"TTS 合成异常 ({elapsed:.1f}s): {e}")
        return Response(
            content=f'{{"error": "合成异常: {str(e)[:100]}"}}',
            media_type="application/json",
            status_code=500,
        )


# ==========================================
# 启动入口
# ==========================================
if __name__ == "__main__":
    # 启动时加载模型
    load_model()

    # 启动 FastAPI 服务
    uvicorn.run(app, host="127.0.0.1", port=9233)
