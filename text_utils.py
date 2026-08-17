"""
文本清洗工具：为 TTS 和显示提供不同格式的文本。
"""
import re


# ==========================================
# Emoji 正则（精确窄范围，不覆盖中文/英文/数字）
# ==========================================
_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"   # emoticons
    "\U0001F300-\U0001F5FF"   # symbols & pictographs
    "\U0001F680-\U0001F6FF"   # transport & map symbols
    "\U0001F1E0-\U0001F1FF"   # flags
    "\U0001F900-\U0001F9FF"   # supplemental symbols
    "\U0001FA00-\U0001FA6F"   # chess symbols
    "\U0001FA70-\U0001FAFF"   # symbols extended-A
    "\U00002702-\U000027B0"   # dingbats
    "\U000024C2-\U000024FF"   # enclosed alphanumerics（仅到 24FF，不覆盖中文）
    "\U00002600-\U000026FF"   # misc symbols
    "\U000025A0-\U000025FF"   # geometric shapes
    "\U000023F0-\U000023FA"   # misc technical
    "\U00002B50"              # star
    "\U00002B55"              # circle
    "\U00002764"              # heart
    "\U0000263A"              # smileys
    "\U00002B05-\U00002B07"   # arrows
    "\U00002934-\U00002935"   # curved arrows
    "\U00003030"              # wavy dash
    "\U0000203C\U00002049"    # exclamation marks
    "\U000020E3"              # combining enclosing keycap
    "\U0000FE0F"              # variation selector-16
    "\U0000200D"              # zero width joiner
    "\U000020E3"              # combining enclosing keycap
    "]+",
    flags=re.UNICODE,
)


# ==========================================
# TTS 文本清洗（去除 emoji、特殊符号）
# ==========================================
def clean_text_for_tts(text: str) -> str:
    """
    清洗文本，使其适合 TTS 朗读。
    去除 emoji、*、# 等不需要读出来的字符，合并多余空格。

    Args:
        text: 原始文本 (str)

    Returns:
        str: 清洗后的文本
    """
    # 去除 emoji
    text = _EMOJI_RE.sub("", text)

    # 去除 * 和 # 符号
    text = text.replace("*", "").replace("#", "")

    # 合并多余空格
    text = re.sub(r" {2,}", " ", text)

    return text.strip()
