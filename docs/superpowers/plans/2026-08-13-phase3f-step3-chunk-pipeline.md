# Phase 3f Step 3: Chunk 流水线 + 预缓冲 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 200 字文本的首帧延迟从 10+ 秒降低到 4-6 秒，chunk 之间无缝衔接。

**Architecture:** 在 LiveTalking 后端新增 `chunk_processor` 模块，接收完整文本后拆分为 ~50 字/chunk，通过 `TextChunkQueue` 后台线程逐 chunk 送入 TTS。`HumanPlayer` 新增预缓冲机制（hold/release），前 N 个 chunk 攒够后再播放。前端零改动。

**Tech Stack:** Python 3.10, threading, LiveTalking (aiohttp + aiortc), pytest

**Spec:** `docs/superpowers/specs/2026-08-13-phase3f-step3-chunk-pipeline-design.md`

---

## Task 1: 创建 chunk_processor.py 纯函数

**Files:**
- Create: `G:/JupyterProject/LiveTalking/server/chunk_processor.py`

- [ ] **Step 1.1: 创建 chunk_processor.py 骨架**

在 `G:/JupyterProject/LiveTalking/server/` 目录下创建 `chunk_processor.py`：

```python
###############################################################################
#  Chunk Processor — 文本分句 + chunk 合并 + 逐 chunk 送入 avatar
###############################################################################

import re
import time
import threading
import logging

logger = logging.getLogger(__name__)


# ==========================================
# 按标点分句
# ==========================================
def split_sentences(text: str) -> list:
    """
    按中文标点分句。
    Args:
        text: 完整文本 (str)
    Returns:
        list[str]: 分句后的列表
    """
    parts = re.split(r'(?<=[。！？；…\n])', text)
    return [s for s in parts if s.strip()]


# ==========================================
# 合并小句子为 chunk
# ==========================================
def chunk_sentences(sentences: list, chunk_size: int = 50) -> list:
    """
    将小句子按字数累积合并为较大的 chunk。
    Args:
        sentences: 小句子列表 (list[str])
        chunk_size: 每个 chunk 的目标字数 (int)
    Returns:
        list[str]: 合并后的 chunk 列表
    """
    if not sentences:
        return []

    chunks = []
    current = ""

    for s in sentences:
        current += s
        if len(current) >= chunk_size:
            chunks.append(current)
            current = ""

    # 尾部合并到最后一个 chunk
    if current:
        if chunks:
            chunks[-1] += current
        else:
            chunks.append(current)

    return chunks
```

- [ ] **Step 1.2: 验证文件无语法错误**

```bash
cd G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from server.chunk_processor import split_sentences, chunk_sentences; print('OK')"
```

预期输出：`OK`

- [ ] **Step 1.3: 提交**

```bash
cd G:\JupyterProject\LiveTalking
git add server/chunk_processor.py
git commit -m "feat(chunk-processor): add split_sentences and chunk_sentences functions"
```

---

## Task 2: 为 split_sentences 编写单元测试

**Files:**
- Create: `G:/JupyterProject/LiveTalking/tests/test_chunk_processor.py`

- [ ] **Step 2.1: 创建测试文件**

在 `G:/JupyterProject/LiveTalking/tests/` 目录下创建 `test_chunk_processor.py`：

```python
###############################################################################
#  chunk_processor 单元测试
###############################################################################

import sys
import os
import pytest

# 添加 LiveTalking 根目录到 path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server.chunk_processor import split_sentences, chunk_sentences


# ==========================================
# split_sentences 测试
# ==========================================
class TestSplitSentences:

    def test_basic_split(self):
        """基本分句：句号分隔"""
        text = "你好。我是Lisa。"
        result = split_sentences(text)
        assert result == ["你好。", "我是Lisa。"]

    def test_multiple_punctuation(self):
        """多标点分隔"""
        text = "真的吗？太好了！再见。"
        result = split_sentences(text)
        assert result == ["真的吗？", "太好了！", "再见。"]

    def test_no_punctuation(self):
        """无标点：整体返回"""
        text = "你好世界"
        result = split_sentences(text)
        assert result == ["你好世界"]

    def test_empty_text(self):
        """空文本：返回空列表"""
        result = split_sentences("")
        assert result == []

    def test_newline_split(self):
        """换行分句"""
        text = "第一行\n第二行\n"
        result = split_sentences(text)
        assert result == ["第一行\n", "第二行\n"]

    def test_mixed_punctuation(self):
        """混合标点"""
        text = "你好，世界！真的吗？是的。"
        result = split_sentences(text)
        # 逗号不分句，其他标点分句
        assert result == ["你好，世界！", "真的吗？", "是的。"]
```

