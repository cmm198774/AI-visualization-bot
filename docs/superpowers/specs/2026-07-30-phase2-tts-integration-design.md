# Phase 2: TTS 语音集成设计文档

**日期**: 2026-07-30
**状态**: 设计中

## 1. 目标

为 Lisa 聊天机器人集成 CosyVoice2 本地语音合成（TTS），实现 AI 回复的语音播放。用户发送消息后，Lisa 的回复不仅以文字显示，还以语音逐句播放。

## 2. 技术决策

| 决策项 | 选择 | 理由 |
|---|---|---|
| TTS 模型 | CosyVoice2-0.5B | 阿里开源，中文效果好，支持流式 |
| 部署方式 | 本地 GPU 部署 | 用户有 NVIDIA 显卡，无 API 费用 |
| 服务架构 | 独立 TTS 服务 | 模型加载不影响主服务，崩溃互不影响 |
| 音频模式 | 句子队列逐句播放 | 改动最小，ainvoke 不用改，体验够用 |
| 声音 | CosyVoice2 内置"中文女" | 先用内置音色跑通流程 |
| 错误处理 | 静默降级 | TTS 失败只显示文字，用户无感知 |

## 3. 整体架构

```
浏览器（前端）
    │ SSE
    ▼
主服务器 server.py (:8000)
    │ ainvoke → 完整文本 → 分句
    │ 逐句: yield text → 调 TTS → yield audio
    │
    │ HTTP POST
    ▼
TTS 服务 tts_server.py (:9233)
    │ CosyVoice2-0.5B 模型
    │ GPU: NVIDIA 显卡
```

### SSE 事件流

```
status → text(句1) → audio(句1) → text(句2) → audio(句2) → ... → mood → audio_done → done
```

### 新增 SSE 事件类型

| 事件 | 数据 | 说明 |
|---|---|---|
| `audio` | `{"type": "audio", "data": "<base64 WAV>"}` | 一句音频 |
| `audio_done` | `{"type": "audio_done"}` | 所有音频发送完毕 |

## 4. TTS 服务（tts_server.py）

### 启动

```bash
python tts_server.py    # 端口 9233，加载模型约 10~20 秒
```

### API 接口

```
POST /tts
  请求: {"text": "你好呀老板～", "speaker": "中文女"}
  响应: WAV 音频二进制 (audio/wav)

GET /health
  响应: {"status": "ready"} 或 {"status": "loading"}
```

### 核心逻辑

```python
from cosyvoice.cli.cosyvoice import CosyVoice2

model = CosyVoice2('pretrained_models/CosyVoice2-0.5B')

@app.post("/tts")
async def tts(request: TTSRequest):
    audio_data = model.inference_sft(request.text, request.speaker)
    wav_bytes = numpy_to_wav(audio_data)
    return Response(content=wav_bytes, media_type="audio/wav")
```

### 依赖

```bash
# 克隆 CosyVoice2 官方仓库
git clone https://github.com/QwenAudio/CosyVoice.git
# 按官方文档配置 conda 环境 + 下载模型
# 模型放在 CosyVoice/pretrained_models/CosyVoice2-0.5B/
```

### .gitignore 新增

```
CosyVoice/    # 官方仓库 + 模型文件，不上传
```

## 5. 主服务器改动（server.py）

### 分句工具（sentence_splitter.py）

```python
def split_sentences(text: str) -> list[str]:
    """
    按中文标点分句，保留标点在句尾。

    输入: "你好呀老板～今天天气不错呢！有什么需要帮忙的吗？"
    输出: ["你好呀老板～", "今天天气不错呢！", "有什么需要帮忙的吗？"]

    规则:
    - 分隔符: 。！？～；…，、
    - 无标点的尾部文本也作为一个句子
    - 空句子过滤掉
    """
```

### _event_stream 改动

```python
# 原流程:
# ainvoke → yield text(完整) → yield mood → yield done

# 新流程:
result = await agent_graph.ainvoke(...)
final_text = extract_text(result)
mood = result.get("mood", "default")

sentences = split_sentences(final_text)

for sentence in sentences:
    # 1. 先 yield 文字（前端立即显示）
    yield text_event(sentence)

    # 2. 调 TTS 服务获取音频
    try:
        audio_bytes = await call_tts_service(sentence)
        audio_b64 = base64.b64encode(audio_bytes).decode()
        yield audio_event(audio_b64)
    except Exception:
        pass  # 静默降级

yield mood_event(mood)
yield "audio_done" event
yield done_event()
```

