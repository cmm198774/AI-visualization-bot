# Phase 3f Step 3 设计文档：Chunk 流水线 + 预缓冲

**版本**: 1.0  
**日期**: 2026-08-13  
**状态**: 待审核

---

## 1. 背景与目标

### 1.1 背景

Phase 3f 的 Step 1（自动连接）和 Step 2（发送按钮锁定）已完成。但当前数字人存在一个关键性能问题：

- **LLM 非流式输出**：server.py 使用 `ainvoke`（非流式），等完整生成后才一次性 yield 给前端
- **前端一次 POST**：收到完整文本后调一次 `sendToLiveTalking(完整文本)`，POST 到 LiveTalking `/human`
- **LiveTalking 一次性处理**：整段文本进入 TTS `msgqueue` → edge-tts 合成完整音频 → avatar 推理全部视频帧 → 才开始 WebRTC 播放

**现象**：200 字文本，数字人要等 10+ 秒才开始播放。

### 1.2 目标

1. **降低首帧延迟**：将长文本拆成多个 chunk，第一段处理完（2-3 秒）就开始播放
2. **chunk 之间无缝衔接**：预缓冲机制确保 chunk 之间不出现卡顿
3. **可配置**：chunk 大小和预缓冲数量可通过启动参数调整
4. **前端零改动**：所有改动都在 LiveTalking 后端完成

---

## 2. 当前数据流（改前）

```
server.py
  ainvoke(用户消息) → 等 LLM 全部生成完 → 完整文本（200字）
      ↓
  SSE: { type: "text", content: "完整200字文本" }
      ↓
前端 app.js
  handleSSEEvent case "text":
      sendToLiveTalking(完整200字)  ← 一次 POST /human
      ↓
LiveTalking routes.py
  /human → avatar.put_msg_txt(200字)
      ↓
base_avatar.py
  put_msg_txt → tts.put_msg_txt → msgqueue.put(200字)
      ↓
TTS 后台线程 (edge.py)
  msgqueue.get() → edge_tts.Communicate(200字)
  → 合成完整音频（耗时 5-8 秒）
  → put_audio_frame() × N 次
      ↓
avatar 推理线程 (base_avatar.py inference + process_frames)
  音频特征提取 → UNet/VAE 推理 → 视频帧
  → HumanPlayer.push_video(frame)
      ↓
HumanPlayer
  __video._queue.put(frame)  ← maxsize=100
      ↓
PlayerStreamTrack.recv()
  _queue.get() → 设置 pts → WebRTC 发给前端
      ↓
前端 <video> 播放
```

**问题**：从 POST /human 到前端开始播放，中间要等 TTS + 推理处理完全部 200 字，约 10+ 秒。

---

## 3. 目标数据流（改后）

```
server.py（不变）
  ainvoke → 完整文本（200字）→ SSE text 事件
      ↓
前端 app.js（不变）
  sendToLiveTalking(完整200字) → POST /human
      ↓
LiveTalking routes.py（不变）
  /human → avatar.put_msg_txt(200字)
      ↓
base_avatar.py（改动）
  put_msg_txt → chunk_processor.submit(200字)  ← 新增 chunk_processor 层
      ↓
chunk_processor.submit()
  1. split_sentences(200字) → ["句子1。", "句子2。", "句子3。", ...]
  2. chunk_sentences(句子列表, chunk_size=50) → ["chunk1(~50字)", "chunk2(~50字)", ...]
  3. 后台线程逐 chunk 送入 avatar._feed_text_to_tts(chunk)
      ↓
TTS 后台线程（不变）
  msgqueue.get(chunk) → edge_tts 合成 chunk 音频 → put_audio_frame()
      ↓
avatar 推理（不变）
  音频特征 → 推理 → 视频帧 → HumanPlayer.push_video(frame)
      ↓
HumanPlayer（改动）
  前 N 个 chunk（pre_buffer_count=2）：
      push_video → 攒在 _held_frames（不入 _queue）
  第 N+1 个 chunk 开始时：
      release_buffer() → _held_frames 全部入 _queue → WebRTC 开始播放
  后续 chunk：
      push_video → 直接入 _queue → 接力播放
      ↓
PlayerStreamTrack.recv()（不变）
  _queue.get() → WebRTC → 前端播放
```

**效果**：chunk1 处理完约 2-3 秒（50 字），加上 chunk2 的预缓冲时间，约 4-6 秒开始播放，之后无缝衔接。

---

## 4. 模块设计

### 4.1 chunk_processor.py（新建）

**文件位置**：`LiveTalking/server/chunk_processor.py`

**职责**：接收完整文本 → 分句 → 合并 chunk → 后台线程逐 chunk 送入 TTS

#### 4.1.1 纯函数

