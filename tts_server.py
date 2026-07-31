"""
TTS 独立服务模块
封装 CosyVoice-300M-SFT 模型，提供 HTTP API 进行语音合成。
每个 Worker 持有独立 model 实例，实现真正并行推理。
启动方式: python tts_server.py
端口: 9233
"""
import asyncio
import io
import os
import sys
import time
import threading

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
# 模型路径
# ==========================================
MODEL_PATH = os.path.join(COSYVOICE_DIR, "pretrained_models", "CosyVoice-300M-SFT")


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
# 同步推理函数（接收 model 参数）
# ==========================================
def run_inference(model_instance, text: str, speaker: str) -> bytes:
    """
    调用 CosyVoice 模型进行语音合成（同步函数）。

    Args:
        model_instance: CosyVoice 模型实例
        text: 要合成的文本 (str)
        speaker: 音色名称 (str)

    Returns:
        bytes: WAV 格式音频数据

    Raises:
        RuntimeError: 推理失败
    """
    audio_chunks = []
    for chunk in model_instance.inference_sft(text, speaker):
        audio_chunks.append(chunk["tts_speech"].numpy().flatten())

    if not audio_chunks:
        raise RuntimeError("合成失败：无音频输出")

    audio_np = np.concatenate(audio_chunks)
    return numpy_to_wav(audio_np, sample_rate=model_instance.sample_rate)


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
# 加载单个模型实例
# ==========================================
def load_one_model(worker_id: int):
    """
    加载一个 CosyVoice 模型实例（在线程中运行）。

    Args:
        worker_id: worker 编号，用于日志

    Returns:
        CosyVoice 模型实例
    """
    logger.info(f"Worker #{worker_id} 加载模型...")
    t0 = time.time()
    from cosyvoice.cli.cosyvoice import CosyVoice
    model_instance = CosyVoice(MODEL_PATH)
    elapsed = time.time() - t0
    logger.info(f"Worker #{worker_id} 模型加载完成: 耗时 {elapsed:.1f}s")
    return model_instance


# ==========================================
# 后台 Worker（每个 worker 持有独立 model 实例）
# ==========================================
async def tts_worker(worker_id: int):
    """
    后台 worker 协程。
    每个 worker 持有独立的 model 实例，实现真正并行推理。
    通过信号量控制 GPU 并发数，防止 VRAM 溢出。
    """
    # 在线程中加载模型（避免阻塞事件循环）
    model_instance = await asyncio.to_thread(load_one_model, worker_id)

    # 更新加载计数
    global models_loaded_count, all_models_ready
    with models_loaded_lock:
        models_loaded_count += 1
        if models_loaded_count >= TTS_MAX_CONCURRENT:
            all_models_ready = True
            logger.info(f"所有 {TTS_MAX_CONCURRENT} 个模型加载完成")

    logger.info(f"TTS worker #{worker_id} 就绪 ({models_loaded_count}/{TTS_MAX_CONCURRENT})")

    while True:
        job = await request_queue.get()
        try:
            async with semaphore:
                logger.info(f"Worker #{worker_id} 处理: text={job.text[:20]}...")
                wav_bytes = await asyncio.to_thread(
                    run_inference, model_instance, job.text, job.speaker
                )
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

# 模型就绪状态（所有 worker 模型都加载完才为 True）
all_models_ready = False
models_loaded_count = 0
models_loaded_lock = threading.Lock()


# ==========================================
# 启动时创建多个 Worker（每个加载独立模型）
# ==========================================
@app.on_event("startup")
async def startup():
    """启动时创建 TTS_MAX_CONCURRENT 个 worker，每个加载独立模型"""
    global all_models_ready

    for i in range(TTS_MAX_CONCURRENT):
        asyncio.create_task(tts_worker(i))

    # 等待所有模型加载完成（最多等 120s）
    # 用健康检查来判断
    logger.info(f"启动 {TTS_MAX_CONCURRENT} 个 TTS workers（独立模型实例）")


# ==========================================
# 健康检查
# ==========================================
@app.get("/health")
async def health():
    """健康检查端点"""
    return {
        "status": "ready" if all_models_ready else "loading",
        "queue_size": request_queue.qsize(),
        "workers": TTS_MAX_CONCURRENT,
        "models_loaded": models_loaded_count,
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
    if not all_models_ready:
        return Response(
            content='{"error": "模型加载中，请稍后"}',
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
    # 启动 FastAPI 服务（模型由 worker 在 startup 时加载）
    uvicorn.run(app, host="127.0.0.1", port=9233)
