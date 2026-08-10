# LiveTalking 死锁排查设计文档

**日期**: 2026-08-10
**状态**: 设计中
**问题**: LiveTalking 推理 ~100 帧后 FPS 从 25 降到 9.37 并卡死

---

## 1. 问题描述

### 现象
- LiveTalking WebRTC 连接成功，视频画面初始正常
- FPS 从 25 逐渐降到 9.37，最终完全停止
- 日志停止更新，程序不崩溃但无响应
- 设置 `PYTORCH_ALLOC_CONF=expandable_segments:True` 后 FPS 恢复到 25，但约 100 帧后仍卡死

### 环境
- GPU: RTX 5090D（17GB 显存空闲时仍死锁）
- OS: Windows 11
- Python: py310 (Anaconda)
- PyTorch: 2.10.0+cu128
- TTS: edge-tts（云端合成，速度快，音频一次性到达）
- 传输模式: WebRTC 本地直连

### 已排除
- GPU 显存不足（17GB 空闲）
- GPU 频率异常（2595MHz 正常）
- 虚拟内存不足

---

## 2. 线程架构分析

### 2.1 四线程模型

LiveTalking 运行时存在 4 个主要线程 + 1 个 asyncio 事件循环：

```
┌──────────────────────────────────────────────────────────────────────────┐
│                         LiveTalking 线程架构                             │
├──────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  [线程1: TTS] process_tts()                                              │
│      │                                                                   │
│      │ txt_to_audio() → edge-tts 生成 PCM 音频                          │
│      ▼                                                                   │
│  ┌─────────────────────────┐                                             │
│  │ asr.queue (无界 Queue)   │                                             │
│  └──────────┬──────────────┘                                             │
│             │                                                            │
│             ▼                                                            │
│  [线程2: 主线程] render() 循环 → asr.run_step()                          │
│      │                                                                   │
│      │ 1. 取 batch_size*2 个音频帧                                       │
│      │ 2. np.concatenate(self.frames)  ← 持续增长!                      │
│      │ 3. audio_processor.audio2feat(inputs)  ← Whisper 推理(GPU)       │
│      │ 4. _feature2chunks()                                             │
│      ▼                                                                   │
│  ┌─────────────────────────┐   ┌──────────────────────────────┐         │
│  │ feat_queue (maxsize=2)  │   │ output_queue (无界 Queue)     │         │
│  └──────────┬──────────────┘   └──────────────┬───────────────┘         │
│             │                                  │                         │
│             ▼                                  ▼                         │
│  [线程3: 推理] inference()                                              │
│      │                                                                   │
│      │ 1. feat_queue.get() → audiofeat_batch                            │
│      │ 2. output_queue.get() × batch_size*2 (无超时!)                   │
│      │ 3. inference_batch() → UNet + VAE decode (GPU)                   │
│      ▼                                                                   │
│  ┌─────────────────────────────────┐                                    │
│  │ res_frame_queue (maxsize=B*2)   │                                    │
│  └──────────┬──────────────────────┘                                    │
│             │                                                            │
│             ▼                                                            │
│  [线程4: 帧处理] process_frames()                                        │
│      │                                                                   │
│      │ 1. res_frame_queue.get() → combine_frame                         │
│      │ 2. output.push_video_frame() → video._queue (maxsize=100)       │
│      │ 3. output.push_audio_frame() → audio._queue (无界)              │
│      ▼                                                                   │
│  [asyncio] WebRTC recv()                                                │
│      │                                                                   │
│      │ video._queue.get_nowait() → 发送给浏览器                         │
│      ▼                                                                   │
│  浏览器                                                                 │
└──────────────────────────────────────────────────────────────────────────┘
```

### 2.2 五个队列状态

| 队列 | 位置 | 容量 | 生产者 | 消费者 |
|------|------|------|--------|--------|
| `asr.queue` | `base_asr.py:37` | 无界 | TTS 线程 | 主线程(run_step) |
| `asr.output_queue` | `base_asr.py:38` | 无界 | 主线程(run_step) | 推理线程(inference) |
| `asr.feat_queue` | `base_asr.py:46` | maxsize=2 | 主线程(run_step) | 推理线程(inference) |
| `res_frame_queue` | `base_avatar.py:86` | maxsize=batch_size*2 | 推理线程(inference) | 帧处理线程(process_frames) |
| `video._queue` | `webrtc.py:58` | maxsize=100 | 帧处理线程(process_frames) | asyncio(recv) |