```python
def split_sentences(text: str) -> list[str]:
    """
    按中文标点分句。
    分句符号：。！？；…\n
    """
    parts = re.split(r'(?<=[。！？；…\n])', text)
    return [s for s in parts if s.strip()]

def chunk_sentences(sentences: list[str], chunk_size: int = 50) -> list[str]:
    """
    将小句子按字数累积合并为较大的 chunk。
    - 如果单个句子超过 chunk_size，保持原样不截断
    - 剩余不足 chunk_size 的尾部，合并到最后一个 chunk（不单独成 chunk）
    """
    chunks = []
    current = ""
    for s in sentences:
        current += s
        if len(current) >= chunk_size:
            chunks.append(current)
            current = ""
    if current:
        if chunks:
            chunks[-1] += current   # 合并到最后一个 chunk
        else:
            chunks.append(current)   # 只有一句的情况
    return chunks
```

#### 4.1.2 TextChunkQueue 类

```python
class TextChunkQueue:
    """
    管理文本 chunk 的队列和后台处理。
    接收完整文本 → 分句 → chunk 合并 → 逐 chunk 送入 avatar。
    
    Args:
        avatar: BaseAvatar 实例
        chunk_size: 每个 chunk 的目标字数（默认 50）
        pre_buffer_count: 预缓冲 chunk 数量（默认 2，攒够再播放）
    """
    
    def __init__(self, avatar, chunk_size=50, pre_buffer_count=2):
        self.avatar = avatar
        self.chunk_size = chunk_size
        self.pre_buffer_count = pre_buffer_count
        self.text_queue = []          # 待处理 chunk 列表
        self.current_chunk = None     # 正在处理的 chunk
        self._lock = threading.Lock()
        self._processing = False
        self._chunks_fed = 0          # 已送入的 chunk 计数
```

#### 4.1.3 核心方法

```python
def submit(self, text, datainfo=None):
    """
    接收完整文本，拆分为 chunk 入队并启动后台处理。
    """
    sentences = split_sentences(text)
    chunks = chunk_sentences(sentences, self.chunk_size)
    # 入队 + 启动后台线程

def _process_loop(self):
    """
    后台线程：逐 chunk 送入 avatar，等待每个 chunk 播完再送下一个。
    
    关键逻辑：
    - 前 pre_buffer_count 个 chunk：送入后通知 HumanPlayer 进入 hold 模式
    - 第 pre_buffer_count + 1 个 chunk 送入前：通知 HumanPlayer release
    - 后续 chunk：正常送入，等当前 chunk 播完再送下一个
    """
    
def _wait_chunk_done(self):
    """
    等待当前 chunk 的音视频全部播完。
    阶段 1：等 TTS msgqueue 排空（文本被 TTS 线程取走）
    阶段 2：等 avatar.speaking=False 且 buffer 清空
    超时 30s 强制退出。
    """

def is_busy(self) -> bool:
    """
    判断 chunk_processor 本身是否忙碌。
    条件：队列不为空 或 当前有 chunk 在处理。
    """

def flush(self):
    """清空队列，停止处理（interrupt 时调用）"""
```

#### 4.1.4 与 HumanPlayer 的交互

chunk_processor 通过 avatar 的 player 引用控制预缓冲：

```python
# 开始处理时，通知 player 进入 hold 模式
if hasattr(self.avatar, 'output') and hasattr(self.avatar.output, '_player'):
    player = self.avatar.output._player
    if player:
        player.enter_hold_mode()

# 送入第 pre_buffer_count + 1 个 chunk 前，释放缓冲
if self._chunks_fed == self.pre_buffer_count:
    player.release_buffer()
```

### 4.2 HumanPlayer 预缓冲机制（改动 webrtc.py）

**文件位置**：`LiveTalking/server/webrtc.py`

**改动范围**：`HumanPlayer` 类

#### 4.2.1 新增属性

```python
class HumanPlayer:
    def __init__(self, ...):
        # ... 原有代码 ...
        self._hold_mode = False       # 是否处于 hold 模式
        self._held_frames = []        # 预缓冲的视频帧列表
```

#### 4.2.2 新增方法

```python
def enter_hold_mode(self):
    """进入 hold 模式：后续 push_video 的帧暂存，不入 _queue"""
    self._hold_mode = True
    self._held_frames = []

def release_buffer(self):
    """释放缓冲：将攒的帧全部入 _queue，退出 hold 模式"""
    for frame in self._held_frames:
        self.__video._queue.put((frame, None))
    self._held_frames = []
    self._hold_mode = False
```

#### 4.2.3 修改 push_video

```python
def push_video(self, frame):
    from av import VideoFrame
    new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
    if self._hold_mode:
        self._held_frames.append(new_frame)  # 暂存
    else:
        self.__video._queue.put((new_frame, None))  # 正常入队
```

#### 4.2.4 修改 clear_queues

