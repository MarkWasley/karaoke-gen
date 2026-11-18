"""Import a user-supplied, line-timed LRC file as lyrics, with no transcription and no AI matching.

This is the "bring your own timing" alternative to the normal pipeline
(fetch reference lyrics -> transcribe -> anchor/gap matching -> correction).
The LRC file is treated as ground truth for *text* and for *line start times*.
Word-level timing is only an initial estimate, to be refined by a human in the
review UI.

What the parser understands
---------------------------
* ``[mm:ss.xx] text`` with 1-3 fractional digits, or no fraction (``[mm:ss]``).
* Several timestamps in front of one line (``[00:12.00][01:30.50]Chorus``) - the
  line is repeated at each time.
* Header tags (``[ar:]``, ``[ti:]``, ``[offset:]`` ...). ``[offset:+500]`` is
  applied per the common LRC convention: a positive value makes lyrics appear
  *earlier*.
* Timestamped lines with no text (``[01:23.45]``). These are the usual LRC way of
  saying "the previous line stops here", and are used as that line's end time.
* Enhanced-LRC inline word tags (``<00:12.30>``) are stripped. This importer is
  line-timed by design, so any word timing in the file is deliberately ignored.

Word timing estimate
--------------------
Each line's words are spread across the line's duration in proportion to their
length. A line ends at the first of: an explicit end marker, the next line's
start, or a length-based cap (so a long instrumental break after a short line
doesn't stretch its words across the whole gap).
"""

from __future__ import annotations

import copy
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from karaoke_gen.lyrics_transcriber.types import CorrectionResult, LyricsSegment, Word
from karaoke_gen.lyrics_transcriber.utils.word_utils import WordUtils