### 2.3 关键代码位置

| 文件 | 行号 | 函数 | 说明 |
|------|------|------|------|
| `avatars/audio_features/whisper.py` | 58-76 | `run_step()` | 主线程音频特征提取 |
| `avatars/base_avatar.py` | 326-381 | `inference()` | 推理线程主循环 |
| `avatars/base_avatar.py` | 383-467 | `process_frames()` | 帧处理线程主循环 |
| `avatars/base_avatar.py` | 469-501 | `render()` | 主线程渲染循环 |
| `server/webrtc.py` | 111-152 | `recv()` | WebRTC 帧发送 |
| `avatars/musetalk_avatar.py` | 130-152 | `inference_batch()` | UNet + VAE GPU 推理 |

---

## 3. 五个可疑死锁点

### 可疑点 1 🔴：`self.frames` 无限增长（最可能）

**位置**: `whisper.py:76`
**代码**: `self.frames = self.frames[-(self.stride_left_size + self.stride_right_size):]`
**问题**:
- `run_step()` 每次追加 `batch_size*2` 个音频帧到 `self.frames`
- 裁剪保留 `stride_left_size + stride_right_size` 个历史帧
- 但如果 `stride_left_size + stride_right_size` 很大，保留的历史数据仍然很多
- 随着运行时间增长，`self.frames` 越来越大
- `np.concatenate(self.frames)` 和 `audio2feat(inputs)` 耗时线性增长
- 最终主线程卡在 `audio2feat()` 上，无法往 `feat_queue` 放数据
- 推理线程等待 `feat_queue` 超时 → 整个管线饥饿

**验证方法**: 打印每次 `run_step()` 后 `self.frames` 的长度和 `audio2feat()` 耗时

### 可疑点 2 🟠：`output_queue.get()` 无超时

**位置**: `base_avatar.py:348`
**代码**: `audioframe = self.asr.output_queue.get()` (无 block/timeout 参数)
**问题**:
- `inference()` 循环中，从 `output_queue` 取 `batch_size*2` 个帧
- 如果主线程 `run_step()` 阻塞在 `audio2feat()` 上
- `output_queue` 得不到新数据，但 `inference()` 的 `get()` 没有超时
- 推理线程永远阻塞在此处

**验证方法**: 改为 `get(block=True, timeout=5)` 并记录超时次数

### 可疑点 3 🟠：`video._queue` 满导致级联阻塞

**位置**: `webrtc.py:58`, `streamout/webrtc.py:28-29`
**代码**: `self._player.push_video(frame)` → `self.__video._queue.put((new_frame, None))`
**问题**:
- `video._queue` maxsize=100
- 如果 WebRTC 消费速度 < 生产速度（例如浏览器卡顿、网络延迟）
- `push_video_frame()` 阻塞 → `process_frames` 阻塞 → `res_frame_queue` 满 → `inference` 阻塞
- 形成级联阻塞链

**验证方法**: 在 `push_video_frame` 前打印 `video._queue.qsize()`

### 可疑点 4 🟠：CUDA 错误被静默吞掉

**位置**: `musetalk_avatar.py:148-152`
**问题**:
- `inference_batch()` 调用 UNet 和 VAE 进行 GPU 推理
- 如果发生 CUDA 错误（如 OOM、非法内存访问），异常在子线程中被静默吞掉
- 推理线程无声死亡 → `res_frame_queue` 不再有新数据 → 看起来像死锁
- 尤其在 `expandable_segments` 模式下，内存碎片可能导致 CUDA 错误

**验证方法**: 在 `inference_batch()` 外包 try/except，打印所有异常；调用 `torch.cuda.synchronize()` 确认 CUDA 状态

### 可疑点 5 🔴：video._queue 满导致级联死锁（最可能的死锁触发路径）

**级联死锁链**:
```
video._queue 满(maxsize=100)
  → push_video_frame() 阻塞（Queue.put 默认 block=True）
    → process_frames 线程阻塞
      → res_frame_queue 满(maxsize=batch_size*2)
        → inference 线程阻塞在 res_frame_queue.put()
          → inference 不再从 output_queue 取数据
            → output_queue 无限堆积（主线程仍在生产）
              → feat_queue 满(maxsize=2)
                → 主线程阻塞在 feat_queue.put()
                  → run_step 停止
                    → 整个系统死锁
```

