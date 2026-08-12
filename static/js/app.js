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


/* ==========================================
   关闭 WebRTC 连接
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

    const placeholder = document.getElementById("avatar-placeholder");
    if (placeholder) {
        placeholder.innerHTML = '<div class="icon">📡</div><div><small>数字人未连接</small></div>';
        placeholder.style.display = "flex";
        placeholder.classList.remove("unavailable");
    }
}


/* ==========================================
   初始化 LiveTalking WebRTC 连接（返回 Promise）
   ========================================== */
function initLiveTalking() {
    return new Promise(function(resolve, reject) {
        const videoElement = document.getElementById("livetalking-video");
        const placeholder = document.getElementById("avatar-placeholder");

        if (!videoElement) {
            reject(new Error("video element not found"));
            return;
        }

        if (placeholder) {
            placeholder.innerHTML = '<div class="icon">📡</div><div><small>连接 LiveTalking...</small></div>';
            placeholder.style.display = "flex";
            placeholder.classList.remove("unavailable");
        }

        try {
            pc = new RTCPeerConnection({ sdpSemantics: "unified-plan" });

            pc.addEventListener("track", function(evt) {
                console.log("[LiveTalking] received track:", evt.track.kind);
                if (evt.track.kind === "video") {
                    videoElement.srcObject = evt.streams[0];
                    // Edge/Chromium 需要显式调用 play()
                    videoElement.play().catch(function(e) {
                        console.warn("[LiveTalking] autoplay failed:", e.message);
                    });
                }
            });

            pc.onconnectionstatechange = function() {
                console.log("[LiveTalking] connection state:", pc.connectionState);
                if (pc.connectionState === "connected") {
                    livetalkingReady = true;
                    if (placeholder) placeholder.style.display = "none";
                    console.log("[LiveTalking] WebRTC connected, sessionid:", livetalkingSessionId);
                    resolve();
                } else if (pc.connectionState === "failed" || pc.connectionState === "disconnected") {
                    livetalkingReady = false;
                    reject(new Error("connection " + pc.connectionState));
                }
            };

            pc.addTransceiver("video", { direction: "recvonly" });
            pc.addTransceiver("audio", { direction: "recvonly" });

            // 15 秒连接超时（Edge 下 ICE 可能卡住）
            var connectTimeout = setTimeout(function() {
                if (!livetalkingReady) {
                    pc.close();
                    reject(new Error("WebRTC 连接超时（15s）"));
                }
            }, 15000);

            pc.createOffer().then(function(offer) {
                return pc.setLocalDescription(offer);
            }).then(function() {
                return waitForIceGathering(pc);
            }).then(function() {
                console.log("[LiveTalking] sending offer, SDP length:", pc.localDescription.sdp.length);
                return fetch(LIVETALKING_URL + "/offer", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        sdp: pc.localDescription.sdp,
                        type: pc.localDescription.type,
                    }),
                });
            }).then(function(response) {
                if (!response.ok) {
                    return response.text().then(function(t) {
                        throw new Error("/offer HTTP " + response.status + ": " + t.substring(0, 200));
                    });
                }
                return response.json();
            }).then(function(answer) {
                if (answer.sessionid) {
                    livetalkingSessionId = String(answer.sessionid);
                }
                return pc.setRemoteDescription(new RTCSessionDescription(answer));
            }).then(function() {
                console.log("[LiveTalking] SDP exchange complete");
            }).catch(function(err) {
                clearTimeout(connectTimeout);
                reject(err);
            });

            // 连接成功后清除超时
            var origOnStateChange = pc.onconnectionstatechange;
            pc.onconnectionstatechange = function() {
                if (pc.connectionState === "connected") {
                    clearTimeout(connectTimeout);
                }
                if (origOnStateChange) origOnStateChange.call(pc);
            };

        } catch (err) {
            reject(err);
        }
    });
}


/* ==========================================
   页面加载时自动连接 LiveTalking
   ========================================== */
function autoConnectLiveTalking() {
    initLiveTalking().then(function() {
        console.log("[LiveTalking] auto connect success");
    }).catch(function(err) {
        console.warn("[LiveTalking] auto connect failed:", err.message);
        livetalkingReady = false;
        var placeholder = document.getElementById("avatar-placeholder");
        if (placeholder) {
            placeholder.innerHTML = '<div class="icon">⚠️</div><div><small>数字人不可用</small></div>';
            placeholder.style.display = "flex";
            placeholder.classList.add("unavailable");
        }
    });
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
   发送文字到 LiveTalking（不可用时静默跳过）
   ========================================== */
function sendToLiveTalking(text) {
    if (!livetalkingReady || !text) return;

    console.log("[LiveTalking] sending text:", text.substring(0, 50) + "...");

    fetch(LIVETALKING_URL + "/human", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            text: text,
            type: "echo",
            interrupt: false,
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
            // 把文字发给 LiveTalking 让数字人说话
            sendToLiveTalking(data.content);
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
   页面加载时自动连接 LiveTalking
   ========================================== */
window.addEventListener("DOMContentLoaded", function() {
    autoConnectLiveTalking();
});
