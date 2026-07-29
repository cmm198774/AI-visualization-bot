"""
用户认证模块
JWT token 生成和验证，密码哈希。
"""
from datetime import datetime, timedelta
from typing import Optional

from jose import jwt, JWTError
from passlib.context import CryptContext

from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES


# ==========================================
# 密码哈希上下文
# ==========================================
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ==========================================
# 密码验证
# ==========================================
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    验证密码。

    Args:
        plain_password: 明文密码 (str)
        hashed_password: 哈希后的密码 (str)

    Returns:
        bool: 密码是否匹配
    """
    return pwd_context.verify(plain_password, hashed_password)


# ==========================================
# 生成密码哈希
# ==========================================
def get_password_hash(password: str) -> str:
    """
    生成密码哈希。

    Args:
        password: 明文密码 (str)

    Returns:
        str: 哈希后的密码
    """
    return pwd_context.hash(password)


# ==========================================
# 创建 JWT token
# ==========================================
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    创建 JWT access token。

    Args:
        data: token 数据 (dict)
        expires_delta: 过期时间增量 (Optional[timedelta])

    Returns:
        str: JWT token
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


# ==========================================
# 解码 JWT token
# ==========================================
def decode_access_token(token: str) -> Optional[dict]:
    """
    解码 JWT token。

    Args:
        token: JWT token (str)

    Returns:
        Optional[dict]: token 数据，无效返回 None
    """
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None