**为什么 edge-tts 加剧这个问题**:
- edge-tts 生成音频极快（云端合成），所有音频几乎瞬间到达 `asr.queue`
- 主线程 `run_step()` 快速处理所有音频，往 `feat_queue` 和 `output_queue` 灌数据
- 推理线程消费速度受 GPU 推理速度限制（比音频生产慢）
- 如果 WebRTC 消费帧的速度 < 帧生产速度，`video._queue` 逐渐堆积
- 堆积到 100 时触发上述级联死锁

**验证方法**:
- 在 `push_video_frame()` 调用前打印 `video._queue.qsize()`
- 在 `res_frame_queue.put()` 处加超时，记录阻塞时间
- 在 `feat_queue.put()` 处加超时，记录阻塞时间

### 可疑点 6 🟡：render 主循环 buffer_size 检查

**位置**: `base_avatar.py:491-494`
**代码**:
```python
buffer_size = self.output.get_buffer_size()
if buffer_size >= 5:
    time.sleep(0.04 * buffer_size * 0.8)
```
**问题**:
- 如果 `video._queue` 堆积 ≥ 5，主线程 sleep 时间过长
- sleep 期间不调用 `run_step()` → 不往队列放数据
- 如果 queue 一直 ≥ 5（消费端卡住），主线程基本停滞

**验证方法**: 打印每次 sleep 的时间和 buffer_size

---

## 4. 排查方案（三阶段）

### 阶段 A：日志观测（不改逻辑，纯监控）

**目标**: 精确定位死锁时哪个线程卡在哪个队列的 get/put 上

**修改文件**:
1. `avatars/audio_features/whisper.py` — 加 run_step 诊断日志
2. `avatars/base_avatar.py` — 加 inference / process_frames / render 诊断日志
3. `server/webrtc.py` — 加 recv 诊断日志
4. 新增 `utils/diag.py` — GPU 状态监控线程

**日志内容**:

**A1 — whisper.py `run_step()`**:
```python
logger.info(f"[DIAG-RUN_STEP] frames_len={len(self.frames)} "
            f"frames_sec={len(self.frames)/16000:.1f}s "
            f"feat_qsize={self.feat_queue.qsize()} "
            f"output_qsize={self.output_queue.qsize()} "
            f"audio2feat_time={t_feat:.3f}s "
            f"total_time={t_total:.3f}s")
```

**A2 — base_avatar.py `inference()`**:
```python
logger.info(f"[DIAG-INFER] feat_wait={t_feat_wait:.3f}s "
            f"output_wait={t_output_wait:.3f}s "
            f"infer_time={t_infer:.3f}s "
            f"res_frame_qsize={self.res_frame_queue.qsize()} "
            f"total_frames={total_frames}")
```

**A3 — base_avatar.py `process_frames()`**:
```python
logger.info(f"[DIAG-PROC] res_wait={t_res_wait:.3f}s "
            f"paste_time={t_paste:.3f}s "
            f"video_qsize={self.output.get_buffer_size()} "
            f"total_frames={total_frames}")
```

**A4 — webrtc.py `recv()`**:
```python
# 每 50 帧打印一次
if self.framecount % 50 == 0:
    mylogger.info(f"[DIAG-RECV] frame={self.framecount} "
                  f"queue_size={self._queue.qsize()} "
                  f"fps={self.framecount/self.totaltime:.2f}")
```

**A5 — 队列阻塞监控（新增，检测级联死锁）**:
```python
# 在 res_frame_queue.put() 和 feat_queue.put() 处加超时
# 记录每次 put 的等待时间和队列大小
logger.info(f"[DIAG-QUEUE] res_frame_qsize={self.res_frame_queue.qsize()} "
            f"feat_qsize={self.asr.feat_queue.qsize()} "
            f"output_qsize={self.asr.output_queue.qsize()} "
            f"video_qsize={self.output.get_buffer_size()} "
            f"put_wait={t_put:.3f}s")
```

