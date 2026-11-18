"""Tests for line-timed LRC import (no transcription, no AI matching)."""
import pytest

from karaoke_gen.lyrics_transcriber.lyrics import lrc_import
from karaoke_gen.lyrics_transcriber.lyrics.lrc_import import (
    LrcImportError,
    build_correction_result,
    import_lrc_file,
    lrc_to_segments,
    parse_lrc,
    read_lrc_file,
)
from karaoke_gen.lyrics_transcriber.output.timing_validation import validate_segment_timing


class TestParseLrc:
    def test_basic_lines(self):
        parsed = parse_lrc("[00:05.00]Hello\n[00:09.50]World again\n")
        assert [(l.start, l.text) for l in parsed.lines] == [(5.0, "Hello"), (9.5, "World again")]

    @pytest.mark.parametrize(
        "stamp,expected",
        [("[01:02]", 62.0), ("[01:02.5]", 62.5), ("[01:02.50]", 62.5), ("[01:02.500]", 62.5), ("[01:02:25]", 62.25)],
    )
    def test_timestamp_formats(self, stamp, expected):
        assert parse_lrc(f"{stamp}Text").lines[0].start == pytest.approx(expected)

    def test_multiple_timestamps_repeat_the_line_in_time_order(self):
        parsed = parse_lrc("[00:30.00]Verse\n[00:10.00][01:00.00]Chorus\n")
        assert [(l.start, l.text) for l in parsed.lines] == [(10.0, "Chorus"), (30.0, "Verse"), (60.0, "Chorus")]

    def test_unsorted_input_is_sorted(self):
        parsed = parse_lrc("[00:20.00]B\n[00:10.00]A\n")
        assert [l.text for l in parsed.lines] == ["A", "B"]

    def test_header_tags_are_read_not_treated_as_lyrics(self):
        parsed = parse_lrc("[ar:Some Artist]\n[ti:Some Title]\n[00:01.00]Lyric\n")
        assert parsed.tags["ar"] == "Some Artist"
        assert parsed.tags["ti"] == "Some Title"
        assert [l.text for l in parsed.lines] == ["Lyric"]

    def test_positive_offset_makes_lyrics_earlier(self):
        parsed = parse_lrc("[offset:+500]\n[00:10.00]Lyric\n")
        assert parsed.lines[0].start == pytest.approx(9.5)

    def test_negative_offset_makes_lyrics_later_and_clamps_at_zero(self):
        assert parse_lrc("[offset:-500]\n[00:10.00]Lyric\n").lines[0].start == pytest.approx(10.5)
        assert parse_lrc("[offset:+5000]\n[00:01.00]Lyric\n").lines[0].start == 0.0

    def test_empty_timestamp_line_is_an_end_marker_not_a_lyric(self):
        parsed = parse_lrc("[00:10.00]Line one\n[00:13.00]\n[00:30.00]Line two\n")
        assert [l.text for l in parsed.lines] == ["Line one", "Line two"]
        assert parsed.lines[0].end_hint == 13.0
        assert parsed.lines[1].end_hint is None

    def test_enhanced_word_tags_are_stripped(self):
        parsed = parse_lrc("[00:10.00]<00:10.00>Hel<00:10.40>lo <00:11.00>there\n")
        assert parsed.lines[0].text == "Hello there"  # syllables split by tags are rejoined

    def test_whitespace_is_normalised(self):
        assert parse_lrc("[00:10.00]   spaced    out   \n").lines[0].text == "spaced out"

    def test_crlf_and_bom(self):
        parsed = parse_lrc("\ufeff[00:01.00]A\r\n[00:02.00]B\r\n")
        assert [l.text for l in parsed.lines] == ["A", "B"]

    def test_non_lrc_lines_are_reported_as_skipped(self):
        parsed = parse_lrc("[00:01.00]A\nstray text\n")
        assert parsed.skipped_lines == ["stray text"]

    def test_no_lyrics_raises(self):
        with pytest.raises(LrcImportError):
            parse_lrc("[ti:Only a header]\n")
        with pytest.raises(LrcImportError):
            parse_lrc("[00:01.00]\n")  # a bare marker is not a lyric
        with pytest.raises(LrcImportError):
            parse_lrc("")


class TestReadLrcFile:
    def test_reads_utf8_with_bom(self, tmp_path):
        f = tmp_path / "a.lrc"
        f.write_bytes("\ufeff[00:01.00]Café\n".encode("utf-8"))
        assert read_lrc_file(str(f)).lines[0].text == "Café"

    def test_falls_back_to_cp1252(self, tmp_path):
        f = tmp_path / "a.lrc"
        f.write_bytes("[00:01.00]Café\n".encode("cp1252"))
        assert read_lrc_file(str(f)).lines[0].text == "Café"

    def test_missing_file(self, tmp_path):
        with pytest.raises(LrcImportError):
            read_lrc_file(str(tmp_path / "nope.lrc"))