- [ ] **Step 2.2: 运行测试**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -m pytest tests/test_chunk_processor.py::TestSplitSentences -v
```

预期：6 个测试全部 PASS

- [ ] **Step 2.3: 提交**

```bash
git add tests/test_chunk_processor.py
git commit -m "test(chunk-processor): add unit tests for split_sentences"
```

---

## Task 3: 为 chunk_sentences 编写单元测试

**Files:**
- Modify: `G:/JupyterProject/LiveTalking/tests/test_chunk_processor.py`

- [ ] **Step 3.1: 追加 chunk_sentences 测试**

在 `test_chunk_processor.py` 文件末尾追加：

```python
# ==========================================
# chunk_sentences 测试
# ==========================================
class TestChunkSentences:

    def test_basic_chunk(self):
        """基本合并：达到 chunk_size 后拆分"""
        sentences = ["你好。", "我是Lisa。", "很高兴认识你。"]
        result = chunk_sentences(sentences, chunk_size=10)
        assert len(result) >= 1
        assert "".join(result) == "".join(sentences)

    def test_small_chunk_size(self):
        """小 chunk_size：拆成多个 chunk"""
        sentences = ["短。", "也短。", "还是短。"]
        result = chunk_sentences(sentences, chunk_size=3)
        assert len(result) >= 2

    def test_large_chunk_size(self):
        """大 chunk_size：全部合并为一个"""
        sentences = ["一句话。"]
        result = chunk_sentences(sentences, chunk_size=100)
        assert result == ["一句话。"]

    def test_empty_list(self):
        """空列表：返回空"""
        result = chunk_sentences([], chunk_size=50)
        assert result == []

    def test_content_preserved(self):
        """内容完整性"""
        sentences = ["A" * 20, "B" * 20, "C" * 20]
        result = chunk_sentences(sentences, chunk_size=30)
        assert "".join(result) == "A" * 20 + "B" * 20 + "C" * 20

    def test_tail_merged(self):
        """尾部合并到最后一个 chunk"""
        sentences = ["A" * 30, "B" * 10, "C" * 5]  # 尾部 B+C = 15 < 50
        result = chunk_sentences(sentences, chunk_size=30)
        # 第一个 chunk 是 AAAA... (30字)
        # 尾部 BBBB...CCCC 合并到第二个 chunk
        assert len(result) == 2
        assert result[0] == "A" * 30
        assert result[1] == "B" * 10 + "C" * 5