**A6 — GPU 监控（独立守护线程）**:
```python
# 每 5 秒采样一次
logger.info(f"[DIAG-GPU] mem_used={mem_used}MB "
            f"mem_total={mem_total}MB "
            f"utilization={utilization}% "
            f"cuda_ok={torch.cuda.is_available()}")
```

**输出**: 日志文件 `logs/livetalking_diag.log`，包含所有诊断信息

---

### 阶段 C：压力递减测试

**目标**: 找到死锁的精确阈值，确认是时间相关还是数据量相关

| 测试组 | 文本长度 | 预期音频时长 | 目的 |
|--------|----------|-------------|------|
| C1 | 10 字 | ~3 秒 | 基线验证 |
| C2 | 30 字 | ~10 秒 | 接近死锁点 |
| C3 | 50 字 | ~17 秒 | 临界点 |
| C4 | 100 字 | ~33 秒 | 确认必死 |
| C5 | 连续 3 条 × 30 字 | ~30 秒 | 多轮累积效应 |
| C6 | 静音 60 秒 | 60 秒纯静音 | 验证是否无音频输入时不死锁 |

**每组记录**:
- 死锁时间（秒）
- 最后 FPS
- `self.frames` 长度
- 各队列 qsize
- GPU 显存使用量
- 卡住的线程和队列（从日志判断）

---

### 阶段 B：针对性修复

根据 A+C 的结论，按优先级修复：

**B1 — video._queue 防堆积（防止级联死锁，最高优先级）**
```python
# webrtc.py HumanPlayer.push_video() 中
# 如果队列满，丢弃最老的帧，防止级联阻塞
if self.__video._queue.full():
    try:
        self.__video._queue.get_nowait()  # 丢弃最老的帧
    except queue.Empty:
        pass
self.__video._queue.put_nowait((new_frame, None))
```

**B2 — 所有队列 put/get 加超时（切断级联死锁链）**
```python
# inference() 中 output_queue.get()
try:
    audioframe = self.asr.output_queue.get(block=True, timeout=5)
except queue.Empty:
    logger.warning("[INFER] output_queue timeout, skipping")
    continue

# inference() 中 res_frame_queue.put()
try:
    self.res_frame_queue.put((res_frame, ...), block=True, timeout=5)
except queue.Full:
    logger.warning("[INFER] res_frame_queue full, dropping frame")
    continue

# render() 中 feat_queue.put()
try:
    self.feat_queue.put(whisper_chunks, block=True, timeout=5)
except queue.Full:
    logger.warning("[RENDER] feat_queue full, dropping features")
```

**B3 — `self.frames` 内存上限保护**
```python
# whisper.py run_step() 末尾
MAX_FRAMES = 16000 * 30  # 最多保留 30 秒音频
if len(self.frames) > MAX_FRAMES:
    self.frames = self.frames[-MAX_FRAMES:]
```

**B4 — CUDA 错误检测**
```python
# inference_batch() 外包 try/except
try:
    pred = self.inference_batch(index, audiofeat_batch)
except Exception as e:
    logger.error(f"[INFER] GPU error: {e}")
    torch.cuda.synchronize()
    continue
```

---

## 5. 实施顺序

1. **阶段 A** — 修改 4 个文件加日志 + 新增 GPU 监控
2. **运行一次测试** — 发 50 字文本，收集日志
3. **分析日志** — 确定哪个线程/队列先卡住
4. **阶段 C** — 根据 A 结论，用不同长度文本测试
5. **阶段 B** — 根据 C 结论，实施修复
6. **回归测试** — 确认修复有效且不引入新问题

---

## 6. 风险和注意事项

- **日志量**: 诊断日志量大，建议用单独日志文件，不影响正常日志
- **性能影响**: 日志本身可能轻微影响性能，但可接受
- **不改变逻辑**: 阶段 A 严禁修改任何业务逻辑
- **Windows 兼容**: GPU 监控用 `torch.cuda.memory_allocated()` 而非 `nvidia-smi`
- **测试脚本**: 压力测试脚本放 `tests/` 目录

---

## 7. 成功标准

- 阶段 A 能精确定位死锁卡在哪个队列
- 阶段 C 能找到死锁的文本长度阈值
- 阶段 B 修复后，100 字文本持续运行 5 分钟不死锁
- FPS 波动在 ±3 以内（22-28 范围）
