/* ==========================================
   认证检查
   ========================================== */
const token = localStorage.getItem("token");
const username = localStorage.getItem("username");

// 严格检查：token 和 username 都必须存在且不为空
if (!token || !username || username === "undefined" || username === "null") {
    // 清除无效数据，跳转到登录页
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    window.location.href = "/static/login.html";
}

// 显示用户名
const usernameDisplay = document.getElementById("username-display");
if (usernameDisplay) {
    usernameDisplay.textContent = username;
}

// 用户 ID 使用用户名
const userId = username;


/* ==========================================
   退出登录
   ========================================== */
function logout() {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    window.location.href = "/static/login.html";
}


/* ==========================================
   情绪 emoji 映射
   ========================================== */
const MOOD_EMOJI = {
    "default": "😊",
    "upbeat": "🤩",
    "angry": "😠",
    "depressed": "😢",
    "friendly": "🥰",
    "cheerful": "😄",
};

const MOOD_LABEL = {
    "default": "平静",
    "upbeat": "兴奋",
    "angry": "生气",
    "depressed": "低落",
    "friendly": "友好",
    "cheerful": "开心",
};


/* ==========================================
   状态显示变量
   ========================================== */
let statusTimer = null
let statusSeconds = 0
const statusMessages = {
    "detecting_mood": "🎭 情绪检测",
    "compacting": "️ 整理对话",
    "thinking": "💭 思考",
    "tool_call": "🔍 查询",
}


/* ==========================================
   状态显示函数
   ========================================== */
function showStatus(status, tool) {
    statusSeconds = 0
    const statusEl = document.getElementById("status-display")
    const statusText = statusMessages[status] || "处理中"

    if (statusEl) {
        statusEl.style.display = "block"
        statusEl.textContent = `${statusText} ${statusSeconds}s`
    }

    if (statusTimer) clearInterval(statusTimer)
    statusTimer = setInterval(() => {
        statusSeconds++
        if (statusEl) {
            statusEl.textContent = `${statusText} ${statusSeconds}s`
        }
    }, 1000)
}

function hideStatus() {
    const statusEl = document.getElementById("status-display")
    if (statusEl) statusEl.style.display = "none"
    if (statusTimer) {
        clearInterval(statusTimer)
        statusTimer = null
    }
}


/* ==========================================
   状态变量
   ========================================== */
let currentBotMsg = null;
let currentBotText = "";

// 音频队列 + 文字队列（同步显示）
let audioQueue = [];
let textQueue = [];
let isPlaying = false;
let ttsEnabled = true;


/* ==========================================
   音频播放
   ========================================== */
function showAudioWave() {
    const wave = document.getElementById("audio-wave");
    if (wave) wave.style.display = "flex";
}

function hideAudioWave() {
    const wave = document.getElementById("audio-wave");
    if (wave) wave.style.display = "none";
}

function playNextAudio() {
    if (audioQueue.length === 0) {
        console.log("[Audio] queue empty, stop playing");
        isPlaying = false;
        hideAudioWave();
        return;
    }

    console.log("[Audio] playNextAudio, audioQueue=" + audioQueue.length + ", textQueue=" + textQueue.length);
    isPlaying = true;
    showAudioWave();

    // 显示对应的文字（文字和音频同步）
    if (textQueue.length > 0) {
        var nextText = textQueue.shift();
        currentBotText += nextText;
        if (currentBotMsg) {
            currentBotMsg.textContent = currentBotText;
        }
        scrollToBottom();
    }

    const base64Data = audioQueue.shift();
    const audioBytes = Uint8Array.from(atob(base64Data), function(c) { return c.charCodeAt(0); });
    const blob = new Blob([audioBytes], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);

    const audio = new Audio(url);
    audio.onended = function() {
        console.log("[Audio] ended");
        URL.revokeObjectURL(url);
        playNextAudio();
    };
    audio.onerror = function(e) {
        console.error("[Audio] error:", e);
        URL.revokeObjectURL(url);
        playNextAudio();
    };
    audio.play().then(function() {
        console.log("[Audio] playing started");
    }).catch(function(e) {
        console.error("[Audio] play failed:", e);
    });
}

function toggleTTS() {
    ttsEnabled = !ttsEnabled;
    var btn = document.getElementById("tts-toggle");
    if (btn) btn.textContent = ttsEnabled ? "🔊" : "🔇";
    if (!ttsEnabled) {
        audioQueue = [];
        textQueue = [];
        isPlaying = false;
        hideAudioWave();
    }
}