```python
def clear_queues(self):
    # 原有清空 _queue 的逻辑 ...
    # 新增：清空 held_frames + 重置 hold_mode
    self._held_frames = []
    self._hold_mode = False
```

### 4.3 base_avatar.py 集成（改动）

**文件位置**：`LiveTalking/avatars/base_avatar.py`

#### 4.3.1 `__init__` 末尾创建 chunk_processor

```python
# 在 __init__ 末尾添加
from server.chunk_processor import TextChunkQueue
self.chunk_processor = TextChunkQueue(
    self,
    chunk_size=opt.chunk_size,
    pre_buffer_count=opt.pre_buffer_count,
)
```

#### 4.3.2 改写 put_msg_txt 委托给 chunk_processor

```python
def put_msg_txt(self, msg, datainfo:dict={}):
    """接收文本，委托给 chunk_processor 处理"""
    self.last_active_time = time.time()
    self.chunk_processor.submit(msg, datainfo)
```

#### 4.3.3 新增 _feed_text_to_tts（原 put_msg_txt 逻辑）

```python
def _feed_text_to_tts(self, msg, datainfo:dict={}):
    """
    将文本直接送入 TTS 模块。
    chunk_processor 内部调用，跳过 chunk 拆分。
    """
    if hasattr(self, 'tts'):
        self.tts.put_msg_txt(msg, datainfo)
```

#### 4.3.4 增强 is_speaking 检查

```python
def is_speaking(self) -> bool:
    """
    综合判断是否忙碌。
    检查顺序：
    1. chunk_processor 有排队/处理中的 chunk
    2. TTS msgqueue 有未处理的文本
    3. avatar.speaking 为 True（正在输出音频帧）
    4. output buffer 有未播放的视频帧
    5. HumanPlayer 有 held_frames（预缓冲中）
    """
    # 条件 1：chunk_processor
    if hasattr(self, 'chunk_processor') and self.chunk_processor.is_busy():
        return True
    # 条件 2：TTS 队列
    if hasattr(self, 'tts') and hasattr(self.tts, 'msgqueue'):
        if self.tts.msgqueue.qsize() > 0:
            return True
    # 条件 3：speaking 标志
    if self.speaking:
        return True
    # 条件 4：视频 buffer
    if hasattr(self, 'output') and hasattr(self.output, 'get_buffer_size'):
        if self.output.get_buffer_size() > 0:
            return True
    # 条件 5：预缓冲帧
    if hasattr(self, 'output') and hasattr(self.output, '_player'):
        player = self.output._player
        if player and hasattr(player, '_held_frames') and player._held_frames:
            return True
    return False
```

#### 4.3.5 flush_talk / reset_for_reuse 同步清理

```python
def flush_talk(self):
    # 新增：清理 chunk_processor
    if hasattr(self, 'chunk_processor'):
        self.chunk_processor.flush()
    # 原有逻辑 ...

def reset_for_reuse(self):
    # 新增：清理 chunk_processor
    if hasattr(self, 'chunk_processor'):
        self.chunk_processor.flush()
    self.speaking = False
    # 原有逻辑 ...
```

### 4.4 config.py 参数（改动）

**文件位置**：`LiveTalking/config.py`

新增两个命令行参数：

```python
parser.add_argument('--chunk_size', type=int, default=50,
                    help='chunk_processor: 每个 chunk 的目标字数（默认 50）')
parser.add_argument('--pre_buffer_count', type=int, default=2,
                    help='chunk_processor: 预缓冲 chunk 数量（默认 2）')
```

启动示例：

```bash
# 默认参数
python app.py --model musetalk --avatar_id musetalk_avatar1 --transport webrtc --listenport 8010 --pool_size 2

# 自定义参数（更大的 chunk，更多的预缓冲）
python app.py --model musetalk --avatar_id musetalk_avatar1 --transport webrtc --listenport 8010 --pool_size 2 --chunk_size 80 --pre_buffer_count 3
```

---

## 5. 数据流时序图

以 200 字文本为例，`chunk_size=50`，`pre_buffer_count=2`：

```
时间轴 →
0s          2s          4s          6s          8s          10s         12s
|           |           |           |           |           |           |

POST /human (200字)
    ↓
chunk_processor.submit()
    ↓ split_sentences → chunk_sentences
    ↓ 得到 4 个 chunk: [c1(50字), c2(50字), c3(50字), c4(50字)]
    ↓
    ↓ enter_hold_mode() ← HumanPlayer 进入 hold 模式
    ↓
c1 → TTS → 推理 → push_video → held_frames[0..49]（~50帧）
    |           |           |
    0s          2s          3s
    
c2 → TTS → 推理 → push_video → held_frames[50..99]（~50帧）
                |           |           |
                3s          5s          6s
                
    ↓ _chunks_fed == pre_buffer_count(2)，触发 release_buffer()
    ↓ held_frames[0..99] → _queue → WebRTC 开始播放
    ↓                                    ↑ 约 6 秒开始播放（有 100 帧缓冲）
    
c3 → TTS → 推理 → push_video → _queue（直接入队，接力播放）
                            |           |           |
                            6s          8s          9s

c4 → TTS → 推理 → push_video → _queue（直接入队）
                                        |           |           |
                                        9s          11s         12s

    ↓ 全部播完 → is_speaking() = false → 前端轮询解锁发送按钮
```