### TTS 调用函数

```python
import aiohttp

TTS_URL = config.TTS_SERVER_URL   # http://127.0.0.1:9233/tts

async def call_tts_service(text: str) -> bytes:
    async with aiohttp.ClientSession() as session:
        async with session.post(TTS_URL, json={
            "text": text,
            "speaker": "中文女"
        }, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.read()
            raise Exception(f"TTS 服务返回 {resp.status}")
```

### 命令处理

命令路径（`/clear`、`/help` 等）不经过 TTS，直接返回文字 + done。

## 6. 前端改动

### 音频播放队列（app.js）

```javascript
let audioQueue = [];     // base64 音频数据队列
let isPlaying = false;   // 当前是否在播放
let ttsEnabled = true;   // 语音开关

// handleSSEEvent 新增 case
case "audio":
    if (ttsEnabled) {
        audioQueue.push(data.data);
        if (!isPlaying) playNextAudio();
    }
    break;

case "audio_done":
    // 等队列播完后隐藏声波动画
    break;
```

### 逐句播放

```javascript
async function playNextAudio() {
    if (audioQueue.length === 0) {
        isPlaying = false;
        hideAudioWave();
        return;
    }

    isPlaying = true;
    showAudioWave();

    const base64Data = audioQueue.shift();
    const audioBytes = Uint8Array.from(atob(base64Data), c => c.charCodeAt(0));
    const blob = new Blob([audioBytes], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);

    const audio = new Audio(url);
    audio.onended = () => { URL.revokeObjectURL(url); playNextAudio(); };
    audio.onerror = () => { URL.revokeObjectURL(url); playNextAudio(); };
    await audio.play();
}
```

### 语音开关按钮（index.html）

```html
<!-- chat-input-area 新增 -->
<button id="tts-toggle" onclick="toggleTTS()" title="语音开关">🔊</button>
```

```javascript
function toggleTTS() {
    ttsEnabled = !ttsEnabled;
    document.getElementById("tts-toggle").textContent = ttsEnabled ? "🔊" : "🔇";
    if (!ttsEnabled) {
        audioQueue = [];    // 清空队列
        isPlaying = false;
        hideAudioWave();
    }
}
```

### 声波动画

`index.html` 已有 `#audio-wave` DOM 元素，只需控制显隐：

```javascript
function showAudioWave() { document.getElementById("audio-wave").style.display = "flex"; }
function hideAudioWave() { document.getElementById("audio-wave").style.display = "none"; }
```

## 7. 错误处理

| 场景 | 处理方式 |
|---|---|
| TTS 服务未启动 | aiohttp 连接失败 → except 捕获 → 跳过音频，只显示文字 |
| TTS 响应超时（>10 秒） | ClientTimeout 触发 → 跳过该句音频 |
| TTS 返回非 200 | 检查 resp.status → 抛异常 → 跳过 |
| 前端音频播放失败 | audio.onerror → 跳过该句，继续下一句 |
| 分句结果为空 | split_sentences 过滤空句 → 不调 TTS |

**原则：TTS 是增强功能，任何 TTS 错误不影响文字聊天。**

## 8. 文件清单

### 新增文件

| 文件 | 说明 |
|---|---|
| `tts_server.py` | TTS 独立服务（FastAPI + CosyVoice2） |
| `sentence_splitter.py` | 中文分句工具 |

### 修改文件

| 文件 | 改动内容 |
|---|---|
| `server.py` | `_event_stream` 加句子循环 + 音频推送 |
| `config.py` | 新增 `TTS_SERVER_URL` 配置项 |
| `static/js/app.js` | 新增音频队列、播放逻辑、TTS 开关 |
| `static/index.html` | 新增 🔊/🔇 按钮 |
| `requirements.txt` | 新增 `aiohttp` |
| `.gitignore` | 新增 `CosyVoice/` |
| `.env.example` | 新增 `TTS_SERVER_URL` 配置项 |

### 外部依赖（不上传）

| 目录 | 说明 |
|---|---|
| `CosyVoice/` | 官方仓库 + 模型文件（约 1GB） |

## 9. 配置

### .env 新增

```
# TTS 服务配置
TTS_SERVER_URL=http://127.0.0.1:9233/tts
TTS_SPEAKER=中文女
TTS_TIMEOUT=10
```

### config.py 新增