/* ==========================================
   发送消息并接收 SSE 流式响应
   ========================================== */
async function sendMessage() {
    const input = document.getElementById("chat-input");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    appendMessage("user", text);

    // 创建 bot 消息占位
    currentBotMsg = appendMessage("bot", "");
    currentBotText = "";
    audioQueue = [];
    textQueue = [];
    isPlaying = false;
    const cursor = document.createElement("span");
    cursor.className = "typing-cursor";
    currentBotMsg.appendChild(cursor);

    try {
        const response = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query: text, user_id: userId }),
        });

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop(); // 保留不完整的行

            for (const line of lines) {
                if (line.startsWith("data: ")) {
                    const dataStr = line.slice(6).trim();
                    if (!dataStr) continue;
                    try {
                        const data = JSON.parse(dataStr);
                        handleSSEEvent(data, cursor);
                    } catch (e) {
                        // 跳过无法解析的行
                    }
                }
            }
        }
    } catch (error) {
        if (currentBotMsg) {
            currentBotMsg.textContent = "连接失败，请检查服务器是否运行。";
        }
    }

    // 清理光标
    if (currentBotMsg && currentBotMsg.querySelector(".typing-cursor")) {
        currentBotMsg.querySelector(".typing-cursor").remove();
    }
    currentBotMsg = null;
    currentBotText = "";
}


/* ==========================================
   处理 SSE 事件
   ========================================== */
function handleSSEEvent(data, cursor) {
    switch (data.type) {
        case "status":
            showStatus(data.status, data.tool)
            break

        case "text":
            hideStatus()
            if (ttsEnabled) {
                // TTS 开启时，文字进入队列，等音频播放时才显示
                textQueue.push(data.content);
                console.log("[SSE] text queued, textQueue.length=" + textQueue.length);
            } else {
                // TTS 关闭时，直接显示文字
                currentBotText += data.content;
                if (currentBotMsg) {
                    currentBotMsg.textContent = currentBotText;
                    if (cursor) currentBotMsg.appendChild(cursor);
                }
                scrollToBottom();
            }
            break;

        case "mood":
            updateMood(data.mood);
            break;

        case "audio":
            if (ttsEnabled) {
                audioQueue.push(data.data);
                console.log("[SSE] audio queued, audioQueue.length=" + audioQueue.length);
                if (!isPlaying) playNextAudio();
            }
            break;

        case "audio_done":
            console.log("[SSE] audio_done, textQueue=" + textQueue.length + ", audioQueue=" + audioQueue.length);
            // 队列会在播完后自动隐藏声波动画
            // 刷新残余文字（防止 TTS 失败导致文字丢失）
            if (ttsEnabled && textQueue.length > 0) {
                while (textQueue.length > 0) {
                    currentBotText += textQueue.shift();
                }
                if (currentBotMsg) {
                    currentBotMsg.textContent = currentBotText;
                }
                scrollToBottom();
            }
            break;

        case "error":
            hideStatus()
            if (currentBotMsg) {
                currentBotText += "\n[错误：" + data.content + "]";
                currentBotMsg.textContent = currentBotText;
            }
            break;

        case "done":
            hideStatus()
            if (cursor && cursor.parentNode) cursor.remove();
            break;
    }
}


/* ==========================================
   追加消息气泡
   ========================================== */
function appendMessage(role, text) {
    const container = document.getElementById("chat-messages");
    const div = document.createElement("div");
    div.className = `message ${role}`;
    div.textContent = text;
    container.appendChild(div);
    scrollToBottom();
    return div;
}


/* ==========================================
   更新情绪指示器
   ========================================== */
function updateMood(mood) {
    const emoji = MOOD_EMOJI[mood] || "😊";
    const label = MOOD_LABEL[mood] || mood;
    document.getElementById("mood-text").textContent = `Lisa 心情：${label}`;
    document.querySelector(".mood-indicator .emoji").textContent = emoji;
}


/* ==========================================
   滚动到底部
   ========================================== */
function scrollToBottom() {
    const container = document.getElementById("chat-messages");
    container.scrollTop = container.scrollHeight;
}


/* ==========================================
   回车发送
   ========================================== */
document.getElementById("chat-input").addEventListener("keydown", function(e) {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});
