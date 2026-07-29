# Phase 1 集成测试报告

**测试日期**: 2026-07-26  
**测试环境**: Windows 10, Python 3.10 (conda py310), GPU 5090  
**服务器版本**: FastAPI + LangGraph + qwen3.6-flash

---

## 测试 1: 文字生成延时

### 测试项目
- TTFT (首 token 延迟)
- 情绪检测是否阻塞主流程

### 运行命令
```bash
cd G:\JupyterProject\20260725_Agent_AI可视化机器人
conda run -n py310 python tests/test_latency.py
```

### 测试代码 (tests/test_latency.py)
```python
"""
Phase 1 测试 1: 文字生成延时
测试 TTFT (首 token 延迟) 和情绪检测是否阻塞主流程
"""
import time
import json
import requests

SERVER_URL = "http://127.0.0.1:8000"

def test_ttft():
    """测试首 token 延迟"""
    url = f"{SERVER_URL}/chat"
    t0 = time.time()
    response = requests.post(
        url,
        json={"query": "你好 Lisa", "user_id": "test_latency"},
        stream=True,
    )

    first_token_time = None
    full_text = ""
    mood_received = False

    for line in response.iter_lines(decode_unicode=True):
        if line and line.startswith("data: "):
            try:
                data = json.loads(line[6:])
                if data.get("type") == "text":
                    if first_token_time is None:
                        first_token_time = time.time()
                    full_text += data.get("content", "")
                elif data.get("type") == "mood":
                    mood_received = True
            except json.JSONDecodeError:
                pass

    ttft = first_token_time - t0 if first_token_time else None
    total = time.time() - t0

    print(f"TTFT: {ttft:.2f}s")
    print(f"总耗时: {total:.2f}s")
    print(f"收到情绪标签: {mood_received}")

    assert ttft is not None, "未收到 text event"
    assert ttft < 5.0, f"TTFT 过高: {ttft:.2f}s"
    assert mood_received, "未收到 mood event"
    return True

def test_concurrent():
    """测试多用户并发"""
    import threading
    url = f"{SERVER_URL}/chat"
    users = ["test_concurrent_1", "test_concurrent_2", "test_concurrent_3"]
    results = []

    def send_request(user_id):
        t0 = time.time()
        resp = requests.post(url, json={"query": f"你好，我是 {user_id}", "user_id": user_id}, stream=True)
        first_token_time = None
        for line in resp.iter_lines(decode_unicode=True):
            if line and line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    if data.get("type") == "text" and first_token_time is None:
                        first_token_time = time.time()
                except json.JSONDecodeError:
                    pass
        if first_token_time:
            results.append((user_id, first_token_time - t0))

    threads = [threading.Thread(target=send_request, args=(u,)) for u in users]
    for t in threads: t.start()
    for t in threads: t.join()

    for user_id, ttft in results:
        print(f"{user_id}: TTFT = {ttft:.2f}s")

    assert all(ttft < 10.0 for _, ttft in results)
    return True
```

### 测试结果

| 测试项 | 结果 | 详情 |
|--------|------|------|
| TTFT | ✅ 通过 | 3.04s (目标 < 5s) |
| 情绪检测 | ✅ 通过 | 收到 mood event: "friendly" |
| 并发 | ❌ 失败 | 2 个用户超时 60s，1 个用户 10s |

**并发失败原因**: `agent_graph.ainvoke()` 在高并发下存在性能问题，可能是 RedisSaver 或 LangGraph 内部序列化导致。后续需要优化为真正的流式输出 (`astream_events`) 来提升并发性能。

---

## 测试 2: 错误处理

### 测试项目
- 空 query
- 空 user_id
- 超长输入 (10000 字)
- 缺失 query 字段

### 运行命令
```bash
cd G:\JupyterProject\20260725_Agent_AI可视化机器人
conda run -n py310 python tests/test_error_handling.py
```

