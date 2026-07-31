"""
中文分句工具模块
按中文标点将文本拆分为句子列表。
"""
import re


# ==========================================
# 分句分隔符
# ==========================================
SENTENCE_SEPARATORS = re.compile(r"([。！？～；…，、])")


# ==========================================
# 分句函数
# ==========================================
def split_sentences(text: str) -> list:
    """
    按中文标点分句，保留标点在句尾。

    Args:
        text: 输入文本 (str)

    Returns:
        list[str]: 句子列表

    Rules:
        - 分隔符: 。！？～；…，、
        - 无标点的尾部文本也作为一个句子
        - 空句子和纯空白句子过滤掉
    """
    if not text or not text.strip():
        return []

    # 用正则按分隔符拆分，保留分隔符
    parts = SENTENCE_SEPARATORS.split(text)

    # 重新组合：把分隔符粘回前面的文本
    # 连续标点不拆分，合并为一句
    sentences = []
    current = ""
    for part in parts:
        if SENTENCE_SEPARATORS.match(part):
            # 当前 part 是分隔符
            if current:
                # current 有内容 → 构成完整句子
                sentences.append(current + part)
                current = ""
            else:
                # current 为空（连续标点）→ 合并到上一句
                if sentences:
                    sentences[-1] += part
                else:
                    current = part
        else:
            # 当前 part 是文本 → 追加
            current += part

    # 处理尾部没有标点的剩余文本
    if current.strip():
        sentences.append(current)

    return sentences


# ==========================================
# 按字数合并句子为 chunk
# ==========================================
def chunk_sentences(sentences: list, chunk_size: int = 100) -> list:
    """
    将小句子按字数累积合并为较大的 chunk。

    Args:
        sentences: 小句子列表 (list[str])
        chunk_size: 每个 chunk 的目标字数 (int)

    Returns:
        list[str]: 合并后的 chunk 列表

    Rules:
        - 累积小句直到总字数 >= chunk_size，合并为一个 chunk
        - 最后一个 chunk 如果字数不足，合并到前一个 chunk
        - 空列表返回空列表
    """
    if not sentences:
        return []

    chunks = []
    current_chunk = ""

    for sentence in sentences:
        current_chunk += sentence
        # 累积到目标字数，切一个 chunk
        if len(current_chunk) >= chunk_size:
            chunks.append(current_chunk)
            current_chunk = ""

    # 剩余不足 chunk_size 的部分，作为独立 chunk
    if current_chunk:
        chunks.append(current_chunk)

    return chunks
