"""
Redis 服务器管理模块
提供启动和停止本地 Redis 服务器的功能
"""
import atexit
import os
import socket
import subprocess
import time

from sys_logger import setup_global_logger


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()

# 全局变量，保存 Redis 进程
_redis_process = None


# ==========================================
# 启动 Redis 服务器
# ==========================================
def start_redis_server():
    """
    启动 Redis 服务器，如果已在运行则跳过。

    Returns:
        subprocess.Popen: Redis 进程对象，如果已在运行则返回 None
    """
    global _redis_process

    # 检查是否已有 Redis 在运行
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(1)
        sock.connect(("127.0.0.1", 6379))
        logger.info("[Redis] 已在运行")
        sock.close()
        return None
    except (ConnectionRefusedError, socket.timeout):
        pass
    finally:
        sock.close()

    # 项目目录
    project_dir = os.path.dirname(os.path.abspath(__file__))
    redis_exe = os.path.join(project_dir, "redis-server", "redis-server.exe")
    redis_conf = os.path.join(project_dir, "redis_cache", "redis.conf")
    redis_data_dir = os.path.join(project_dir, "redis_cache")

    # 创建 redis_cache 目录
    os.makedirs(redis_data_dir, exist_ok=True)

    # 创建配置文件
    if not os.path.exists(redis_conf):
        with open(redis_conf, "w", encoding="utf-8") as f:
            f.write("dir redis_cache\nbind 127.0.0.1\nport 6379\nloglevel notice\n")

    # 启动 Redis
    _redis_process = subprocess.Popen(
        [redis_exe, redis_conf],
        cwd=project_dir,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    logger.info(f"[Redis] 服务器启动 (PID: {_redis_process.pid})")

    # 注册退出时自动关闭
    atexit.register(stop_redis_server)

    # 等待启动完成
    time.sleep(1)
    return _redis_process


# ==========================================
# 停止 Redis 服务器
# ==========================================
def stop_redis_server():
    """停止 Redis 服务器"""
    global _redis_process
    if _redis_process and _redis_process.poll() is None:
        _redis_process.terminate()
        try:
            _redis_process.wait(timeout=3)
            logger.info("[Redis] 服务器已停止")
        except subprocess.TimeoutExpired:
            _redis_process.kill()
            logger.warning("[Redis] 强制停止")
    _redis_process = None