**对比改前**：
- 改前：0s POST → 10+ 秒开始播放
- 改后：0s POST → ~6 秒开始播放（预缓冲 2 chunk），之后无缝衔接

---

## 6. 错误处理

### 6.1 chunk_processor 超时

`_wait_chunk_done` 有 30 秒超时保护。超时后：
- 记录 warning 日志
- 强制跳过当前 chunk，处理下一个
- 不会死锁

### 6.2 flush_talk / interrupt

前端发送 interrupt 时（`/human` 带 `interrupt: true`）：
1. `avatar.flush_talk()` 被调用
2. chunk_processor.flush() 清空队列
3. HumanPlayer.clear_queues() 清空 held_frames + _queue
4. 后续新文本正常处理

### 6.3 Session 回池复用

WebRTC 断开 → `release()` → `reset_for_reuse()`：
- chunk_processor.flush() 清理
- held_frames 清空
- hold_mode 重置
- session 可安全复用

### 6.4 短文本不拆分

如果文本 < chunk_size（如"你好" 2 个字）：
- split_sentences → ["你好"]
- chunk_sentences → ["你好"]
- 只有 1 个 chunk，pre_buffer_count 不触发（不够 2 个）
- 特殊处理：如果总 chunk 数 < pre_buffer_count，在最后一个 chunk 处理完后自动 release

---

## 7. 文件改动清单

| 仓库 | 文件 | 改动类型 | 改动内容 |
|------|------|----------|----------|
| LiveTalking | `server/chunk_processor.py` | **新建** | split_sentences + chunk_sentences + TextChunkQueue |
| LiveTalking | `avatars/base_avatar.py` | 修改 | put_msg_txt 委托 + _feed_text_to_tts + is_speaking 增强 + flush/reset 清理 |
| LiveTalking | `server/webrtc.py` | 修改 | HumanPlayer 新增 hold/release 预缓冲机制 |
| LiveTalking | `config.py` | 修改 | 新增 --chunk_size 和 --pre_buffer_count 参数 |
| LiveTalking | `tests/test_chunk_processor.py` | **新建** | split_sentences + chunk_sentences + TextChunkQueue 单元测试 |
| Lisa 前端 | （无改动） | — | — |

---

## 8. 测试计划

### 8.1 单元测试（LiveTalking/tests/test_chunk_processor.py）

| 测试 | 内容 |
|------|------|
| split_sentences | 基本分句、多标点、无标点、空文本、换行分句 |
| chunk_sentences | 基本合并、小 chunk_size、大 chunk_size、空列表、内容完整性、尾部合并 |
| TextChunkQueue | submit 触发处理、is_busy 状态、flush 清理、mock avatar 交互 |

### 8.2 集成测试（手动）

| 场景 | 验证 |
|------|------|
| 短文本（<50字） | 不拆分，正常处理播放 |
| 中等文本（100字） | 拆成 2 chunk，预缓冲后播放 |
| 长文本（200字） | 拆成 4 chunk，首帧延迟 < 8 秒，chunk 间无卡顿 |
| 连续发两条消息 | 第一条播完后第二条正常处理 |
| interrupt 打断 | 队列清空，新文本正常处理 |
| WebRTC 断开重连 | session 复用，chunk_processor 状态干净 |

### 8.3 性能指标

| 指标 | 改前 | 改后预期 |
|------|------|----------|
| 200 字首帧延迟 | 10+ 秒 | 4-6 秒 |
| chunk 间卡顿 | N/A | 无（预缓冲保证） |
| 视频帧率 | 25 FPS | 25 FPS（不变） |
| GPU 显存 | ~1613 MB | ~1613 MB（不变） |

---

## 9. 验收标准

- [ ] chunk_processor 单元测试全部通过
- [ ] 200 字文本首帧延迟 < 8 秒
- [ ] chunk 之间播放无明显卡顿（主观评价）
- [ ] short 文本（<50字）正常处理
- [ ] interrupt 打断后状态干净
- [ ] Session 回池复用正常
- [ ] `--chunk_size` 和 `--pre_buffer_count` 参数可配置且生效
- [ ] LiveTalking 启动无导入错误

---

**下一步**：审核此设计文档，确认后转入实施计划阶段。