```

- [ ] **Step 3.2: 运行测试**

```bash
C:\ProgramData\Anaconda3\envs\py310\python.exe -m pytest tests/test_chunk_processor.py::TestChunkSentences -v
```

预期：6 个测试全部 PASS

- [ ] **Step 3.3: 提交**

```bash
git add tests/test_chunk_processor.py
git commit -m "test(chunk-processor): add unit tests for chunk_sentences"
```

---

## Task 4: 创建 TextChunkQueue 类

**Files:**
- Modify: `G:/JupyterProject/LiveTalking/server/chunk_processor.py`

- [ ] **Step 4.1: 追加 TextChunkQueue 类**

在 `chunk_processor.py` 文件末尾追加：

```python
# ==========================================
# 文本 chunk 队列管理器
# ==========================================
class TextChunkQueue:
    """
    管理文本 chunk 的队列和后台处理。
    接收完整文本 → 分句 → chunk 合并 → 逐 chunk 送入 avatar 处理。

    Args:
        avatar: BaseAvatar 实例
        chunk_size: 每个 chunk 的目标字数 (int)
        pre_buffer_count: 预缓冲 chunk 数量 (int)
    """

    def __init__(self, avatar, chunk_size: int = 50, pre_buffer_count: int = 2):
        """
        Args:
            avatar: BaseAvatar 实例
            chunk_size: 每个 chunk 的目标字数 (int)
            pre_buffer_count: 预缓冲 chunk 数量 (int)
        """
        self.avatar = avatar
        self.chunk_size = chunk_size
        self.pre_buffer_count = pre_buffer_count
        self.text_queue = []
        self.current_chunk = None
        self._lock = threading.Lock()
        self._processing = False
        self._chunks_fed = 0  # 已送入的 chunk 计数

    # ------------------------------------------
    # 提交文本
    # ------------------------------------------
    def submit(self, text: str, datainfo: dict = None):
        """
        接收完整文本，拆分为 chunk 入队并启动后台处理。
        Args:
            text: 完整文本 (str)
            datainfo: 附加信息 (dict)，透传给 avatar._feed_text_to_tts
        """
        if datainfo is None:
            datainfo = {}

        sentences = split_sentences(text)
        chunks = chunk_sentences(sentences, self.chunk_size)
        if not chunks:
            return

        logger.info(
            "[ChunkProcessor] submit: %d chars → %d sentences → %d chunks",
            len(text), len(sentences), len(chunks)
        )

        with self._lock:
            self.text_queue.extend(chunks)
            if not self._processing:
                self._processing = True
                self._chunks_fed = 0
                # 通知 player 进入 hold 模式
                self._enter_hold_mode()
                t = threading.Thread(target=self._process_loop, daemon=True)
                t.start()

    # ------------------------------------------
    # 后台处理循环
    # ------------------------------------------
    def _process_loop(self):
        """后台线程：逐 chunk 送入 avatar，等待每个 chunk 播完再送下一个"""
        while True:
            with self._lock:
                if not self.text_queue:
                    self.current_chunk = None
                    self._processing = False
                    return
                chunk = self.text_queue.pop(0)
                self.current_chunk = chunk

            # 预缓冲：送入第 pre_buffer_count+1 个 chunk 前释放缓冲
            if self._chunks_fed == self.pre_buffer_count:
                self._release_buffer()

            logger.debug("[ChunkProcessor] feeding chunk: %d chars", len(chunk))
            self.avatar._feed_text_to_tts(chunk, {})
            self._chunks_fed += 1
            self._wait_chunk_done()

    # ------------------------------------------
    # 等待当前 chunk 处理完成
    # ------------------------------------------
    def _wait_chunk_done(self):
        """
        等待当前 chunk 的音视频全部播完。
        阶段 1：等 TTS msgqueue 排空（文本被 TTS 线程取走）
        阶段 2：等 avatar.speaking=False 且 buffer 清空
        超时 30s 强制退出。
        """
        timeout = 30.0
        start = time.time()

        # 阶段 1：等文本被 TTS 取走
        while time.time() - start < timeout:
            tts_qsize = 0
            if hasattr(self.avatar, 'tts') and hasattr(self.avatar.tts, 'msgqueue'):
                tts_qsize = self.avatar.tts.msgqueue.qsize()
            if tts_qsize == 0:
                break
            time.sleep(0.05)

        # 阶段 2：等 speaking 结束 + buffer 清空
        while time.time() - start < timeout:
            if not self.avatar.speaking and self._buffer_empty():
                return
            time.sleep(0.05)

        logger.warning(
            "[ChunkProcessor] _wait_chunk_done timeout (%.1fs), force skip",
            time.time() - start
        )

    # ------------------------------------------
    # 综合忙碌状态
    # ------------------------------------------
    def is_busy(self) -> bool:
        """
        判断 chunk_processor 本身是否忙碌（不含 TTS/avatar 状态）。
        条件：队列不为空 或 当前有 chunk 在处理。
        """
        with self._lock:
            return bool(self.text_queue) or self.current_chunk is not None

    # ------------------------------------------
    # buffer 检查
    # ------------------------------------------
    def _buffer_empty(self) -> bool:
        """
        检查输出 buffer 是否为空。
        通过 avatar.output.get_buffer_size() 获取视频帧队列大小。
        """
        if hasattr(self.avatar, 'output') and hasattr(self.avatar.output, 'get_buffer_size'):
            return self.avatar.output.get_buffer_size() == 0
        return True

    # ------------------------------------------
    # 预缓冲控制
    # ------------------------------------------
    def _enter_hold_mode(self):
        """通知 player 进入 hold 模式"""
        player = self._get_player()
        if player and hasattr(player, 'enter_hold_mode'):
            player.enter_hold_mode()

    def _release_buffer(self):
        """通知 player 释放缓冲"""
        player = self._get_player()
        if player and hasattr(player, 'release_buffer'):
            player.release_buffer()

    def _get_player(self):
        """获取 HumanPlayer 实例"""
        if hasattr(self.avatar, 'output') and hasattr(self.avatar.output, '_player'):
            return self.avatar.output._player
        return None

    # ------------------------------------------
    # 清理
    # ------------------------------------------
    def flush(self):
        """清空队列，停止处理"""
        with self._lock:
            self.text_queue.clear()
            self.current_chunk = None
            self._processing = False
            self._chunks_fed = 0
        # 释放缓冲（如果还在 hold 模式）
        self._release_buffer()
