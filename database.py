"""
用户数据库模块
SQLite 存储用户信息，支持注册和登录。
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from sys_logger import setup_global_logger


# ==========================================
# 模块级常量
# ==========================================
DB_PATH = Path(__file__).parent / "users.db"

logger = setup_global_logger()


# ==========================================
# 数据库连接
# ==========================================
@contextmanager
def get_db():
    """
    获取数据库连接上下文管理器。

    Yields:
        sqlite3.Connection: 数据库连接对象
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# ==========================================
# 初始化数据库
# ==========================================
def init_db():
    """初始化数据库，创建用户表"""
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                hashed_password TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
    logger.info(f"数据库初始化完成: {DB_PATH}")


# ==========================================
# 创建用户
# ==========================================
def create_user(username: str, hashed_password: str) -> int:
    """
    创建新用户。

    Args:
        username: 用户名 (str)
        hashed_password: 哈希后的密码 (str)

    Returns:
        int: 新用户 ID

    Raises:
        sqlite3.IntegrityError: 用户名已存在
    """
    with get_db() as db:
        cursor = db.execute(
            "INSERT INTO users (username, hashed_password) VALUES (?, ?)",
            (username, hashed_password)
        )
        user_id = cursor.lastrowid
        logger.info(f"用户注册成功: {username} (ID: {user_id})")
        return user_id


# ==========================================
# 获取用户信息
# ==========================================
def get_user_by_username(username: str) -> dict:
    """
    根据用户名获取用户信息。

    Args:
        username: 用户名 (str)

    Returns:
        dict: 用户信息，不存在返回 None
    """
    with get_db() as db:
        row = db.execute(
            "SELECT id, username, hashed_password FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        return dict(row) if row else None
