# LiveTalking 死锁排查 — 阶段 A 日志观测实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 LiveTalking 关键代码位置添加诊断日志，不改业务逻辑，精确定位死锁时哪个线程卡在哪个队列。

**Architecture:** 新增独立诊断模块 `utils/diag.py`（含诊断 logger + GPU 监控线程），修改 4 个现有文件插入诊断代码。所有诊断日志写入独立文件 `livetalking_diag.log`，用 `[DIAG-*]` 前缀标识。关键是在每个 `queue.get()` / `queue.put()` 处测量等待时间，以发现级联阻塞。

**Tech Stack:** Python threading, torch.cuda, queue.Queue, logging

**项目路径:** `G:\JupyterProject\LiveTalking\`

**关键参数（config.py 默认值）:**
- `batch_size = 16`
- `stride_left_size = 10`（`-l`）
- `stride_right_size = 10`（`-r`）
- `fps = 25`
- `res_frame_queue` maxsize = `batch_size * 2 = 32`
- `feat_queue` maxsize = 2
- `video._queue` maxsize = 100

---

## 文件结构

| 操作 | 文件路径 | 职责 |
|------|----------|------|
| 新建 | `utils/diag.py` | 诊断 logger + GPU 监控线程 |
| 修改 | `avatars/audio_features/whisper.py:58-76` | run_step() 诊断 |
| 修改 | `avatars/base_avatar.py:326-501` | inference() / process_frames() / render() 诊断 |
| 修改 | `avatars/musetalk_avatar.py:130-152` | inference_batch() CUDA 错误捕获 |
| 修改 | `server/webrtc.py:111-152, 190-193` | recv() + push_video() 诊断 |

---

### Task 1: 创建诊断模块 `utils/diag.py`

**Files:**
- Create: `utils/diag.py`

- [ ] **Step 1: 创建 `utils/diag.py`**

```python
###############################################################################
#  LiveTalking 死锁诊断模块
#  独立日志文件 + GPU 监控线程
###############################################################################

import logging
import time
import threading

import torch
from utils.logger import logger as main_logger