```

- [ ] **Step 4.2: 验证文件无语法错误**

```bash
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from server.chunk_processor import TextChunkQueue; print('OK')"
```

预期输出：`OK`

- [ ] **Step 4.3: 提交**

```bash
git add server/chunk_processor.py
git commit -m "feat(chunk-processor): add TextChunkQueue class with submit/process_loop/flush"
```

---

## Task 5: 为 TextChunkQueue 编写单元测试

**Files:**
- Modify: `G:/JupyterProject/LiveTalking/tests/test_chunk_processor.py`

- [ ] **Step 5.1: 追加 TextChunkQueue 测试**

在 `test_chunk_processor.py` 文件末尾追加：

```python
from server.chunk_processor import TextChunkQueue
from unittest.mock import MagicMock


# ==========================================
# TextChunkQueue 测试
# ==========================================
class TestTextChunkQueue:

    def _make_mock_avatar(self):
        """创建 mock avatar"""
        avatar = MagicMock()
        avatar.speaking = False
        avatar.tts = MagicMock()
        avatar.tts.msgqueue = MagicMock()
        avatar.tts.msgqueue.qsize.return_value = 0
        avatar.output = MagicMock()
        avatar.output.get_buffer_size.return_value = 0
        avatar.output._player = MagicMock()
        return avatar

    def test_submit_creates_chunks(self):
        """submit 触发 chunk 处理"""
        avatar = self._make_mock_avatar()
        cq = TextChunkQueue(avatar, chunk_size=10)
        cq.submit("你好。我是Lisa。很高兴认识你。今天天气不错。")
        # 等待后台线程启动
        import time
        time.sleep(0.3)
        # 应该调用了 avatar._feed_text_to_tts
        assert avatar._feed_text_to_tts.called

    def test_is_busy_empty_queue(self):
        """空队列时 is_busy 返回 False"""
        avatar = self._make_mock_avatar()
        cq = TextChunkQueue(avatar)
        assert cq.is_busy() == False

    def test_is_busy_with_queue(self):
        """有队列时 is_busy 返回 True"""
        avatar = self._make_mock_avatar()
        cq = TextChunkQueue(avatar)
        cq.text_queue = ["chunk1"]
        assert cq.is_busy() == True

    def test_flush_clears_queue(self):
        """flush 清空队列"""
        avatar = self._make_mock_avatar()
        cq = TextChunkQueue(avatar)
        cq.text_queue = ["chunk1", "chunk2"]
        cq.current_chunk = "chunk0"
        cq.flush()
        assert cq.text_queue == []
        assert cq.current_chunk is None
        assert cq._processing == False

    def test_flush_releases_buffer(self):
        """flush 释放预缓冲"""
        avatar = self._make_mock_avatar()
        cq = TextChunkQueue(avatar)
        cq.flush()
        # 验证调用了 release_buffer
        assert avatar.output._player.release_buffer.called
```

- [ ] **Step 5.2: 运行测试**

```bash
C:\ProgramData\Anaconda3\envs\py310\python.exe -m pytest tests/test_chunk_processor.py::TestTextChunkQueue -v
```

预期：5 个测试全部 PASS

- [ ] **Step 5.3: 提交**

```bash
git add tests/test_chunk_processor.py
git commit -m "test(chunk-processor): add unit tests for TextChunkQueue"
```

---

## Task 6: 修改 HumanPlayer 添加预缓冲机制

**Files:**
- Modify: `G:/JupyterProject/LiveTalking/server/webrtc.py`

- [ ] **Step 6.1: 在 HumanPlayer.__init__ 中添加属性**

找到 `HumanPlayer.__init__` 方法（约第 180 行），在 `self.__container = avatar_session` 之前添加：

```python
        # 预缓冲机制（Phase 3f Step 3）
        self._hold_mode = False       # 是否处于 hold 模式
        self._held_frames = []        # 预缓冲的视频帧列表
