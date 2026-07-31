# edge-tts 迁移设计文档

**日期**: 2026-07-31
**状态**: 待实施
**目标**: 将 TTS 引擎从本地 CosyVoice 切换为 Microsoft edge-tts 云端服务，彻底解决语音流畅度问题

## 背景与动机

当前 TTS 使用本地 CosyVoice-300M-SFT 模型推理，存在根本性的 GPU 串行瓶颈：

- 80 字/chunk 生成约 27 秒 ≈ 播放时间，生成速度追不上播放
- 句子间停顿 4-14 秒，用户体验差
- 每个 worker 加载模型约 15 秒，启动慢
- 6 个 worker 55% 失败率（GPU 资源不足），2 个 worker 稳定但并发有限

edge-tts 是微软 Edge 浏览器的云端 TTS 服务，免费、无需 GPU、推理几乎即时。切换后可彻底解决上述问题。

## 决策记录

| 决策项 | 选择 | 理由 |
|--------|------|------|
| CosyVoice 处理 | 完全替换 | 最简洁，维护成本最低 |
| 音色 | zh-CN-XiaoxiaoNeural | 年轻女声，温暖亲切 |
| 集成方式 | 直接调用（无独立服务） | 代码最少，启动最简单 |
| 效能重点 | 流畅度优先 | 消除句子间停顿 |
| 实现方案 | 方案 A：最小改动 | 保留 chunk + prebuffer 架构，只替换底层合成函数 |

## 架构变更

```
之前（CosyVoice）:                    之后（edge-tts）:

┌──────────┐                          ┌──────────┐
│ server.py│                          │ server.py│
│   │      │                          │   │      │
│   ▼      │                          │   ▼      │
│ tts_     │  HTTP :9233              │ tts_     │  直接调用
│ client.py┼────────┐                 │ client.py┼──────┐
│          │        │                 │          │      │
│          │   ┌────▼─────┐           │          │  ┌───▼──────┐
│          │   │tts_server│           │          │  │edge-tts  │
│          │   │(CosyVoice│           │          │  │(Microsoft│
│          │   │ GPU 推理)│           │          │  │  云端)   │
│          │   └──────────┘           │          │  └──────────┘
└──────────┘                          └──────────┘
  需启动 2 个终端                        只需 1 个终端
```

## 文件变动清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `tts_client.py` | 改写 | `synthesize_speech()` 改用 edge-tts 直接调用 |
| `tts_server.py` | 删除 | 不再需要独立 TTS 服务 |
| `config.py` | 改写 | 清理旧配置，新增 `EDGE_TTS_VOICE` |
| `server.py` | 微调 | 去除 tts_server 相关引用（如有） |
| `static/js/app.js` | 微调 | Blob type 从 `audio/wav` 改为 `audio/mpeg` |
| 依赖 | 新增 | `pip install edge-tts` |

## tts_client.py 核心改动

### synthesize_speech() 新实现

```python
import edge_tts
from config import EDGE_TTS_VOICE

async def synthesize_speech(text: str) -> bytes:
    """调用 edge-tts 云端合成语音。"""
    communicate = edge_tts.Communicate(text, voice=EDGE_TTS_VOICE)
    audio_bytes = b""
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_bytes += chunk["data"]
    return audio_bytes
```

### 保留不变

- `TTS_SKIP` 标记
- `synthesize_speech_b64()` 包装函数
- `tts_stream()` 的 chunk 合并 + 并发 + 预缓冲 + 按序 yield 逻辑
- `chunk_sentences()` 调用

### 可删除

- Windows SSL 证书 monkey-patch（aiohttp 专用，edge-tts 不用 aiohttp）
- `aiohttp` import（如 tts_client 内不再使用）

## 配置变更（config.py）

### 删除

- `TTS_SERVER_URL`
- `TTS_SPEAKER`
- `TTS_TIMEOUT`
- `TTS_MAX_CONCURRENT`

### 新增

- `EDGE_TTS_VOICE = "zh-CN-XiaoxiaoNeural"`

### 保留

- `TTS_CHUNK_SIZE`：继续用于 chunk 合并，初始值保持 40
- `TTS_PREBUFFER`：继续用于预缓冲，值改为 2（云端合成极快，2 个 chunk 缓冲足够应对网络波动）

## 前端改动（app.js）

唯一改动：音频 Blob MIME 类型

```javascript
// 之前
const blob = new Blob([audioBytes], { type: "audio/wav" });

// 之后
const blob = new Blob([audioBytes], { type: "audio/mpeg" });
```

## 效能分析

| 指标 | CosyVoice（当前） | edge-tts（预期） |
|------|-------------------|------------------|
| 单句合成延迟 | ~13-27s（GPU 推理） | ~0.5-2s（云端 API） |
| 并发限制 | GPU 串行，2 worker 极限 | 无 GPU 限制，取决于网络带宽 |
| 首句响应 | 等 prebuffer 4 chunks | prebuffer 降到 2，更快开始播放 |
| 句子间停顿 | 4-14s（生成追不上播放） | 几乎无停顿（生成远快于播放） |
| 资源占用 | GPU 显存 ~2GB/worker | 零本地资源 |
| 启动时间 | 每个 worker 加载模型 ~15s | 无需加载，即开即用 |

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| 网络断开 | `synthesize_speech()` 捕获异常 → 标记 `TTS_SKIP` → 静默降级为纯文字 |
| edge-tts 服务不可用 | 同上，不影响文字输出 |
| 超时 | edge-tts 自带超时机制，可额外包一层 `asyncio.wait_for` 兜底 |

## 依赖

```bash
pip install edge-tts
```

`aiohttp` 可保留（其他模块可能使用），但 `tts_client` 不再依赖它。

## 启动方式变更

```bash
# 之前：需要 2 个终端
# 终端 1：conda run -n py310 python tts_server.py
# 终端 2：conda run -n py310 python server.py

# 之后：只需 1 个终端
conda run -n py310 python server.py
```