# ==========================================
# 诊断专用 logger（写入 livetalking_diag.log）
# ==========================================
def create_diag_logger() -> logging.Logger:
    """
    创建独立的诊断 logger，写入 livetalking_diag.log。
    与主日志 livetalking.log 分离，避免干扰。
    Returns:
        logging.Logger: 诊断专用 logger
    """
    diag_logger = logging.getLogger("livetalking.diag")
    diag_logger.setLevel(logging.DEBUG)
    diag_logger.propagate = False

    # 避免重复添加 handler
    if not diag_logger.handlers:
        formatter = logging.Formatter(
            '%(asctime)s.%(msecs)03d [%(threadName)s] %(message)s',
            datefmt='%H:%M:%S'
        )
        file_handler = logging.FileHandler(
            'livetalking_diag.log', encoding='utf-8'
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        diag_logger.addHandler(file_handler)

    return diag_logger


diag = create_diag_logger()


# ==========================================
# GPU 状态监控守护线程
# ==========================================
class GPUMonitor:
    """
    每 interval 秒采样一次 GPU 状态，写入诊断日志。
    用法: GPUMonitor.start() / GPUMonitor.stop()
    """

    _thread = None
    _stop_event = None

    @staticmethod
    def start(interval: float = 5.0):
        """启动 GPU 监控守护线程。"""
        if GPUMonitor._thread is not None:
            return
        GPUMonitor._stop_event = threading.Event()
        GPUMonitor._thread = threading.Thread(
            target=GPUMonitor._monitor_loop,
            args=(interval,),
            name="GPU-Monitor",
            daemon=True
        )
        GPUMonitor._thread.start()
        diag.info("[DIAG-GPU] monitor started, interval=%.1fs", interval)

    @staticmethod
    def stop():
        """停止 GPU 监控守护线程。"""
        if GPUMonitor._stop_event is not None:
            GPUMonitor._stop_event.set()
        if GPUMonitor._thread is not None:
            GPUMonitor._thread.join(timeout=10)
            GPUMonitor._thread = None
            GPUMonitor._stop_event = None
        diag.info("[DIAG-GPU] monitor stopped")

    @staticmethod
    def _monitor_loop(interval: float):
        """GPU 监控主循环。"""
        while not GPUMonitor._stop_event.is_set():
            try:
                if torch.cuda.is_available():
                    mem_allocated = torch.cuda.memory_allocated() / (1024 ** 2)
                    mem_reserved = torch.cuda.memory_reserved() / (1024 ** 2)
                    mem_max = torch.cuda.max_memory_allocated() / (1024 ** 2)
                    device_name = torch.cuda.get_device_name(0)
                    diag.info(
                        "[DIAG-GPU] alloc=%.0fMB reserved=%.0fMB "
                        "max_alloc=%.0fMB device=%s cuda_ok=True",
                        mem_allocated, mem_reserved, mem_max, device_name
                    )
                else:
                    diag.info("[DIAG-GPU] CUDA not available!")
            except Exception as e:
                diag.error("[DIAG-GPU] sampling error: %s", e)
            GPUMonitor._stop_event.wait(interval)


# ==========================================
# 队列全状态快照（定期输出所有队列大小）
# ==========================================
class QueueSnapshot:
    """
    记录所有队列的状态快照。
    由各线程定期调用，便于在日志中对比各队列的相对大小。
    """

    @staticmethod
    def log(
        asr_queue_size: int = -1,
        output_queue_size: int = -1,
        feat_queue_size: int = -1,
        res_frame_queue_size: int = -1,
        video_queue_size: int = -1,
        frames_len: int = -1,
        extra: str = ""
    ):
        """记录队列状态快照。"""
        parts = ["[DIAG-SNAP]"]
        if asr_queue_size >= 0:
            parts.append(f"asr_q={asr_queue_size}")
        if output_queue_size >= 0:
            parts.append(f"out_q={output_queue_size}")
        if feat_queue_size >= 0:
            parts.append(f"feat_q={feat_queue_size}")
        if res_frame_queue_size >= 0:
            parts.append(f"res_q={res_frame_queue_size}")
        if video_queue_size >= 0:
            parts.append(f"vid_q={video_queue_size}")
        if frames_len >= 0:
            parts.append(f"frames={frames_len}")
        if extra:
            parts.append(extra)
        diag.info(" ".join(parts))
```

- [ ] **Step 2: 验证模块可导入**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from utils.diag import diag, GPUMonitor, QueueSnapshot; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
cd G:\JupyterProject\LiveTalking
git add utils/diag.py
git commit -m "diag: add diagnostic logger, GPU monitor, queue snapshot module"
```

---

### Task 2: `whisper.py` — run_step() 诊断

**Files:**
- Modify: `avatars/audio_features/whisper.py:58-76`

- [ ] **Step 1: 修改 `run_step()` 添加诊断日志**

在 `avatars/audio_features/whisper.py` 顶部添加 import：

```python
import time
import numpy as np

import queue
from queue import Queue
from avatars.audio_features.base_asr import BaseASR
from avatars.musetalk.whisper.audio2feature import Audio2Feature
from utils.diag import diag, QueueSnapshot
```

将 `run_step()` 方法（第 58-76 行）替换为带诊断的版本：

```python
def run_step(self):
    """
    主线程：取音频帧 → Whisper 特征提取 → 放入队列。
    添加了诊断日志，记录每步耗时和队列状态。
    """
    start_time = time.perf_counter()

    # 取 batch_size*2 个音频帧
    for _ in range(self.batch_size * 2):
        audio_frame = self.get_audio_frame()
        self.frames.append(audio_frame.data)
        self.output_queue.put(audio_frame)

    if len(self.frames) <= self.stride_left_size + self.stride_right_size:
        diag.info(
            "[DIAG-RUN_STEP] skip: frames_len=%d <= stride_total=%d",
            len(self.frames), self.stride_left_size + self.stride_right_size
        )
        return

    inputs = np.concatenate(self.frames)

    # Whisper 特征提取（GPU）
    t_feat_start = time.perf_counter()
    whisper_feature = self.audio_processor.audio2feat(inputs)
    t_feat = time.perf_counter() - t_feat_start

    whisper_chunks = self._feature2chunks(
        feature_array=whisper_feature, batch_size=self.batch_size,
        audio_feat_win=[0, 5], start=self.stride_left_size / 2,
        feature_idx_multiplier=2
    )

    # feat_queue 放入（有阻塞风险，maxsize=2）
    t_put_start = time.perf_counter()
    self.feat_queue.put(whisper_chunks)
    t_put = time.perf_counter() - t_put_start

    # 裁剪历史帧
    self.frames = self.frames[-(self.stride_left_size + self.stride_right_size):]

    t_total = time.perf_counter() - start_time

    diag.info(
        "[DIAG-RUN_STEP] frames_len=%d frames_sec=%.2f "
        "concat_len=%d audio2feat=%.3fs feat_put=%.3fs total=%.3fs "
        "feat_q=%d/%d out_q=%d",
        len(self.frames),
        len(self.frames) / 16000.0,
        len(inputs),
        t_feat, t_put, t_total,
        self.feat_queue.qsize(), self.feat_queue.maxsize,
        self.output_queue.qsize()
    )

    # 如果 feat_queue put 阻塞超过 0.1s，输出全队列快照
    if t_put > 0.1:
        QueueSnapshot.log(
            output_queue_size=self.output_queue.qsize(),
            feat_queue_size=self.feat_queue.qsize(),
            frames_len=len(self.frames),
            extra=f"WARN: feat_put blocked for {t_put:.3f}s"
        )
```

- [ ] **Step 2: Commit**

```bash
cd G:\JupyterProject\LiveTalking
git add avatars/audio_features/whisper.py
git commit -m "diag: add run_step() diagnostic logging in whisper.py"
```

---

### Task 3: `base_avatar.py` — inference() 诊断

**Files:**
- Modify: `avatars/base_avatar.py:326-381`

- [ ] **Step 1: 在 `base_avatar.py` 顶部添加 import**

在现有 import 区域（第 20-48 行之后）添加：

```python
from utils.diag import diag, QueueSnapshot
```

- [ ] **Step 2: 修改 `inference()` 方法（第 326-381 行）**

将 `inference()` 方法替换为带诊断的版本：

```python
def inference(self, quit_event):
    """
    推理线程：从 feat_queue 取特征 → 从 output_queue 取音频帧
    → GPU 推理 → 将结果放入 res_frame_queue。
    添加了诊断日志，记录各队列等待时间。
    """
    length = self.get_avatar_length()
    index = 0
    count = 0
    counttime = 0
    last_speaking = False
    total_infer_frames = 0

    logger.info('start inference')
    diag.info("[DIAG-INFER] thread started, batch_size=%d", self.batch_size)

    while not quit_event.is_set():
        starttime = time.perf_counter()

        # ===== 从 feat_queue 取特征（带已有 timeout=1）=====
        t_feat_wait_start = time.perf_counter()
        audiofeat_batch = []
        try:
            audiofeat_batch = self.asr.feat_queue.get(block=True, timeout=1)
        except queue.Empty:
            continue
        t_feat_wait = time.perf_counter() - t_feat_wait_start

        # ===== 从 output_queue 取音频帧（原代码无超时！）=====
        t_output_wait_start = time.perf_counter()
        is_all_silence = True
        audio_frames: list[AudioFrameData] = []
        for i in range(self.batch_size * 2):
            t_single_start = time.perf_counter()
            audioframe: AudioFrameData = self.asr.output_queue.get()
            t_single_wait = time.perf_counter() - t_single_start
            if t_single_wait > 0.1:
                diag.warning(
                    "[DIAG-INFER] output_queue.get(%d) blocked %.3fs! "
                    "out_q=%d",
                    i, t_single_wait, self.asr.output_queue.qsize()
                )
            if audioframe.type == 0:
                is_all_silence = False
            audio_frames.append(audioframe)
        t_output_wait = time.perf_counter() - t_output_wait_start

        # 检测状态变化
        current_speaking = not is_all_silence

        if is_all_silence:
            # 全为静音数据，只需要取 fullimg，不需要推理
            for i in range(self.batch_size):
                idx = mirror_index(length, index)
                t_put_start = time.perf_counter()
                self.res_frame_queue.put((None, audio_frames[i*2:i*2+2], idx))
                t_put = time.perf_counter() - t_put_start
                if t_put > 0.1:
                    diag.warning(
                        "[DIAG-INFER] res_frame_queue.put(silent) blocked %.3fs! "
                        "res_q=%d/%d",
                        t_put,
                        self.res_frame_queue.qsize(),
                        self.res_frame_queue.maxsize
                    )
                index = index + 1
        else:
            if current_speaking and not last_speaking and self.custom_index.get(1) is not None:
                index = 0
            t = time.perf_counter()

            pred = self.inference_batch(index, audiofeat_batch)

            t_infer = time.perf_counter() - t
            counttime += t_infer
            count += self.batch_size
            total_infer_frames += self.batch_size

            if count >= 100:
                logger.info(f"------actual avg infer fps:{count/counttime:.4f}")
                count = 0
                counttime = 0

            for i, res_frame in enumerate(pred):
                t_put_start = time.perf_counter()
                self.res_frame_queue.put(
                    (res_frame, audio_frames[i*2:i*2+2], mirror_index(length, index))
                )
                t_put = time.perf_counter() - t_put_start
                if t_put > 0.1:
                    diag.warning(
                        "[DIAG-INFER] res_frame_queue.put(speak) blocked %.3fs! "
                        "res_q=%d/%d vid_q=%d",
                        t_put,
                        self.res_frame_queue.qsize(),
                        self.res_frame_queue.maxsize,
                        self.output.get_buffer_size() if hasattr(self.output, 'get_buffer_size') else -1
                    )
                index = index + 1

        if current_speaking != last_speaking:
            logger.info(
                f"inference 状态切换：{'说话' if last_speaking else '静音'} "
                f"→ {'说话' if current_speaking else '静音'}"
            )
            last_speaking = current_speaking

        # 每 20 次循环输出一次诊断摘要
        total_loop_time = time.perf_counter() - starttime
        if total_infer_frames % 20 == 0 and total_infer_frames > 0:
            diag.info(
                "[DIAG-INFER] feat_wait=%.3fs output_wait=%.3fs "
                "infer_time=%.3fs loop_total=%.3fs "
                "feat_q=%d out_q=%d res_q=%d/%d total_frames=%d",
                t_feat_wait, t_output_wait,
                t_infer if not is_all_silence else 0,
                total_loop_time,
                self.asr.feat_queue.qsize(),
                self.asr.output_queue.qsize(),
                self.res_frame_queue.qsize(),
                self.res_frame_queue.maxsize,
                total_infer_frames
            )

    logger.info('baseavatar inference thread stop')
    diag.info("[DIAG-INFER] thread stopped, total_infer_frames=%d", total_infer_frames)
```

- [ ] **Step 3: Commit**

```bash
cd G:\JupyterProject\LiveTalking
git add avatars/base_avatar.py
git commit -m "diag: add inference() diagnostic logging in base_avatar.py"
```

---

### Task 4: `base_avatar.py` — process_frames() 诊断

**Files:**
- Modify: `avatars/base_avatar.py:383-467`

- [ ] **Step 1: 修改 `process_frames()` 方法（第 383-467 行）**

将 `process_frames()` 替换为带诊断的版本：

```python
def process_frames(self, quit_event):
    """
    帧处理线程：从 res_frame_queue 取推理结果 → 合成最终帧
    → 通过 output 推送到 video._queue / audio._queue。
    添加了诊断日志，重点监控 push_video_frame 是否阻塞。
    """
    enable_transition = False

    _last_speaking = False
    _transition_start = time.time()

    total_proc_frames = 0

    self.output.start()
    diag.info("[DIAG-PROC] thread started")

    while not quit_event.is_set():
        t_loop_start = time.perf_counter()

        try:
            audio_frames: list[AudioFrameData]
            res_frame, audio_frames, idx = self.res_frame_queue.get(block=True, timeout=1)
        except queue.Empty:
            continue

        t_res_wait = time.perf_counter() - t_loop_start

        # 检测状态变化
        current_speaking = not (audio_frames[0].type != 0 and audio_frames[1].type != 0)
        if current_speaking != _last_speaking:
            logger.info(
                f"状态切换：{'说话' if _last_speaking else '静音'} "
                f"→ {'说话' if current_speaking else '静音'}"
            )
            _transition_start = time.time()
        _last_speaking = current_speaking

        if audio_frames[0].type != 0 and audio_frames[1].type != 0:
            # 全为静音数据
            self.speaking = False
            audiotype = audio_frames[0].type
            if self.custom_index.get(audiotype) is not None:
                mirindex = mirror_index(
                    len(self.custom_img_cycle[audiotype]),
                    self.custom_index[audiotype]
                )
                target_frame = self.custom_img_cycle[audiotype][mirindex]
                self.custom_index[audiotype] += 1
            else:
                target_frame = self.frame_list_cycle[idx]

            if enable_transition:
                if time.time() - _transition_start < _transition_duration and _last_speaking_frame is not None:
                    alpha = min(1.0, (time.time() - _transition_start) / _transition_duration)
                    combine_frame = cv2.addWeighted(_last_speaking_frame, 1-alpha, target_frame, alpha, 0)
                else:
                    combine_frame = target_frame
                _last_silent_frame = combine_frame.copy()
            else:
                combine_frame = target_frame
        else:
            self.speaking = True
            try:
                t_paste_start = time.perf_counter()
                current_frame = self.paste_back_frame(res_frame, idx)
                t_paste = time.perf_counter() - t_paste_start
            except Exception as e:
                logger.warning(f"paste_back_frame error: {e}")
                continue

            if enable_transition:
                if time.time() - _transition_start < _transition_duration and _last_silent_frame is not None:
                    alpha = min(1.0, (time.time() - _transition_start) / _transition_duration)
                    combine_frame = cv2.addWeighted(_last_silent_frame, 1-alpha, current_frame, alpha, 0)
                else:
                    combine_frame = current_frame
                _last_speaking_frame = combine_frame.copy()
            else:
                combine_frame = current_frame

        cv2.putText(
            combine_frame, "LiveTalking", (10, 20),
            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (128, 128, 128), 1
        )

        # ===== 关键：推送视频帧（可能阻塞！）=====
        vid_q_before = self.output.get_buffer_size() if hasattr(self.output, 'get_buffer_size') else -1
        t_push_start = time.perf_counter()
        self.output.push_video_frame(combine_frame)
        t_push_video = time.perf_counter() - t_push_start
        vid_q_after = self.output.get_buffer_size() if hasattr(self.output, 'get_buffer_size') else -1

        if t_push_video > 0.05:
            diag.warning(
                "[DIAG-PROC] push_video_frame BLOCKED %.3fs! "
                "vid_q before=%d after=%d",
                t_push_video, vid_q_before, vid_q_after
            )

        self.record_video_data(combine_frame)

        for audio_frame in audio_frames:
            frame = (audio_frame.data * 32767).astype(np.int16)
            self.output.push_audio_frame(frame, audio_frame.userdata)
            self.record_audio_data(frame)

        total_proc_frames += 1

        # 每 20 帧输出一次诊断摘要
        if total_proc_frames % 20 == 0:
            t_loop = time.perf_counter() - t_loop_start
            diag.info(
                "[DIAG-PROC] total_frames=%d res_wait=%.3fs "
                "push_video=%.3fs vid_q=%d res_q=%d/%d",
                total_proc_frames, t_res_wait, t_push_video,
                vid_q_after,
                self.res_frame_queue.qsize(),
                self.res_frame_queue.maxsize
            )

    self.output.stop()
    logger.info('baseavatar process_frames thread stop')
    diag.info("[DIAG-PROC] thread stopped, total_frames=%d", total_proc_frames)
```

- [ ] **Step 2: Commit**

```bash
cd G:\JupyterProject\LiveTalking
git add avatars/base_avatar.py
git commit -m "diag: add process_frames() diagnostic logging in base_avatar.py"
```

---

### Task 5: `base_avatar.py` — render() 诊断 + GPU 监控启动

**Files:**
- Modify: `avatars/base_avatar.py:469-501`

- [ ] **Step 1: 修改 `render()` 方法（第 469-501 行）**

```python
def render(self, quit_event):
    """
    主渲染循环：启动 TTS/推理/帧处理线程，循环调用 run_step()。
    添加了诊断日志和 GPU 监控启动。
    """
    self.quit_event = quit_event

    self.init_customindex()
    self.tts.render(quit_event)

    # 启动 GPU 监控
    from utils.diag import GPUMonitor
    GPUMonitor.start(interval=5.0)

    infer_quit_event = mp.Event()
    infer_thread = Thread(target=self.inference, args=(infer_quit_event,))
    infer_thread.start()

    process_quit_event = Event()
    process_thread = Thread(target=self.process_frames, args=(process_quit_event,))
    process_thread.start()

    count = 0
    totaltime = 0
    _starttime = time.perf_counter()
    _totalframe = 0
    diag.info("[DIAG-RENDER] main loop started")

    while not quit_event.is_set():
        t = time.perf_counter()
        self.asr.run_step()
        t_step = time.perf_counter() - t

        buffer_size = self.output.get_buffer_size() if hasattr(self.output, 'get_buffer_size') else 0
        if buffer_size >= 5:
            sleep_time = 0.04 * buffer_size * 0.8
            diag.info(
                "[DIAG-RENDER] sleeping %.3fs buffer_size=%d "
                "step_time=%.3fs",
                sleep_time, buffer_size, t_step
            )
            time.sleep(sleep_time)

        _totalframe += 1

        # 每 50 次循环输出一次 render 诊断
        if _totalframe % 50 == 0:
            elapsed = time.perf_counter() - _starttime
            diag.info(
                "[DIAG-RENDER] loop_count=%d elapsed=%.1fs "
                "avg_step=%.3fs buffer_size=%d",
                _totalframe, elapsed,
                elapsed / _totalframe if _totalframe > 0 else 0,
                buffer_size
            )

    logger.info('baseavatar render thread stop')
    diag.info("[DIAG-RENDER] main loop stopped")

    infer_quit_event.set()
    infer_thread.join()

    process_quit_event.set()
    process_thread.join()

    # 停止 GPU 监控
    GPUMonitor.stop()
```

- [ ] **Step 2: Commit**

```bash
cd G:\JupyterProject\LiveTalking
git add avatars/base_avatar.py
git commit -m "diag: add render() diagnostic + GPU monitor start/stop"
```

---

### Task 6: `musetalk_avatar.py` — inference_batch() CUDA 错误捕获

**Files:**
- Modify: `avatars/musetalk_avatar.py:130-152`

- [ ] **Step 1: 修改 `inference_batch()` 添加 CUDA 错误捕获**

在 `avatars/musetalk_avatar.py` 顶部添加 import：

```python
from utils.diag import diag
```

将 `inference_batch()` 方法（第 130-152 行）替换为：

```python
def inference_batch(self, index, audiofeat_batch):
    """
    一个 batch 的 GPU 推理。
    添加了 CUDA 错误捕获和诊断日志。
    Args:
        index: 当前帧在 avatar 中的索引
        audiofeat_batch: 音频特征 batch
    Returns:
        pred: 推理结果（latent 解码后的帧）
    Raises:
        RuntimeError: CUDA 错误时抛出，不再静默吞掉
    """
    length = len(self.input_latent_list_cycle)
    whisper_batch = np.stack(audiofeat_batch)
    latent_batch = []
    for i in range(self.batch_size):
        idx = mirror_index(length, index + i)
        latent = self.input_latent_list_cycle[idx]
        latent_batch.append(latent)
    latent_batch = torch.cat(latent_batch, dim=0)

    audio_feature_batch = torch.from_numpy(whisper_batch)
    audio_feature_batch = audio_feature_batch.to(
        device=self.unet.device, dtype=self.unet.model.dtype
    )
    audio_feature_batch = self.pe(audio_feature_batch)
    latent_batch = latent_batch.to(dtype=self.unet.model.dtype)

    t_start = time.perf_counter()
    try:
        pred_latents = self.unet.model(
            latent_batch, self.timesteps,
            encoder_hidden_states=audio_feature_batch
        ).sample
        t_unet = time.perf_counter() - t_start

        t_vae_start = time.perf_counter()
        pred = self.vae.decode_latents(pred_latents)
        t_vae = time.perf_counter() - t_vae_start

        diag.info(
            "[DIAG-INFER_BATCH] unet=%.3fs vae=%.3fs total=%.3fs "
            "index=%d batch=%d",
            t_unet, t_vae, t_unet + t_vae,
            index, self.batch_size
        )
    except RuntimeError as e:
        diag.error(
            "[DIAG-INFER_BATCH] CUDA/Runtime error: %s", e
        )
        # 尝试同步 CUDA 以确认错误状态
        try:
            torch.cuda.synchronize()
        except Exception as sync_err:
            diag.error("[DIAG-INFER_BATCH] cuda sync also failed: %s", sync_err)
        raise

    return pred
```

- [ ] **Step 2: Commit**

```bash
cd G:\JupyterProject\LiveTalking
git add avatars/musetalk_avatar.py
git commit -m "diag: add CUDA error capture and timing in inference_batch()"
```

---

### Task 7: `server/webrtc.py` — recv() + push_video() 诊断

**Files:**
- Modify: `server/webrtc.py:111-152`（recv）, `server/webrtc.py:190-193`（push_video）

- [ ] **Step 1: 在 `server/webrtc.py` 顶部添加 import**

在现有 import 区域添加：

```python
from utils.diag import diag
```

- [ ] **Step 2: 修改 `recv()` 方法（第 111-152 行）**

将 `recv()` 方法中 video 部分的 FPS 统计逻辑（第 144-151 行）修改为：

```python
if self.kind == 'video':
    self.totaltime += (time.perf_counter() - self.lasttime)
    self.framecount += 1
    self.lasttime = time.perf_counter()
    if self.framecount % 50 == 0:
        avg_fps = self.framecount / self.totaltime if self.totaltime > 0 else 0
        diag.info(
            "[DIAG-RECV] frame=%d avg_fps=%.2f queue_size=%d "
            "maxsize=%d",
            self.framecount, avg_fps,
            self._queue.qsize(), self._queue.maxsize
        )
        # 重置计数器（每 50 帧一次快照）
        self.framecount = 0
        self.totaltime = 0
```

- [ ] **Step 3: 修改 `push_video()` 方法（第 190-193 行）**

将 `HumanPlayer.push_video()` 替换为带诊断的版本：

```python
def push_video(self, frame):
    """
    推送视频帧到 video._queue。
    添加了诊断日志：如果队列接近满，输出警告。
    """
    from av import VideoFrame
    new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
    qsize = self.__video._queue.qsize()
    maxsize = self.__video._queue.maxsize
    if qsize >= maxsize * 0.8:
        diag.warning(
            "[DIAG-PUSH_VIDEO] queue nearly full! qsize=%d/%d",
            qsize, maxsize
        )
    self.__video._queue.put((new_frame, None))
```

- [ ] **Step 4: Commit**

```bash
cd G:\JupyterProject\LiveTalking
git add server/webrtc.py
git commit -m "diag: add recv() FPS logging and push_video() queue size warnings"
```

---

### Task 8: 端到端验证

**Files:** 无新文件，验证所有修改

- [ ] **Step 1: 确认所有修改的语法正确**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from utils.diag import diag, GPUMonitor, QueueSnapshot; from avatars.audio_features.whisper import WhisperASR; print('whisper OK')"
```

Expected: `whisper OK`

- [ ] **Step 2: 验证 base_avatar 可导入**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from avatars.base_avatar import BaseAvatar; print('base_avatar OK')"
```

Expected: `base_avatar OK`

- [ ] **Step 3: 验证 musetalk_avatar 可导入**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from avatars.musetalk_avatar import MuseReal; print('musetalk_avatar OK')"
```

Expected: `musetalk_avatar OK`

- [ ] **Step 4: 验证 webrtc 可导入**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from server.webrtc import HumanPlayer, PlayerStreamTrack; print('webrtc OK')"
```

Expected: `webrtc OK`

- [ ] **Step 5: Commit 所有修改（如有遗漏）**

```bash
cd G:\JupyterProject\LiveTalking
git add -A
git status
git commit -m "diag: complete phase A - all diagnostic logging in place"
```

---

### Task 9: 运行测试 + 收集日志

- [ ] **Step 1: 启动 LiveTalking 服务**

```bash
set PYTHONPATH=G:\JupyterProject\LiveTalking
cd G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe app.py --model musetalk --avatar_id musetalk_avatar1 --transport webrtc --listenport 8010
```

- [ ] **Step 2: 打开浏览器测试**

打开 `http://127.0.0.1:8010/webrtcapi.html`，点击连接，输入一段 50 字文本触发数字人说话。

- [ ] **Step 3: 收集诊断日志**

等待运行结束后，查看 `livetalking_diag.log` 文件内容。重点关注：

1. `[DIAG-RUN_STEP]` — `audio2feat` 耗时是否递增？`feat_put` 是否 > 0.1s？
2. `[DIAG-INFER]` — `output_wait` 是否很长？`res_frame_queue` 是否满？
3. `[DIAG-PROC]` — `push_video` 是否 BLOCKED？`vid_q` 是否接近 100？
4. `[DIAG-RECV]` — `avg_fps` 是否逐渐下降？
5. `[DIAG-INFER_BATCH]` — `unet` / `vae` 耗时是否递增？有无 CUDA error？
6. `[DIAG-GPU]` — 显存是否持续增长？
7. `[DIAG-RENDER]` — `buffer_size` 是否长时间 ≥ 5？

- [ ] **Step 4: 分析日志确定死锁点**

根据日志内容判断：
- 如果 `push_video` BLOCKED → **级联死锁链**（Task 7 的警告触发）
- 如果 `feat_put` > 0.1s → **feat_queue 瓶颈**
- 如果 `audio2feat` 耗时递增 → **self.frames 膨胀**
- 如果 CUDA error 出现 → **GPU 推理异常**

- [ ] **Step 5: 进入阶段 C 压力测试（根据 A 结果）**

用不同长度文本（10/30/50/100 字）重复测试，确认死锁阈值。

- [ ] **Step 6: 进入阶段 B 修复（根据 C 结果）**

根据诊断结论，按设计文档 B1-B4 优先级实施修复。
