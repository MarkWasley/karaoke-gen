"""Import line-timed LRC lyrics without attempting word alignment."""

import re
import uuid
from typing import List, Tuple

from karaoke_gen.lyrics_transcriber.types import LyricsSegment, Word


_TIMESTAMP = re.compile(r"\[(\d{1,3}):(\d{2})(?:\.(\d{1,3}))?\]")


def parse_lrc_timestamp(value: str) -> float:
    """Convert an LRC timestamp (MM:SS.xx) to seconds."""
    match = _TIMESTAMP.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid LRC timestamp: {value}")
    minutes, seconds, fraction = match.groups()
    fractional_seconds = float(f"0.{fraction}") if fraction else 0.0
    return int(minutes) * 60 + int(seconds) + fractional_seconds


def load_lrc_segments(path: str) -> List[LyricsSegment]:
    """Read timed lyric lines. Word timings intentionally remain unset for Human Review."""
    with open(path, "r", encoding="utf-8-sig") as source:
        content = source.read()

    entries: List[Tuple[float, str]] = []
    for line_number, raw_line in enumerate(content.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("[") and re.match(r"\[[a-zA-Z]+:", line):
            continue
        timestamps = list(_TIMESTAMP.finditer(line))
        if not timestamps:
            continue
        lyric_text = _TIMESTAMP.sub("", line).strip()
        if not lyric_text:
            continue
        for match in timestamps:
            stamp = parse_lrc_timestamp(match.group(0))
            entries.append((stamp, lyric_text))

    if not entries:
        raise ValueError(f"No timestamped lyric lines found in LRC file: {path}")

    entries.sort(key=lambda item: item[0])
    segments: List[LyricsSegment] = []
    for index, (timestamp, text) in enumerate(entries):
        words = [
            Word(
                id=str(uuid.uuid4()),
                text=word,
                start_time=None,
                end_time=None,
            )
            for word in text.split()
        ]
        next_timestamp = entries[index + 1][0] if index + 1 < len(entries) else None
        segments.append(
            LyricsSegment(
                id=str(uuid.uuid4()),
                text=text,
                words=words,
                start_time=timestamp,
                end_time=next_timestamp,
                source_timestamp=timestamp,
            )
        )
    return segments
