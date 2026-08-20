"""Read and split Japanese scripts without changing their visible content."""

from pathlib import Path
import re
from typing import List


SOFT_BREAK_CHARS = "、，,：:；;」』）)]】"
PHRASE_BREAK_RE = re.compile(
    r"(?:から|まで|より|ので|のに|けれど|けど|なら|では|には|とは|ても|でも|"
    r"って|して|った|いて|れて|せて|ない|たい|です|ます)"
)


def read_script(path: str) -> str:
    """Read common Japanese text encodings and normalize line endings."""
    data = Path(path).read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp932", "shift_jis"):
        try:
            return data.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")
        except UnicodeDecodeError:
            continue
    raise ValueError("Không đọc được file script. Hãy dùng UTF-8 hoặc Shift-JIS.")


def clean_script(text: str) -> str:
    """Remove empty surrounding whitespace while retaining Japanese wording."""
    lines = [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(line for line in lines if line).strip()


def split_sentences(text: str) -> List[str]:
    """Split at Japanese/ASCII sentence endings and explicit line breaks."""
    cleaned = clean_script(text)
    if not cleaned:
        return []

    sentences: List[str] = []
    for line in cleaned.split("\n"):
        start = 0
        for match in re.finditer(r"[。！？!?]+", line):
            sentence = line[start : match.end()].strip()
            if sentence:
                sentences.append(sentence)
            start = match.end()
        tail = line[start:].strip()
        if tail:
            sentences.append(tail)
    return sentences


def _visible_length(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def _hard_split(text: str, max_chars: int) -> List[str]:
    """Split long text, preferring Japanese phrase boundaries."""
    pieces: List[str] = []
    remaining = text.strip()
    while _visible_length(remaining) > max_chars:
        visible = 0
        limit_index = len(remaining)
        for index, char in enumerate(remaining):
            if not char.isspace():
                visible += 1
            if visible >= max_chars:
                limit_index = index + 1
                break

        window = remaining[:limit_index]
        total_length = _visible_length(remaining)
        ideal = min(max_chars, max(4, total_length // 2)) if total_length <= max_chars * 2 else max_chars
        candidates = [
            index + 1 for index, char in enumerate(window) if char in SOFT_BREAK_CHARS
        ]
        for match in PHRASE_BREAK_RE.finditer(window):
            position = match.end()
            while position < len(remaining) and remaining[position] in SOFT_BREAK_CHARS:
                position += 1
            candidates.append(position)
        candidates = [
            position
            for position in candidates
            if position >= 4 and _visible_length(remaining[position:]) >= 4
        ]
        if candidates:
            break_at = min(candidates, key=lambda value: abs(value - ideal))
        elif total_length <= max_chars + 2:
            # Avoid leaving one character or punctuation in its own caption.
            break_at = max(4, len(remaining) // 2)
        else:
            break_at = limit_index
        pieces.append(remaining[:break_at].strip())
        remaining = remaining[break_at:].strip()
    if remaining:
        pieces.append(remaining)
    return pieces


def make_captions(text: str, max_chars: int = 24) -> List[str]:
    """Create semantic captions with a strict visible-character limit."""
    if max_chars < 4:
        raise ValueError("Số ký tự tối đa phải từ 4 trở lên.")
    captions: List[str] = []
    for sentence in split_sentences(text):
        captions.extend(_hard_split(sentence, max_chars))
    return captions