```

完整上下文：

```python
class HumanPlayer:

    def __init__(
        self, avatar_session, format=None, options=None, timeout=None, loop=False, decode=True
    ):
        self.__thread: Optional[threading.Thread] = None
        self.__thread_quit: Optional[threading.Event] = None

        # examine streams
        self.__started: Set[PlayerStreamTrack] = set()
        self.__audio: Optional[PlayerStreamTrack] = None
        self.__video: Optional[PlayerStreamTrack] = None

        self.__audio = PlayerStreamTrack(self, kind="audio")
        self.__video = PlayerStreamTrack(self, kind="video")

        # 预缓冲机制（Phase 3f Step 3）
        self._hold_mode = False       # 是否处于 hold 模式
        self._held_frames = []        # 预缓冲的视频帧列表

        self.__container = avatar_session
        if hasattr(self.__container, 'output'):
            self.__container.output._player = self
```

- [ ] **Step 6.2: 添加 enter_hold_mode 和 release_buffer 方法**

在 `clear_queues` 方法之后添加：

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

- [ ] **Step 6.3: 修改 push_video 方法**

找到 `push_video` 方法（约第 198 行），替换为：

```python
    def push_video(self, frame):
        """
        推送视频帧到 video._queue。
        如果处于 hold 模式，暂存到 _held_frames。
        """
        from av import VideoFrame
        new_frame = VideoFrame.from_ndarray(frame, format="bgr24")
        if self._hold_mode:
            self._held_frames.append(new_frame)  # 暂存
        else:
            qsize = self.__video._queue.qsize()
            maxsize = self.__video._queue.maxsize
            if qsize >= maxsize * 0.8:
                diag.warning(
                    "[DIAG-PUSH_VIDEO] queue nearly full! qsize=%d/%d",
                    qsize, maxsize
                )
            self.__video._queue.put((new_frame, None))
```

- [ ] **Step 6.4: 修改 clear_queues 方法**

找到 `clear_queues` 方法（约第 224 行），替换为：

```python
    def clear_queues(self):
        """清空音视频队列，用于 session 回池复用"""
        while not self._HumanPlayer__video._queue.empty():
            try:
                self._HumanPlayer__video._queue.get_nowait()
            except Exception:
                break
        while not self._HumanPlayer__audio._queue.empty():
            try:
                self._HumanPlayer__audio._queue.get_nowait()
            except Exception:
                break
        # 清空预缓冲
        self._held_frames = []
        self._hold_mode = False
```

- [ ] **Step 6.5: 验证导入无错误**

```bash
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from server.webrtc import HumanPlayer; hp = HumanPlayer.__new__(HumanPlayer); print('OK')"
```

预期输出：`OK`

- [ ] **Step 6.6: 提交**

```bash
git add server/webrtc.py
git commit -m "feat(webrtc): add pre-buffer mechanism (hold/release) to HumanPlayer"
```

---

## Task 7: 修改 base_avatar.py 集成 chunk_processor

**Files:**
- Modify: `G:/JupyterProject/LiveTalking/avatars/base_avatar.py`

- [ ] **Step 7.1: 在 __init__ 末尾创建 chunk_processor**

找到 `BaseAvatar.__init__` 方法的最后（约第 126 行 `logger.error(...)` 之后），添加：

```python
        # Chunk processor（Phase 3f Step 3）
        from server.chunk_processor import TextChunkQueue
        self.chunk_processor = TextChunkQueue(
            self,
            chunk_size=getattr(opt, 'chunk_size', 50),
            pre_buffer_count=getattr(opt, 'pre_buffer_count', 2),
        )
```

- [ ] **Step 7.2: 改写 put_msg_txt 委托给 chunk_processor**

找到 `put_msg_txt` 方法（约第 128 行），替换为：

```python
    def put_msg_txt(self, msg, datainfo:dict={}):
        """
        接收文本，委托给 chunk_processor 处理。
        chunk_processor 会分句 → 合并 chunk → 逐 chunk 调用 _feed_text_to_tts。
        """
        self.last_active_time = time.time()
        self.chunk_processor.submit(msg, datainfo)