class TestSegments:
    def _segments(self, lrc, **kwargs):
        return lrc_to_segments(parse_lrc(lrc), **kwargs)

    def test_line_starts_come_from_the_lrc(self):
        segs = self._segments("[00:05.00]Hello world\n[00:10.00]Second line\n")
        assert segs[0].start_time == 5.0
        assert segs[1].start_time == 10.0
        assert [w.text for w in segs[0].words] == ["Hello", "world"]

    def test_words_are_contiguous_ordered_and_positive(self):
        segs = self._segments("[00:05.00]one two three four five\n[00:09.00]next\n")
        words = segs[0].words
        assert words[0].start_time == segs[0].start_time
        assert words[-1].end_time == segs[0].end_time
        for a, b in zip(words, words[1:]):
            assert b.start_time == pytest.approx(a.end_time)
        assert all(w.end_time > w.start_time for w in words)

    def test_longer_words_get_more_time(self):
        words = self._segments("[00:00.00]a extraordinary\n[00:10.00]x\n")[0].words
        assert (words[1].end_time - words[1].start_time) > (words[0].end_time - words[0].start_time)

    def test_line_ends_at_next_line_when_close(self):
        segs = self._segments("[00:05.00]Short line here\n[00:08.00]Next\n")
        assert segs[0].end_time == pytest.approx(8.0)

    def test_line_does_not_stretch_across_a_long_instrumental_gap(self):
        segs = self._segments("[00:05.00]Hi\n[01:30.00]Much later\n")
        assert segs[0].end_time < 10.0

    def test_explicit_end_marker_is_honoured(self):
        segs = self._segments("[00:05.00]Some words to sing here\n[00:07.00]\n[00:20.00]Next\n")
        assert segs[0].end_time == pytest.approx(7.0)

    def test_last_line_uses_estimate(self):
        seg = self._segments("[00:05.00]Final line of the song\n")[0]
        assert seg.end_time > seg.start_time

    def test_audio_duration_clamps_the_last_line(self):
        seg = self._segments("[00:05.00]Final line of the song\n", audio_duration=5.5)[0]
        assert seg.end_time <= 5.5 + 1e-9

    def test_lines_closer_than_min_still_valid(self):
        segs = self._segments("[00:05.00]A\n[00:05.05]B\n")
        for s in segs:
            assert all(w.end_time > w.start_time for w in s.words)

    def test_segments_pass_the_pipelines_own_timing_validation(self):
        segs = self._segments("[00:05.00]Hello world\n[00:09.00]Another line of lyrics\n[00:20.00]Last\n")
        validate_segment_timing(segs)  # raises LyricsTimingError if any word is untimed
        assert all(s.start_time == s.words[0].start_time and s.end_time == s.words[-1].end_time for s in segs)

    def test_ids_are_unique(self):
        segs = self._segments("[00:05.00]a b\n[00:09.00]c d\n")
        ids = [s.id for s in segs] + [w.id for s in segs for w in s.words]
        assert len(ids) == len(set(ids))


class TestCorrectionResult:
    def test_has_no_corrections_references_anchors_or_gaps(self):
        result = build_correction_result(self._segs(), artist="A", title="T")
        assert result.corrections == []
        assert result.corrections_made == 0
        assert result.reference_lyrics == {}
        assert result.anchor_sequences == []
        assert result.gap_sequences == []
        assert result.metadata["lyrics_source"] == "lrc_file"
        assert result.metadata["word_timing"] == "estimated"

    def test_original_segments_are_independent_copies(self):
        result = build_correction_result(self._segs())
        result.corrected_segments[0].words[0].text = "CHANGED"
        assert result.original_segments[0].words[0].text != "CHANGED"

    def test_round_trips_through_json(self):
        result = build_correction_result(self._segs(), artist="A", title="T")
        restored = lrc_import.CorrectionResult.from_dict(result.to_dict())
        assert [s.text for s in restored.corrected_segments] == [s.text for s in result.corrected_segments]
        assert restored.corrected_segments[0].words[0].start_time == result.corrected_segments[0].words[0].start_time

    def test_import_lrc_file_makes_no_network_or_model_calls(self, tmp_path, monkeypatch):
        import socket

        def no_network(*a, **k):
            raise AssertionError("network access attempted during LRC import")

        monkeypatch.setattr(socket, "create_connection", no_network)
        monkeypatch.setattr(socket.socket, "connect", no_network)
        f = tmp_path / "a.lrc"
        f.write_text("[00:01.00]Hello there\n[00:04.00]Bye now\n", encoding="utf-8")
        result = import_lrc_file(str(f), artist="A", title="T")
        assert len(result.corrected_segments) == 2

    @staticmethod
    def _segs():
        return lrc_to_segments(parse_lrc("[00:05.00]Hello world\n[00:09.00]Second line\n"))
