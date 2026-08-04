import re

_SINGLE_TILDE_RANGE = re.compile(r"(?<!~)(?<=\S)~(?=\S)(?!~)")


def normalize_markdown_ranges(content: str) -> str:
    """Use an unambiguous range separator for chat clients that parse ``~x~`` as strikeout."""
    return _SINGLE_TILDE_RANGE.sub("–", content)
