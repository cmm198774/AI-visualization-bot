"""
中文分句工具测试
"""
from sentence_splitter import split_sentences


def test_basic_split():
    """基本分句：按中文标点分隔"""
    result = split_sentences("你好呀老板～今天天气不错呢！")
    assert result == ["你好呀老板～", "今天天气不错呢！"]


def test_multiple_punctuation():
    """多个句子"""
    result = split_sentences("一句。两句。三句。")
    assert result == ["一句。", "两句。", "三句。"]


def test_no_punctuation():
    """没有标点 → 整体作为一句"""
    result = split_sentences("没有标点的文本")
    assert result == ["没有标点的文本"]


def test_empty_string():
    """空字符串 → 空列表"""
    result = split_sentences("")
    assert result == []


def test_only_punctuation():
    """只有标点 → 作为一句"""
    result = split_sentences("。。。")
    assert result == ["。。。"]


def test_mixed_content():
    """中英文混合"""
    result = split_sentences("混合,英文hello。中文！")
    assert result == ["混合,英文hello。", "中文！"]


def test_trailing_no_punctuation():
    """尾部无标点也成句"""
    result = split_sentences("第一句。第二句没标点")
    assert result == ["第一句。", "第二句没标点"]


def test_whitespace_only():
    """纯空白 → 空列表"""
    result = split_sentences("   ")
    assert result == []


def test_all_separators():
    """所有分隔符都生效"""
    result = split_sentences("a。b！c？d～e；f…g，h、i")
    assert result == ["a。", "b！", "c？", "d～", "e；", "f…", "g，", "h、", "i"]
