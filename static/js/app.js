/* ==========================================
   认证检查
   ========================================== */
const token = localStorage.getItem("token");
const username = localStorage.getItem("username");

if (!token || !username || username === "undefined" || username === "null") {
    localStorage.removeItem("token");
    localStorage.removeItem("username");
    window.location.href = "/static/login.html";
}

const usernameDisplay = document.getElementById("username-display");
if (usernameDisplay) {
    usernameDisplay.textContent = username;
}

const userId = username;


/* ==========================================
   LiveTalking WebRTC 管理
   ========================================== */
const LIVETALKING_URL = "http://localhost:8010";

let pc = null;
let livetalkingReady = false;
let livetalkingSessionId = "0";

// 文字缓冲：收集 SSE 文字 chunk，按句拆分发给 LiveTalking
let pendingText = "";
let textSendTimer = null;
const TEXT_SEND_DELAY = 500; // 500ms 无新 chunk 就发送

// 句子队列：按顺序发送，每句间隔 1 秒
let sentenceQueue = [];
let isSendingSentence = false;
const SENTENCE_INTERVAL = 1000; // 每句间隔 1 秒


/* ==========================================
   关闭现有 WebRTC 连接（登出/结束按钮时调用）
   ========================================== */
function closeLiveTalking() {
    console.log("[LiveTalking] closing connection...");
    livetalkingReady = false;

    if (pc) {
        pc.close();
        pc = null;
    }

    const video = document.getElementById("livetalking-video");
    if (video) video.srcObject = null;

    // 恢复占位符
    const placeholder = document.getElementById("avatar-placeholder");
    if (placeholder) {
        placeholder.style.display = "flex";
    }

    // 恢复按钮状态：显示「开始」，隐藏「结束」
    updateAvatarButtons(false);
}


/* ==========================================
   更新控制按钮显示状态
   ========================================== */
function updateAvatarButtons(connected) {
    var startBtn = document.getElementById("start-btn");
    var stopBtn = document.getElementById("stop-btn");
    var statusEl = document.getElementById("avatar-status");
    if (connected) {
        if (startBtn) startBtn.style.display = "none";
        if (stopBtn) stopBtn.style.display = "inline-block";
        if (statusEl) { statusEl.textContent = "已连接"; statusEl.className = "avatar-status connected"; }
    } else {
        if (startBtn) startBtn.style.display = "inline-block";
        if (stopBtn) stopBtn.style.display = "none";
        if (statusEl) { statusEl.textContent = "未连接"; statusEl.className = "avatar-status"; }
    }
}


/* ==========================================
   内部：清理旧连接（不操作按钮，供 initLiveTalking 使用）
   ========================================== */
function _resetLiveTalking() {
    livetalkingReady = false;
    if (pc) {
        pc.close();
        pc = null;
    }
    const video = document.getElementById("livetalking-video");
    if (video) video.srcObject = null;
}


/* ==========================================
   点击「开始」按钮 → 建立 WebRTC 连接
   ========================================== */
function startLiveTalking() {
    // 先清理旧连接（防止 session 泄漏），不操作按钮
    _resetLiveTalking();
    // 立即切换按钮，防止重复点击
    updateAvatarButtons(true);
    initLiveTalking();
}


/* ==========================================
   点击「结束」按钮 → 关闭 WebRTC 连接
   ========================================== */
function stopLiveTalking() {
    closeLiveTalking();
}


/* ==========================================
   初始化 LiveTalking WebRTC 连接
   ========================================== */
async function initLiveTalking() {
    // 按钮状态由 startLiveTalking() 控制，这里不再操作按钮

    const videoElement = document.getElementById("livetalking-video");
    const placeholder = document.getElementById("avatar-placeholder");

    if (!videoElement) {
        console.error("[LiveTalking] video element not found");
        return;
    }

    // 重置占位符
    if (placeholder) {
        placeholder.innerHTML = '<div class="icon">📡</div><div><small>连接 LiveTalking...</small></div>';
        placeholder.style.display = "flex";
    }

    try {
        // 创建 RTCPeerConnection
        pc = new RTCPeerConnection({ sdpSemantics: "unified-plan" });

        // 监听视频/音频轨道
        pc.addEventListener("track", function(evt) {
            console.log("[LiveTalking] received track:", evt.track.kind);
            if (evt.track.kind === "video") {
                videoElement.srcObject = evt.streams[0];
            }
        });

        // 监听连接状态
        pc.onconnectionstatechange = function() {
            console.log("[LiveTalking] connection state:", pc.connectionState);
            if (pc.connectionState === "connected") {
                livetalkingReady = true;
                if (placeholder) placeholder.style.display = "none";
                console.log("[LiveTalking] WebRTC connected, sessionid:", livetalkingSessionId);
            } else if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
                livetalkingReady = false;
                if (placeholder) {
                    placeholder.innerHTML = '<div class="icon">❌</div><div><small>连接失败</small></div>';
                    placeholder.style.display = "flex";
                }
                updateAvatarButtons(false);
            }
        };

        // 添加 recvonly transceiver（aiortc 必须）
        pc.addTransceiver("video", { direction: "recvonly" });
        pc.addTransceiver("audio", { direction: "recvonly" });

        // 创建 offer
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);

        // 等待 ICE 收集完成
        await waitForIceGathering(pc);

        console.log("[LiveTalking] sending offer, SDP length:", pc.localDescription.sdp.length);

        // 发送 offer
        const response = await fetch(LIVETALKING_URL + "/offer", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                sdp: pc.localDescription.sdp,
                type: pc.localDescription.type,
            }),
        });

        if (!response.ok) {
            const errText = await response.text();
            throw new Error("/offer HTTP " + response.status + ": " + errText.substring(0, 200));
        }

        const answer = await response.json();

        if (answer.sessionid) {
            livetalkingSessionId = String(answer.sessionid);
        }

        await pc.setRemoteDescription(new RTCSessionDescription(answer));
        console.log("[LiveTalking] SDP exchange complete");

    } catch (err) {
        console.error("[LiveTalking] init failed:", err);
        if (placeholder) {
            placeholder.innerHTML = '<div class="icon"></div><div><small>连接失败: ' + err.message + '</small></div>';
        }
    }
}


