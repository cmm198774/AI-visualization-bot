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
