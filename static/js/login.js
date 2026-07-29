/* ==========================================
   显示/隐藏表单
   ========================================== */
function showRegister() {
    document.getElementById("login-section").style.display = "none";
    document.getElementById("register-section").style.display = "block";
    hideMessage();
}

function showLogin() {
    document.getElementById("register-section").style.display = "none";
    document.getElementById("login-section").style.display = "block";
    hideMessage();
}


/* ==========================================
   消息提示
   ========================================== */
function showMessage(text, type) {
    const box = document.getElementById("message-box");
    box.textContent = text;
    box.className = "message-box " + type;
    box.style.display = "block";
}

function hideMessage() {
    document.getElementById("message-box").style.display = "none";
}


/* ==========================================
   处理登录
   ========================================== */
async function handleLogin(event) {
    event.preventDefault();
    hideMessage();

    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;

    if (!username || !password) {
        showMessage("请输入用户名和密码", "error");
        return;
    }

    const btn = event.target.querySelector("button");
    btn.disabled = true;
    btn.textContent = "登录中...";

    try {
        const response = await fetch("/api/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });

        const data = await response.json();

        if (response.ok) {
            // 保存 token 到 localStorage
            localStorage.setItem("token", data.token);
            localStorage.setItem("username", data.username);
            showMessage("登录成功，正在跳转...", "success");
            // 跳转到主页
            setTimeout(() => {
                window.location.href = "/";
            }, 1000);
        } else {
            showMessage(data.detail || "登录失败", "error");
        }
    } catch (error) {
        showMessage("网络错误，请重试", "error");
    } finally {
        btn.disabled = false;
        btn.textContent = "登录";
    }
}


/* ==========================================
   处理注册
   ========================================== */
async function handleRegister(event) {
    event.preventDefault();
    hideMessage();

    const username = document.getElementById("reg-username").value.trim();
    const password = document.getElementById("reg-password").value;
    const passwordConfirm = document.getElementById("reg-password-confirm").value;

    if (!username || !password || !passwordConfirm) {
        showMessage("请填写所有字段", "error");
        return;
    }

    if (password !== passwordConfirm) {
        showMessage("两次输入的密码不一致", "error");
        return;
    }

    if (password.length < 6) {
        showMessage("密码长度至少 6 位", "error");
        return;
    }

    const btn = event.target.querySelector("button");
    btn.disabled = true;
    btn.textContent = "注册中...";

    try {
        const response = await fetch("/api/register", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password }),
        });

        const data = await response.json();

        if (response.ok) {
            showMessage("注册成功，请登录", "success");
            setTimeout(() => {
                showLogin();
            }, 1500);
        } else {
            showMessage(data.detail || "注册失败", "error");
        }
    } catch (error) {
        showMessage("网络错误，请重试", "error");
    } finally {
        btn.disabled = false;
        btn.textContent = "注册";
    }
}


/* ==========================================
   检查是否已登录
   ========================================== */
function checkAuth() {
    const token = localStorage.getItem("token");
    if (token) {
        // 已登录，直接跳转到主页
        window.location.href = "/";
    }
}

// 页面加载时检查登录状态
checkAuth();