```python
TTS_SERVER_URL = os.getenv("TTS_SERVER_URL", "http://127.0.0.1:9233/tts")
TTS_SPEAKER = os.getenv("TTS_SPEAKER", "中文女")
TTS_TIMEOUT = int(os.getenv("TTS_TIMEOUT", "10"))
```

## 10. 启动方式

```bash
# 终端 1：启动 TTS 服务（需要 GPU，加载模型约 15 秒）
python tts_server.py

# 终端 2：启动主服务
python server.py
```

TTS 服务未启动时，主服务正常运行，只是没有语音输出。

## 11. 完整 SSE 协议（更新后）

| 事件类型 | 数据格式 | 说明 |
|---|---|---|
| `status` | `{"type":"status", "status":"thinking"}` | 状态通知 |
| `text` | `{"type":"text", "content":"句子内容"}` | 文字（逐句） |
| `audio` | `{"type":"audio", "data":"<base64 WAV>"}` | 音频（逐句） |
| `mood` | `{"type":"mood", "mood":"friendly"}` | 情绪标签 |
| `error` | `{"type":"error", "content":"错误信息"}` | 错误 |
| `audio_done` | `{"type":"audio_done"}` | 音频全部发送完毕 |
| `done` | `{"type":"done"}` | 整个响应结束 |

## 12. 测试方案

### 12.1 分句单元测试（sentence_splitter.py）

无需 GPU，直接测试分句逻辑：

```bash
python test_sentence_splitter.py
```

**测试用例：**

| 输入 | 预期输出 |
|---|---|
| `"你好呀老板～今天天气不错呢！"` | `["你好呀老板～", "今天天气不错呢！"]` |
| `"没有标点的文本"` | `["没有标点的文本"]` |
| `"空字符串"` | `[]` |
| `"。。。"` | `["。。。"]` |
| `"一句。两句。三句。"` | `["一句。", "两句。", "三句。"]` |
| `"混合,英文hello。中文！"` | `["混合,英文hello。", "中文！"]` |
| `"长文本无标点超过50字..."` | 截断为合理长度 |

### 12.2 TTS 服务独立测试（tts_server.py）

需要 GPU + CosyVoice2 模型：

```bash
# 启动 TTS 服务
python tts_server.py

# 终端 2：测试健康检查
curl http://127.0.0.1:9233/health
# 预期: {"status": "ready"}

# 测试语音合成
curl -X POST http://127.0.0.1:9233/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "你好，我是Lisa", "speaker": "中文女"}' \
  --output test_output.wav
# 预期: 生成可播放的 WAV 文件

# 测试空文本
curl -X POST http://127.0.0.1:9233/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "", "speaker": "中文女"}'
# 预期: 返回错误提示，不崩溃

# 测试超长文本
curl -X POST http://127.0.0.1:9233/tts \
  -H "Content-Type: application/json" \
  -d '{"text": "很长的文本...（500字）", "speaker": "中文女"}'
# 预期: 正常返回或返回长度限制提示
```

### 12.3 主服务集成测试（server.py → TTS）

需要 TTS 服务 + 主服务同时运行：

```bash
# 使用已有的 test_chat.py 测试
python test_chat.py
```

**验证点：**

| 检查项 | 验证方法 |
|---|---|
| SSE 事件顺序 | 日志中检查 status → text → audio → mood → done 顺序 |
| 文字逐句输出 | 浏览器聊天框中文字逐句出现，不是一次性全部出现 |
| 音频播放 | 浏览器自动播放语音，每句文字对应一段音频 |
| 声波动画 | 播放时 `#audio-wave` 显示，播完隐藏 |
| TTS 开关 | 点击 🔇 后静音，点击 🔊 恢复 |

### 12.4 降级测试

**场景：TTS 服务未启动**

```bash
# 只启动主服务，不启动 TTS
python server.py

# 发送消息
# 预期: 文字正常显示，没有音频，没有报错
# 日志: 记录 TTS 连接失败的 warning
```

**场景：TTS 服务超时**

```bash
# 在 tts_server.py 中模拟延迟（测试后移除）
# 验证: 超过 TTS_TIMEOUT 后跳过该句音频，继续下一句
```

### 12.5 测试顺序

```
1. test_sentence_splitter.py    ← 无需 GPU，最先测
2. tts_server.py 独立测试        ← 需要 GPU，验证 TTS 服务正常
3. server.py + TTS 集成测试      ← 两个服务一起跑
4. 降级测试                      ← 验证 TTS 挂了不影响聊天
5. 浏览器手动测试                ← 最终验收
```
