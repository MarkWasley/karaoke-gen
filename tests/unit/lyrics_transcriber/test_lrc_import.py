import pytest

from karaoke_gen.lyrics_transcriber.lrc_import import (
    load_lrc_segments,
    parse_lrc_timestamp,
)


def test_parse_lrc_timestamp_supports_centiseconds_and_milliseconds():
    assert parse_lrc_timestamp("[01:02.34]") == pytest.approx(62.34)
    assert parse_lrc_timestamp("[01:02.345]") == pytest.approx(62.345)
    assert parse_lrc_timestamp("[01:02.3]") == pytest.approx(62.3)


def test_load_lrc_segments_preserves_line_times_without_word_estimates(tmp_path):
    lrc = tmp_path / "lyrics.lrc"
    lrc.write_text(
        "[ar:Test Artist]\n"
        "[ti:Test Song]\n"
        "[offset:0]\n"
        "[00:01.25]First lyric line\n"
        "[00:04.50]Second lyric line\n",
        encoding="utf-8",
    )

    segments = load_lrc_segments(str(lrc))

    assert [segment.text for segment in segments] == [
        "First lyric line",
        "Second lyric line",
    ]
    assert segments[0].start_time == pytest.approx(1.25)
    assert segments[0].source_timestamp == pytest.approx(1.25)
    assert segments[0].end_time == pytest.approx(4.5)
    assert segments[1].start_time == pytest.approx(4.5)
    assert segments[1].source_timestamp == pytest.approx(4.5)
    assert segments[1].end_time is None
    assert all(word.start_time is None and word.end_time is None
               for segment in segments for word in segment.words)


def test_load_lrc_segments_expands_multiple_timestamps(tmp_path):
    lrc = tmp_path / "lyrics.lrc"
    lrc.write_text("[00:01.00][00:03.00]Repeated line\n", encoding="utf-8")

    segments = load_lrc_segments(str(lrc))

    assert len(segments) == 2
    assert [segment.start_time for segment in segments] == [1.0, 3.0]
    assert [segment.text for segment in segments] == ["Repeated line", "Repeated line"]


def test_load_lrc_segments_rejects_files_without_timed_lyrics(tmp_path):
    lrc = tmp_path / "lyrics.lrc"
    lrc.write_text("[ar:Test Artist]\nJust plain lyrics\n", encoding="utf-8")

    with pytest.raises(ValueError, match="No timestamped lyric lines"):
        load_lrc_segments(str(lrc))