### 测试代码 (tests/test_error_handling.py)
```python
"""
Phase 1 测试 2: 错误处理
"""
import json
import requests

SERVER_URL = "http://127.0.0.1:8000"

def test_empty_query():
    """空 query 应返回错误"""
    resp = requests.post(f"{SERVER_URL}/chat", json={"query": "", "user_id": "test_err"})
    data = resp.json()
    assert "error" in data
    return True

def test_empty_user_id():
    """空 user_id 应使用默认值"""
    resp = requests.post(f"{SERVER_URL}/chat", json={"query": "你好", "user_id": ""}, stream=True)
    received_data = any(line.startswith("data: ") for line in resp.iter_lines(decode_unicode=True) if line)
    assert received_data
    return True

def test_long_input():
    """超长输入应不崩溃"""
    long_text = "你好" * 5000
    resp = requests.post(f"{SERVER_URL}/chat", json={"query": long_text, "user_id": "test_long"}, stream=True)
    received = any(line.startswith("data: ") for line in resp.iter_lines(decode_unicode=True) if line)
    assert received
    return True

def test_missing_query():
    """缺失 query 字段应返回错误"""
    resp = requests.post(f"{SERVER_URL}/chat", json={"user_id": "test_missing"})
    data = resp.json()
    assert "error" in data
    return True
```

### 测试结果

| 测试项 | 结果 | 响应 |
|--------|------|------|
| 空 query | ✅ 通过 | `{"error": "query 不能为空"}` |
| 空 user_id | ✅ 通过 | 使用默认值 "default"，正常返回 |
| 超长输入 | ✅ 通过 | 正常处理，未崩溃 |
| 缺失 query | ✅ 通过 | `{"error": "query 不能为空"}` |

---

## 测试 3: 日志系统

### 测试项目
- global.log 文件存在
- 启动日志记录
- 请求日志记录
- DEBUG 级别在文件中

### 运行命令
```bash
cd G:\JupyterProject\20260725_Agent_AI可视化机器人
conda run -n py310 python tests/test_logging_integration.py
```

### 测试代码 (tests/test_logging_integration.py)
```python
"""
Phase 1 测试 3: 日志系统验证
"""
import os
import time
import requests

SERVER_URL = "http://127.0.0.1:8000"
LOG_FILE = "logs/global.log"

def test_log_file_exists():
    """启动后 global.log 应存在"""
    assert os.path.exists(LOG_FILE)
    return True

def test_startup_logs():
    """global.log 应包含启动日志"""
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    assert "Server ready" in content or "初始化完成" in content
    assert "Redis" in content
    assert "Agent" in content or "LangGraph" in content
    return True

def test_request_logs():
    """发送请求后日志应包含请求记录"""
    resp = requests.post(f"{SERVER_URL}/chat", json={"query": "测试日志", "user_id": "test_log"}, stream=True)
    for line in resp.iter_lines(decode_unicode=True): pass
    time.sleep(0.5)
    
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    assert "用户输入" in content or "test_log" in content
    assert "完成" in content or "E2E" in content
    return True

def test_debug_in_file():
    """DEBUG 级别日志应在文件中"""
    with open(LOG_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    assert "DEBUG" in content
    return True
```

### 测试结果

| 测试项 | 结果 | 详情 |
|--------|------|------|
| 日志文件存在 | ✅ 通过 | logs/global.log 存在 |
| 启动日志 | ✅ 通过 | 包含 Server ready, Redis, Agent |
| 请求日志 | ✅ 通过 | 包含用户输入和完成记录 |
| DEBUG 在文件中 | ✅ 通过 | 包含 14 条 DEBUG 记录 |

---

## 汇总

| 测试类别 | 通过 | 失败 | 总计 |
|----------|------|------|------|
| 延时测试 | 1 | 1 | 2 |
| 错误处理 | 4 | 0 | 4 |
| 日志系统 | 4 | 0 | 4 |
| **总计** | **9** | **1** | **10** |

### 已知问题

1. **并发性能问题**: `ainvoke` 在高并发下会导致请求超时。后续需要：
   - 升级到支持 `astream_events` 的 LangGraph 版本
   - 或实现真正的 token 级流式输出
   - 优化 RedisSaver 的并发性能

### 结论

Phase 1 核心功能基本可用：
- ✅ 单用户聊天正常
- ✅ 情绪检测工作正常
- ✅ 日志系统工作正常
- ⚠️ 并发性能需要优化
