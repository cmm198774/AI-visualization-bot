"""
工具模块
Phase 1 仅包含 Qdrant RAG 知识库检索工具。
"""
import os
import sys
import ssl

from langchain_core.tools import tool
from langchain_core.documents import Document
from langchain_community.vectorstores import Qdrant
from langchain_community.embeddings import DashScopeEmbeddings
from qdrant_client import QdrantClient
from typing import List

from config import (
    DASHSCOPE_API_KEY,
    EMBEDDING_MODEL,
    QDRANT_HOST,
    QDRANT_PORT,
    QDRANT_COLLECTION,
    QDRANT_BASE_DIR,
)
from sys_logger import setup_global_logger


# ==========================================
# Windows SSL 证书修复
# ==========================================
if sys.platform == "win32":
    try:
        import certifi
        os.environ["SSL_CERT_FILE"] = certifi.where()
        os.environ["REQUESTS_CA_BUNDLE"] = certifi.where()
    except ImportError:
        pass
    if hasattr(ssl.SSLContext, "_load_windows_store_certs"):
        ssl.SSLContext._load_windows_store_certs = lambda self, storename, purpose: None


# ==========================================
# 模块级 logger
# ==========================================
logger = setup_global_logger()

# 全局 retriever 单例
_retriever = None
_qdrant_client = None


# ==========================================
# 获取 Qdrant retriever 单例
# ==========================================
def _get_retriever(file_name: str) -> Qdrant:
    """
    获取 Qdrant retriever 单例，首次调用时初始化。

    Args:
        file_name: Qdrant collection 名称 (str)

    Returns:
        Qdrant: Qdrant retriever 实例
    """
    global _retriever, _qdrant_client
    if _retriever is None:
        if os.path.exists("/.dockerenv"):
            _qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, prefer_grpc=False)
        else:
            _qdrant_client = QdrantClient(path=QDRANT_BASE_DIR, prefer_grpc=False)
        store = Qdrant(
            _qdrant_client,
            file_name,
            DashScopeEmbeddings(
                model=EMBEDDING_MODEL,
                dashscope_api_key=DASHSCOPE_API_KEY,
            ),
        )
        _retriever = store.as_retriever(search_type="mmr")
    return _retriever


# ==========================================
# 知识库检索工具
# ==========================================
@tool
def get_info_from_local_db(query: str) -> str:
    """
    查询本地知识库，检索相关信息。
    输入查询关键词，返回知识库中的相关文本。

    Args:
        query: 查询关键词 (str)

    Returns:
        str: 检索到的相关文本内容
    """
    logger.debug(f"工具调用: get_info_from_local_db, query={query}")
    try:
        retriever = _get_retriever(file_name=QDRANT_COLLECTION)
        docs: List[Document] = retriever.invoke(query)

        if not docs:
            return "知识库中未找到相关信息。"

        # 改进: 返回纯文本字符串而不是 Document 对象
        result = "\n\n".join(doc.page_content for doc in docs)
        logger.debug(f"工具返回: {len(docs)} 条结果, 总长度={len(result)} 字符")
        return result
    except Exception as e:
        logger.warning(f"知识库查询失败: {e}")
        return f"知识库暂时无法查询: {str(e)[:100]}。请直接回答用户问题。"


# ==========================================
# 工具描述（供 Agent system prompt 使用）
# ==========================================
TOOL_DESCRIPTIONS = (
    "【可用工具】\n"
    "    - get_info_from_local_db: 查询本地知识库，检索相关信息。(参数: query=查询关键词)\n"
    "根据用户问题选择合适的时机调用工具。"
)