/* ==========================================
   等待 ICE 收集完成
   ========================================== */
function waitForIceGathering(pc) {
    return new Promise(function(resolve) {
        if (pc.iceGatheringState === "complete") {
            resolve();
        } else {
            function checkState() {
                if (pc.iceGatheringState === "complete") {
                    pc.removeEventListener("icegatheringstatechange", checkState);
                    resolve();
                }
            }
            pc.addEventListener("icegatheringstatechange", checkState);
            setTimeout(resolve, 5000);
        }
    });
}


/* ==========================================
   发送文字到 LiveTalking（缓冲合并，避免频繁请求）
   ========================================== */
function sendToLiveTalking() {
    if (!livetalkingReady || !pendingText) return;

    const textToSend = pendingText;
    pendingText = "";

    console.log("[LiveTalking] sending text:", textToSend.substring(0, 50) + "...");

    fetch(LIVETALKING_URL + "/human", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            text: textToSend,
            type: "echo",
            interrupt: true,
            sessionid: livetalkingSessionId,
        }),
    })
    .then(function(res) {
        if (!res.ok) {
            console.error("[LiveTalking] /human HTTP error:", res.status);
            return null;
        }
        return res.json();
    })
    .then(function(data) {
        if (data) console.log("[LiveTalking] /human done");
    })
    .catch(function(err) {
        console.error("[LiveTalking] /human error:", err);
    });
}

function flushPendingText() {
    if (pendingText) {
        sendToLiveTalking();
    }
    if (textSendTimer) {
        clearTimeout(textSendTimer);
        textSendTimer = null;
    }
}


/* ==========================================
   退出登录（先关闭 WebRTC 连接）
   ========================================== */
function logout() {
    closeLiveTalking();
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
   状态显示
   ========================================== */
let statusTimer = null
let statusSeconds = 0
const statusMessages = {
    "detecting_mood": " 情绪检测",
    "compacting": "️ 整理对话",
    "thinking": "💭 思考",
    "tool_call": "🔍 查询",
}

function showStatus(status, tool) {
    statusSeconds = 0
    const statusEl = document.getElementById("status-display")
    const statusText = statusMessages[status] || "处理中"

    if (statusEl) {
        statusEl.style.display = "block"
        statusEl.textContent = statusText + " " + statusSeconds + "s"
    }

    if (statusTimer) clearInterval(statusTimer)
    statusTimer = setInterval(function() {
        statusSeconds++
        if (statusEl) {
            statusEl.textContent = statusText + " " + statusSeconds + "s"
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
   消息状态
   ========================================== */
let currentBotMsg = null;
let currentBotText = "";


/* ==========================================
   发送消息并接收 SSE 流式响应
   ========================================== */
async function sendMessage() {
    const input = document.getElementById("chat-input");
    const text = input.value.trim();
    if (!text) return;

    input.value = "";
    appendMessage("user", text);

    // 重置 LiveTalking 文字缓冲
    pendingText = "";
    flushPendingText();

    // 创建 bot 消息占位
    currentBotMsg = appendMessage("bot", "");
    currentBotText = "";
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
            buffer = lines.pop();

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
            showStatus(data.status, data.tool);
            break;

        case "text":
            hideStatus();
            currentBotText += data.content;
            if (currentBotMsg) {
                currentBotMsg.textContent = currentBotText;
                if (cursor) currentBotMsg.appendChild(cursor);
            }
            scrollToBottom();

            // 缓冲文字（不立即发送，等 done 或超时后一次性发）
            pendingText += data.content;
            if (textSendTimer) clearTimeout(textSendTimer);
            textSendTimer = setTimeout(flushPendingText, TEXT_SEND_DELAY);
            break;

        case "mood":
            updateMood(data.mood);
            break;

        case "error":
            hideStatus();
            if (currentBotMsg) {
                currentBotText += "\n[错误：" + data.content + "]";
                currentBotMsg.textContent = currentBotText;
            }
            break;

        case "done":
            hideStatus();
            if (cursor && cursor.parentNode) cursor.remove();
            // 发送剩余文字到 LiveTalking
            flushPendingText();
            break;
    }
}


/* ==========================================
   追加消息气泡
   ========================================== */
function appendMessage(role, text) {
    const container = document.getElementById("chat-messages");
    const div = document.createElement("div");
    div.className = "message " + role;
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
    document.getElementById("mood-text").textContent = "Lisa 心情：" + label;
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


/* ==========================================
   页面卸载时主动关闭 WebRTC 连接（防止 LiveTalking session 泄漏）
   ========================================== */
window.addEventListener("beforeunload", function() {
    console.log("[LiveTalking] page unloading, closing connection");
    if (pc) {
        pc.close();
        pc = null;
    }
    livetalkingReady = false;
});


/* ==========================================
   页面加载时不自动连接，等用户点击按钮
   ========================================== */
// initLiveTalking() 由"连接"按钮触发