# [mm:ss], [mm:ss.x], [mm:ss.xx], [mm:ss.xxx] (also tolerates ':' before the fraction)
_TIMESTAMP_RE = re.compile(r"\s*\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
# Header / ID tags: [ar:Artist], [offset:+250] ... (key must start with a letter)
_TAG_RE = re.compile(r"^\s*\[([A-Za-z][A-Za-z0-9_#]*):(.*)\]\s*$")
# Enhanced-LRC inline word timestamps: <mm:ss.xx>
_ENHANCED_WORD_RE = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")

# Estimated singing time for a line: BASE + chars * PER_CHAR. A line never stretches past
# STRETCH * estimate + SLACK, even if the next line is much later.
SECONDS_PER_CHAR = 0.12
BASE_SECONDS = 0.5
STRETCH = 1.5
SLACK_SECONDS = 1.0
# Never produce a line or word shorter than this.
MIN_LINE_SECONDS = 0.3
MIN_WORD_SECONDS = 0.05
# Warn when two consecutive lines start closer together than this.
TIGHT_LINE_WARNING_SECONDS = 0.3


class LrcImportError(ValueError):
    """The LRC file could not be turned into usable lyrics."""


@dataclass
class LrcLine:
    """One lyric line: its start time and text, plus an explicit end time if the file gave one."""

    start: float
    text: str
    end_hint: Optional[float] = None


@dataclass
class ParsedLrc:
    lines: List[LrcLine]
    tags: Dict[str, str] = field(default_factory=dict)
    offset_seconds: float = 0.0
    skipped_lines: List[str] = field(default_factory=list)


def _timestamp_to_seconds(minutes: str, seconds: str, fraction: Optional[str]) -> float:
    value = int(minutes) * 60 + int(seconds)
    if fraction:
        value += int(fraction) / (10 ** len(fraction))
    return float(value)


def parse_lrc(content: str) -> ParsedLrc:
    """Parse LRC text into time-ordered lyric lines.

    Raises:
        LrcImportError: if the content contains no timestamped lyric text at all.
    """
    tags: Dict[str, str] = {}
    skipped: List[str] = []
    # (time, text) - text == "" marks an end-of-line marker rather than a lyric.
    entries: List[tuple] = []

    for raw_line in content.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.strip().lstrip("\ufeff")
        if not line:
            continue

        stamps: List[float] = []
        pos = 0
        while True:
            match = _TIMESTAMP_RE.match(line, pos)
            if not match:
                break
            stamps.append(_timestamp_to_seconds(*match.groups()))
            pos = match.end()

        if not stamps:
            tag = _TAG_RE.match(line)
            if tag:
                tags[tag.group(1).strip().lower()] = tag.group(2).strip()
            else:
                skipped.append(line)
            continue

        text = _ENHANCED_WORD_RE.sub("", line[pos:])
        text = " ".join(text.split())
        for stamp in stamps:
            entries.append((stamp, text))

    offset_seconds = 0.0
    if "offset" in tags:
        try:
            # LRC convention: positive offset => lyrics appear sooner.
            offset_seconds = int(tags["offset"].strip().lstrip("+")) / 1000.0
        except ValueError:
            skipped.append(f"[offset:{tags['offset']}]")

    # Stable sort keeps file order for identical timestamps.
    entries.sort(key=lambda e: e[0])

    lines: List[LrcLine] = []
    for index, (stamp, text) in enumerate(entries):
        if not text:
            continue
        start = max(0.0, stamp - offset_seconds)
        end_hint: Optional[float] = None
        if index + 1 < len(entries) and not entries[index + 1][1]:
            end_hint = max(0.0, entries[index + 1][0] - offset_seconds)
        lines.append(LrcLine(start=start, text=text, end_hint=end_hint))

    if not lines:
        raise LrcImportError("No timestamped lyric lines were found. Expected lines like '[00:12.34] Some lyrics'.")

    return ParsedLrc(lines=lines, tags=tags, offset_seconds=offset_seconds, skipped_lines=skipped)


def read_lrc_file(path: str) -> ParsedLrc:
    """Read and parse an LRC file, tolerating the common legacy encodings."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise LrcImportError(f"Could not read LRC file {path}: {e}") from e

    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return parse_lrc(raw.decode(encoding))
        except UnicodeDecodeError:
            continue
    raise LrcImportError(f"Could not decode LRC file {path}")  # pragma: no cover - latin-1 never fails


def estimate_line_duration(text: str) -> float:
    """Rough time it takes to sing ``text``. Only used as an upper bound / fallback."""
    return BASE_SECONDS + len(text) * SECONDS_PER_CHAR


def _line_end(line: LrcLine, next_start: Optional[float], audio_duration: Optional[float]) -> float:
    estimate = estimate_line_duration(line.text)
    cap = line.start + estimate * STRETCH + SLACK_SECONDS

    candidates = [cap]
    if line.end_hint is not None:
        candidates.append(line.end_hint)
    if next_start is not None:
        candidates.append(next_start)
    end = min(candidates)

    if next_start is None and line.end_hint is None:
        # Final line with nothing to bound it: use the plain estimate rather than the generous cap.
        end = line.start + estimate

    if audio_duration is not None:
        end = min(end, audio_duration)

    return max(end, line.start + MIN_LINE_SECONDS)


def _spread_words(text: str, start: float, end: float) -> List[Word]:
    """Distribute the words of ``text`` across [start, end], weighted by word length."""
    word_texts = text.split()
    weights = [max(1, len(w)) for w in word_texts]
    total = float(sum(weights))
    duration = max(end - start, MIN_WORD_SECONDS * len(word_texts))

    words: List[Word] = []
    cursor = start
    for index, (word_text, weight) in enumerate(zip(word_texts, weights)):
        word_end = start + duration if index == len(word_texts) - 1 else cursor + duration * (weight / total)
        words.append(
            Word(
                id=WordUtils.generate_id(),
                text=word_text,
                start_time=round(cursor, 3),
                end_time=round(word_end, 3),
                confidence=1.0,  # Text comes straight from the user's file
                created_during_correction=False,
            )
        )
        cursor = word_end
    return words


def lrc_to_segments(
    parsed: ParsedLrc,
    audio_duration: Optional[float] = None,
    logger: Optional[logging.Logger] = None,
) -> List[LyricsSegment]:
    """Turn parsed LRC lines into segments with *estimated* word timings."""
    logger = logger or logging.getLogger(__name__)
    segments: List[LyricsSegment] = []
    lines = parsed.lines

    for index, line in enumerate(lines):
        next_start = lines[index + 1].start if index + 1 < len(lines) else None
        if next_start is not None and next_start - line.start < TIGHT_LINE_WARNING_SECONDS:
            logger.warning(
                f"LRC lines start {next_start - line.start:.2f}s apart (at {line.start:.2f}s): "
                f"{line.text!r} / {lines[index + 1].text!r}. Fix their timing in review."
            )
        if audio_duration is not None and line.start >= audio_duration:
            logger.warning(f"LRC line at {line.start:.2f}s is past the end of the audio ({audio_duration:.2f}s): {line.text!r}")

        end = _line_end(line, next_start, audio_duration)
        words = _spread_words(line.text, line.start, end)
        segments.append(
            LyricsSegment(
                id=WordUtils.generate_id(),
                text=line.text,
                words=words,
                start_time=words[0].start_time,
                end_time=words[-1].end_time,
            )
        )
    return segments


def build_correction_result(
    segments: List[LyricsSegment],
    artist: Optional[str] = None,
    title: Optional[str] = None,
    audio_filepath: Optional[str] = None,
    source_path: Optional[str] = None,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> CorrectionResult:
    """Wrap segments in a CorrectionResult that carries no corrections, references, anchors or gaps.

    This is the same shape the pipeline produces when auto-correction is disabled, so the review UI,
    output generators and post-review rendering handle it unchanged.
    """
    total_words = sum(len(s.words) for s in segments)
    metadata: Dict[str, Any] = {
        "correction_type": "none",
        "reason": "lrc_import",
        "lyrics_source": "lrc_file",
        "word_timing": "estimated",
        "artist": artist,
        "title": title,
        "audio_filepath": audio_filepath,
        "source_lrc": source_path,
        "anchor_sequences_count": 0,
        "gap_sequences_count": 0,
        "total_words": total_words,
        "correction_ratio": 0.0,
        "available_handlers": [],
        "enabled_handlers": [],
        "agentic_routing": "disabled",
    }
    if extra_metadata:
        metadata.update(extra_metadata)

    return CorrectionResult(
        original_segments=copy.deepcopy(segments),
        corrected_segments=segments,
        corrections=[],
        corrections_made=0,
        confidence=1.0,
        reference_lyrics={},
        anchor_sequences=[],
        gap_sequences=[],
        resized_segments=[],
        metadata=metadata,
        correction_steps=[],
        word_id_map={},
        segment_id_map={},
    )


def import_lrc_file(
    path: str,
    artist: Optional[str] = None,
    title: Optional[str] = None,
    audio_filepath: Optional[str] = None,
    audio_duration: Optional[float] = None,
    logger: Optional[logging.Logger] = None,
) -> CorrectionResult:
    """Read an LRC file and return a review-ready CorrectionResult. Makes no network or model calls."""
    logger = logger or logging.getLogger(__name__)
    parsed = read_lrc_file(path)

    if parsed.skipped_lines:
        preview = "; ".join(repr(s) for s in parsed.skipped_lines[:3])
        logger.warning(f"Ignored {len(parsed.skipped_lines)} non-lyric line(s) in {path}: {preview}")
    if parsed.offset_seconds:
        logger.info(f"Applied LRC [offset] of {parsed.offset_seconds * 1000:+.0f}ms (positive = earlier)")

    segments = lrc_to_segments(parsed, audio_duration=audio_duration, logger=logger)
    logger.info(f"Imported {len(segments)} lines / {sum(len(s.words) for s in segments)} words from {path}; word timings are estimated")
    return build_correction_result(segments, artist=artist, title=title, audio_filepath=audio_filepath, source_path=path)