```

- [ ] **Step 7.3: 添加 _feed_text_to_tts 方法**

在 `put_msg_txt` 方法之后添加：

```python
    def _feed_text_to_tts(self, msg, datainfo:dict={}):
        """
        将文本直接送入 TTS 模块（chunk_processor 内部调用）。
        跳过 chunk 拆分，直接入 TTS 队列。
        """
        if hasattr(self, 'tts'):
            self.tts.put_msg_txt(msg, datainfo)
```

- [ ] **Step 7.4: 修改 is_speaking 方法**

找到 `is_speaking` 方法（约第 226 行），替换为：

```python
    def is_speaking(self) -> bool:
        """
        综合判断是否忙碌（供 /is_speaking API 使用）。
        任一条件为真 → busy:
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

- [ ] **Step 7.5: 修改 flush_talk 方法**

找到 `flush_talk` 方法（约第 216 行），替换为：

```python
    def flush_talk(self):
        # 清理 chunk_processor
        if hasattr(self, 'chunk_processor'):
            self.chunk_processor.flush()
        # 原有逻辑
        if hasattr(self, 'tts') and hasattr(self.tts, 'flush_talk'):
            self.tts.flush_talk()
        if hasattr(self, 'asr') and hasattr(self.asr, 'flush_talk'):
            self.asr.flush_talk()
        self.custom_audiotype = 0
```

- [ ] **Step 7.6: 修改 reset_for_reuse 方法**

找到 `reset_for_reuse` 方法（约第 134 行），在 `self.speaking = False` 之后添加：

```python
    def reset_for_reuse(self):
        """
        重置 session 状态以便回池复用。
        清空 TTS 队列、输出队列、重置 speaking 状态。
        不杀线程，不释放 GPU 缓存。
        """
        # 清理 chunk_processor
        if hasattr(self, 'chunk_processor'):
            self.chunk_processor.flush()

        # 重置说话状态
        self.speaking = False

        # 清空 TTS 消息队列
        if hasattr(self, 'tts') and hasattr(self.tts, 'flush_talk'):
            self.tts.flush_talk()

        # 通过 output 的 player 清空音视频队列
        if hasattr(self, 'output') and hasattr(self.output, '_player'):
            player = self.output._player
            if player is not None and hasattr(player, 'clear_queues'):
                player.clear_queues()

        # 清空 res_frame_queue（推理结果队列）
        while not self.res_frame_queue.empty():
            try:
                self.res_frame_queue.get_nowait()
            except Exception:
                break

        logger.info(f"[RESET] session {self.sessionid} reset for reuse")
```

- [ ] **Step 7.7: 验证导入无错误**

```bash
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from avatars.base_avatar import BaseAvatar; print('OK')"
```

预期输出：`OK`

- [ ] **Step 7.8: 提交**

```bash
git add avatars/base_avatar.py
git commit -m "feat(base-avatar): integrate chunk_processor, enhance is_speaking and flush"
```

---

## Task 8: 修改 config.py 添加命令行参数

**Files:**
- Modify: `G:/JupyterProject/LiveTalking/config.py`

- [ ] **Step 8.1: 添加 chunk_size 和 pre_buffer_count 参数**

找到 `--pool_size` 参数（约第 88 行），在其后添加：

```python
    parser.add_argument('--pool_size', type=int, default=2,
                        help="Session pool size (number of pre-created sessions)")
    # Chunk processor 参数（Phase 3f Step 3）
    parser.add_argument('--chunk_size', type=int, default=50,
                        help="chunk_processor: 每个 chunk 的目标字数（默认 50）")
    parser.add_argument('--pre_buffer_count', type=int, default=2,
                        help="chunk_processor: 预缓冲 chunk 数量（默认 2）")
```

- [ ] **Step 8.2: 验证参数解析**

```bash
C:\ProgramData\Anaconda3\envs\py310\python.exe -c "from config import parse_args; import sys; sys.argv=['test', '--chunk_size', '80', '--pre_buffer_count', '3']; opt=parse_args(); print(f'chunk_size={opt.chunk_size}, pre_buffer_count={opt.pre_buffer_count}')"
```

预期输出：`chunk_size=80, pre_buffer_count=3`

- [ ] **Step 8.3: 提交**

```bash
git add config.py
git commit -m "feat(config): add --chunk_size and --pre_buffer_count CLI parameters"
```

---

## Task 9: 集成测试

- [ ] **Step 9.1: 启动 LiveTalking 服务**

```bash
cd G:\JupyterProject\LiveTalking
set PYTHONPATH=G:\JupyterProject\LiveTalking
C:\ProgramData\Anaconda3\envs\py310\python.exe app.py --model musetalk --avatar_id musetalk_avatar1 --transport webrtc --listenport 8010 --pool_size 2
```

观察日志，确认：
- 无导入错误
- Session 池正常创建

- [ ] **Step 9.2: 启动 Lisa 主服务**

```bash
cd G:\JupyterProject\20260725_Agent_AI可视化机器人
conda run -n py310 python server.py
```

- [ ] **Step 9.3: 浏览器测试短文本（<50字）**

打开 `http://localhost:8000`，发送：

```
你好，我是Lisa。
```

**验证**：
- 数字人正常说话
- 日志显示 `[ChunkProcessor] submit: X chars → Y sentences → 1 chunks`
- 说完后按钮解锁

- [ ] **Step 9.4: 浏览器测试长文本（>100字）**

发送：

```
你好，我是Lisa，很高兴认识你。今天天气真不错，阳光明媚，微风不燥。我最近在学习一些新的技术，感觉非常有意思。希望以后能和你多聊聊，分享更多有趣的事情。
```

**验证**：
- 数字人说话首帧延迟明显降低（应 < 8 秒）
- 日志显示多个 chunk：`[ChunkProcessor] submit: X chars → Y sentences → N chunks`
- chunk 之间无明显卡顿

- [ ] **Step 9.5: 检查 LiveTalking 日志**

确认日志中出现：
```
[ChunkProcessor] submit: 100 chars → 5 sentences → 2 chunks
[ChunkProcessor] feeding chunk: 50 chars
[ChunkProcessor] feeding chunk: 50 chars
```

- [ ] **Step 9.6: 测试 interrupt 打断**

发送第一条长消息，在数字人说话过程中发送第二条消息。

**验证**：
- 第一条被打断，队列清空
- 第二条正常处理

- [ ] **Step 9.7: 测试自定义参数**

重启 LiveTalking：

```bash
C:\ProgramData\Anaconda3\envs\py310\python.exe app.py --model musetalk --avatar_id musetalk_avatar1 --transport webrtc --listenport 8010 --pool_size 2 --chunk_size 80 --pre_buffer_count 3
```

**验证**：
- 日志显示 chunk 大小和预缓冲数量生效

- [ ] **Step 9.8: 提交集成测试结果**

如果所有测试通过：

```bash
# 无需额外提交，前面的任务已经分别提交了
git log --oneline -5
```

预期看到 5 个 commit（Task 1/2/3/4/5/6/7/8 对应的提交）。

---

## 完成标准

所有 Task 完成后，以下功能应正常工作：

1. **chunk_processor 单元测试全部通过**
2. **短文本（<50字）正常处理，不拆分**
3. **长文本（200字）首帧延迟 < 8 秒，chunk 间无卡顿**
4. **interrupt 打断后状态干净**
5. **Session 回池复用正常**
6. **`--chunk_size` 和 `--pre_buffer_count` 参数可配置且生效**

---

## 文件改动清单

| 仓库 | 文件 | 改动类型 | 说明 |
|------|------|----------|------|
| LiveTalking | `server/chunk_processor.py` | 新建 | split_sentences + chunk_sentences + TextChunkQueue |
| LiveTalking | `avatars/base_avatar.py` | 修改 | put_msg_txt 委托 + _feed_text_to_tts + is_speaking 增强 + flush/reset 清理 |
| LiveTalking | `server/webrtc.py` | 修改 | HumanPlayer 新增 enter_hold_mode/release_buffer + push_video 改造 + clear_queues 清理 |
| LiveTalking | `config.py` | 修改 | 新增 --chunk_size 和 --pre_buffer_count 参数 |
| LiveTalking | `tests/test_chunk_processor.py` | 新建 | 单元测试 |

---

## 预计提交数

8 个 commit（Task 1-8 各一个），Task 9 是集成测试无 commit。
