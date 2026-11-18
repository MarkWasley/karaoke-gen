"""Tests for LRC import mode (--lrc_file): line-timed LRC in, no transcription / AI matching, human word timing.

Covers LyricsProcessor.import_lrc_lyrics, KaraokePrep argument validation, CLI argument validation and the
gen_cli review/finalise branching.
"""
import argparse
import json
import logging
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from karaoke_gen.config import DEFAULT_STYLE_PARAMS
from karaoke_gen.karaoke_gen import KaraokePrep
from karaoke_gen.lyrics_processor import LyricsProcessor
from karaoke_gen.lyrics_transcriber.lyrics.lrc_import import LrcImportError
from karaoke_gen.lyrics_transcriber.types import CorrectionResult
from karaoke_gen.utils import gen_cli
from karaoke_gen.utils.cli_args import create_parser
from tests.unit.test_gen_cli import MOCK_FINAL_TRACK

LRC = "[00:05.00]Hello darkness my old friend\n[00:09.50]I've come to talk with you again\n[00:13.00]\n[00:20.00]Because a vision\n"


@pytest.fixture
def style_json(tmp_path):
    path = tmp_path / "style.json"
    path.write_text(json.dumps(DEFAULT_STYLE_PARAMS))
    return str(path)


@pytest.fixture
def lrc_path(tmp_path):
    path = tmp_path / "input.lrc"
    path.write_text(LRC, encoding="utf-8")
    return str(path)


@pytest.fixture
def processor(style_json):
    return LyricsProcessor(
        logger=logging.getLogger("test"),
        style_params_json=style_json,
        lyrics_file=None,
        skip_transcription=False,
        skip_transcription_review=True,
        render_video=False,
        subtitle_offset_ms=0,
    )


class TestImportLrcLyrics:
    def test_writes_pipeline_outputs_and_returns_transcribe_compatible_dict(self, processor, lrc_path, tmp_path):
        out = tmp_path / "track"
        out.mkdir()
        result = processor.import_lrc_lyrics("/nonexistent/audio.wav", "Test Artist", "Demo", str(out), lrc_path)

        # Same keys KaraokePrep reads from transcribe_lyrics()
        assert result["corrected_lyrics_text"].splitlines()[0] == "Hello darkness my old friend"
        assert os.path.isfile(result["corrected_lyrics_text_filepath"])
        assert result["countdown_padding_added"] is False
        assert result["countdown_padding_seconds"] == 0.0
        assert result["padded_audio_filepath"] is None
        assert os.path.isfile(result["lrc_filepath"])
        assert result["lrc_filepath"] == str(out / "Test Artist - Demo (Karaoke).lrc")

        corrections = out / "lyrics" / "Test Artist - Demo (Lyrics Corrections).json"
        data = CorrectionResult.from_dict(json.loads(corrections.read_text()))
        assert [s.text for s in data.corrected_segments][0] == "Hello darkness my old friend"
        assert data.reference_lyrics == {} and data.anchor_sequences == [] and data.gap_sequences == []
        assert data.corrections == []
        assert data.corrected_segments[0].start_time == 5.0

    def test_does_not_construct_transcriber_or_fetch_lyrics(self, processor, lrc_path, tmp_path):
        out = tmp_path / "track"
        out.mkdir()
        with patch("karaoke_gen.lyrics_processor.LyricsTranscriber", side_effect=AssertionError("LyricsTranscriber used")):
            processor.import_lrc_lyrics("/x.wav", "A", "T", str(out), lrc_path)

    def test_input_lrc_is_never_modified_or_overwritten(self, processor, lrc_path, tmp_path):
        out = tmp_path / "track"
        out.mkdir()
        before = open(lrc_path, "rb").read()
        processor.import_lrc_lyrics("/x.wav", "A", "T", str(out), lrc_path)
        assert open(lrc_path, "rb").read() == before
        assert (out / "lyrics" / "A - T (Source LRC).lrc").read_bytes() == before

    def test_rerun_keeps_existing_corrections_so_human_timing_is_not_lost(self, processor, lrc_path, tmp_path):
        out = tmp_path / "track"
        out.mkdir()
        processor.import_lrc_lyrics("/x.wav", "A", "T", str(out), lrc_path)

        corrections = out / "lyrics" / "A - T (Lyrics Corrections).json"
        edited = json.loads(corrections.read_text())
        edited["corrected_segments"][0]["words"][0]["start_time"] = 5.25  # a human nudged this word
        corrections.write_text(json.dumps(edited))

        processor.import_lrc_lyrics("/x.wav", "A", "T", str(out), lrc_path)
        kept = CorrectionResult.from_dict(json.loads(corrections.read_text()))
        assert kept.corrected_segments[0].words[0].start_time == 5.25

    def test_missing_lrc_raises(self, processor, tmp_path):
        with pytest.raises(LrcImportError):
            processor.import_lrc_lyrics("/x.wav", "A", "T", str(tmp_path), str(tmp_path / "missing.lrc"))

    def test_lrc_without_lyrics_raises(self, processor, tmp_path):
        bad = tmp_path / "bad.lrc"
        bad.write_text("[ti:nothing here]\n")
        with pytest.raises(LrcImportError):
            processor.import_lrc_lyrics("/x.wav", "A", "T", str(tmp_path), str(bad))


class TestKaraokePrepArgs:
    def test_lrc_requires_existing_instrumental(self, lrc_path):
        with pytest.raises(ValueError, match="existing_instrumental"):
            KaraokePrep(logger=MagicMock(), lrc_file=lrc_path)

    def test_lrc_missing_file(self, tmp_path):
        inst = tmp_path / "i.flac"
        inst.touch()
        with pytest.raises(FileNotFoundError):
            KaraokePrep(logger=MagicMock(), lrc_file=str(tmp_path / "no.lrc"), existing_instrumental=str(inst))

    def test_lrc_conflicts(self, lrc_path, tmp_path):
        inst = tmp_path / "i.flac"
        inst.touch()
        with pytest.raises(ValueError):
            KaraokePrep(logger=MagicMock(), lrc_file=lrc_path, existing_instrumental=str(inst), skip_lyrics=True)
        with pytest.raises(ValueError):
            KaraokePrep(logger=MagicMock(), lrc_file=lrc_path, existing_instrumental=str(inst), lyrics_file="x.txt")

    def test_vocals_requires_instrumental_and_existing_file(self, tmp_path):
        v = tmp_path / "v.flac"
        v.touch()
        with pytest.raises(ValueError, match="existing_instrumental"):
            KaraokePrep(logger=MagicMock(), existing_vocals=str(v))
        inst = tmp_path / "i.flac"
        inst.touch()
        with pytest.raises(FileNotFoundError):
            KaraokePrep(logger=MagicMock(), existing_instrumental=str(inst), existing_vocals=str(tmp_path / "nope.flac"))

    def test_valid_combination_is_accepted_and_stored(self, lrc_path, tmp_path):
        inst, voc = tmp_path / "i.flac", tmp_path / "v.flac"
        inst.touch()
        voc.touch()
        kp = KaraokePrep(logger=MagicMock(), lrc_file=lrc_path, existing_instrumental=str(inst), existing_vocals=str(voc))
        assert kp.lrc_file == lrc_path and kp.existing_vocals == str(voc)

    def test_default_is_unchanged(self):
        kp = KaraokePrep(logger=MagicMock())
        assert kp.lrc_file is None and kp.existing_vocals is None


class TestCliArgs:
    def test_flags_are_registered(self):
        args = create_parser(prog="karaoke-gen").parse_args(["--lrc_file", "a.lrc", "--existing_vocals", "v.flac", "--existing_instrumental", "i.flac", "x.flac", "A", "T"])
        assert args.lrc_file == "a.lrc" and args.existing_vocals == "v.flac"

    def test_validator_ok_when_not_in_lrc_mode(self):
        assert gen_cli.validate_lrc_mode_args(argparse.Namespace()) == []
        assert gen_cli.validate_lrc_mode_args(argparse.Namespace(lrc_file=None)) == []

    def test_validator_ignores_mock_attributes(self):
        # Existing tests pass MagicMock-ish args; a Mock attribute must not look like "--lrc_file given"
        assert gen_cli.validate_lrc_mode_args(MagicMock()) == []

    def test_validator_requires_instrumental(self, lrc_path):
        problems = gen_cli.validate_lrc_mode_args(argparse.Namespace(lrc_file=lrc_path, existing_instrumental=None))
        assert any("--existing_instrumental" in p for p in problems)

    def test_validator_reports_missing_files(self, tmp_path):
        problems = gen_cli.validate_lrc_mode_args(
            argparse.Namespace(lrc_file=str(tmp_path / "a.lrc"), existing_instrumental=str(tmp_path / "i.flac"), existing_vocals=str(tmp_path / "v.flac"))
        )
        assert len(problems) == 3

    @pytest.mark.parametrize(
        "extra,flag",
        [
            ({"lyrics_file": "x.txt"}, "--lyrics_file"),
            ({"skip_lyrics": True}, "--skip-lyrics"),
            ({"skip_separation": True}, "--skip-separation"),
            ({"lyrics_only": True}, "--lyrics-only"),
            ({"edit_lyrics": True}, "--edit-lyrics"),
        ],
    )
    def test_validator_rejects_conflicting_flags(self, lrc_path, tmp_path, extra, flag):
        inst = tmp_path / "i.flac"
        inst.touch()
        problems = gen_cli.validate_lrc_mode_args(argparse.Namespace(lrc_file=lrc_path, existing_instrumental=str(inst), **extra))
        assert any(flag in p for p in problems)

    def test_validator_accepts_good_args(self, lrc_path, tmp_path):
        inst, voc = tmp_path / "i.flac", tmp_path / "v.flac"
        inst.touch()
        voc.touch()
        args = argparse.Namespace(
            lrc_file=lrc_path, existing_instrumental=str(inst), existing_vocals=str(voc),
            lyrics_file=None, skip_lyrics=False, skip_separation=False, lyrics_only=False, edit_lyrics=False,
        )
        assert gen_cli.validate_lrc_mode_args(args) == []


# --- gen_cli flow ---------------------------------------------------------------------------------------

pytestmark_async = pytest.mark.asyncio


def _args(tmp_path, **overrides):
    """Namespace mirroring tests/unit/test_gen_cli.py's mock_base_args, plus LRC-mode flags."""
    base = dict(
        args=["Artist", "Title"], prep_only=False, finalise_only=False, edit_lyrics=False, test_email_template=False,
        skip_transcription=False, skip_separation=False, skip_lyrics=False, lyrics_only=False, log_level="info",
        dry_run=False, render_bounding_boxes=False, filename_pattern=None, output_dir=".", no_track_subfolders=True,
        lossless_output_format="FLAC", output_png=True, output_jpg=True,
        clean_instrumental_model="m", backing_vocals_models=["b"], other_stems_models=["o"],
        model_file_dir="/tmp/m", existing_instrumental=None, instrumental_format="flac", lyrics_artist=None,
        lyrics_title=None, lyrics_file=None, subtitle_offset_ms=0, skip_transcription_review=False,
        style_params_json=None, style_override=None, background_video=None, background_video_darkness=0,
        list_themes=False, validate_theme=False, theme=None, auto_download=False, enable_cdg=False, enable_txt=False,
        brand_prefix=None, organised_dir=None, organised_dir_rclone_root=None, public_share_dir=None,
        youtube_client_secrets_file=None, youtube_description_file=None, rclone_destination=None,
        discord_webhook_url=None, email_template_file=None, keep_brand_code=False, no_video=False, yes=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


@pytest.fixture
def lrc_run(tmp_path, monkeypatch, lrc_path):
    """A prepared track dir + args for an LRC-mode run. chdir is real, so nothing leaks into the repo checkout."""
    track_dir = tmp_path / "track"
    track_dir.mkdir()
    instrumental = track_dir / "A - T (Instrumental Custom).flac"
    instrumental.touch()
    audio = track_dir / "A - T.wav"
    audio.touch()
    monkeypatch.chdir(track_dir)

    track = {
        "artist": "A", "title": "T", "input_media": "in.wav", "input_audio_wav": str(audio),
        "track_output_dir": str(track_dir),
        "separated_audio": {"Custom": {"instrumental": str(instrumental), "vocals": None}},
    }
    args = _args(tmp_path, lrc_file=lrc_path, existing_instrumental=str(instrumental), no_video=True)
    return SimpleNamespace(track=track, args=args, track_dir=track_dir, instrumental=instrumental)


async def _run_async_main(args, track, **extra_patches):
    kprep = MagicMock()
    kprep.process = AsyncMock(return_value=[track])
    with patch("karaoke_gen.utils.gen_cli.is_url", return_value=False), \
         patch("karaoke_gen.utils.gen_cli.is_file", return_value=False), \
         patch("karaoke_gen.utils.gen_cli.KaraokePrep", return_value=kprep) as kprep_cls, \
         patch("karaoke_gen.utils.gen_cli.argparse.ArgumentParser") as parser, \
         patch("karaoke_gen.utils.gen_cli.pyperclip", MagicMock()), \
         patch("karaoke_gen.utils.gen_cli.KaraokeFinalise") as finalise, \
         patch("karaoke_gen.utils.gen_cli.run_combined_review", **extra_patches.pop("review_kwargs", {"return_value": (None, None, False)})) as review:
        parser.return_value.parse_args.return_value = args
        finalise.return_value.process.return_value = MOCK_FINAL_TRACK
        await gen_cli.async_main()
    return SimpleNamespace(kprep_cls=kprep_cls, review=review, finalise=finalise)


@pytest.mark.asyncio
async def test_lrc_mode_passes_new_args_to_kprep(lrc_run):
    lrc_run.args.existing_vocals = None
    mocks = await _run_async_main(lrc_run.args, lrc_run.track, review_kwargs={"return_value": (None, MagicMock(), False)})
    kwargs = mocks.kprep_cls.call_args.kwargs
    assert kwargs["lrc_file"] == lrc_run.args.lrc_file
    assert kwargs["existing_instrumental"] == str(lrc_run.instrumental)
    assert kwargs["skip_transcription_review"] is True  # review still deferred to the interactive flow


@pytest.mark.asyncio
async def test_lrc_mode_runs_lyrics_only_review_and_uses_supplied_instrumental(lrc_run):
    reviewed = MagicMock()
    mocks = await _run_async_main(lrc_run.args, lrc_run.track, review_kwargs={"return_value": (None, reviewed, False)})

    mocks.review.assert_called_once()
    assert mocks.review.call_args.kwargs["lyrics_only"] is True
    assert mocks.finalise.call_args.kwargs["selected_instrumental_file"] == str(lrc_run.instrumental)


@pytest.mark.asyncio
async def test_lrc_mode_aborts_if_review_did_not_complete(lrc_run):
    with pytest.raises(SystemExit):
        await _run_async_main(lrc_run.args, lrc_run.track, review_kwargs={"return_value": (None, None, False)})


@pytest.mark.asyncio
async def test_lrc_mode_skip_transcription_review_runs_no_review(lrc_run):
    lrc_run.args.skip_transcription_review = True
    mocks = await _run_async_main(lrc_run.args, lrc_run.track)
    mocks.review.assert_not_called()
    assert mocks.finalise.call_args.kwargs["selected_instrumental_file"] == str(lrc_run.instrumental)
    # Prep renders the video itself when review is off
    assert mocks.kprep_cls.call_args.kwargs["render_video"] is (not lrc_run.args.no_video)


@pytest.mark.asyncio
async def test_lrc_mode_skip_instrumental_review_flag_does_not_disable_lyrics_review(lrc_run):
    # There is no instrumental review in LRC mode, so this flag must not switch off the word-timing review
    lrc_run.args.skip_instrumental_review = True
    mocks = await _run_async_main(lrc_run.args, lrc_run.track, review_kwargs={"return_value": (None, MagicMock(), False)})
    mocks.review.assert_called_once()


@pytest.mark.asyncio
async def test_lrc_mode_invalid_args_exit_before_any_work(lrc_run):
    lrc_run.args.existing_instrumental = None
    with pytest.raises(SystemExit):
        await _run_async_main(lrc_run.args, lrc_run.track)


@pytest.mark.asyncio
async def test_lrc_mode_regenerates_lrc_from_reviewed_timings(lrc_run, tmp_path):
    """After review, the root (Karaoke).lrc (read by CDG/TXT generation) must carry the reviewed timings."""
    lrc_run.args.no_video = False
    reviewed = MagicMock()
    reviewed.to_dict.return_value = {"reviewed": True}

    new_lrc = tmp_path / "regenerated.lrc"
    new_lrc.write_text("[re:MidiCo]\nREVIEWED")
    new_video = tmp_path / "video.mkv"
    new_video.write_text("v")
    outputs = SimpleNamespace(video=str(new_video), lrc=str(new_lrc), ass=None)

    with patch("karaoke_gen.utils.gen_cli.CountdownProcessor") as countdown, \
         patch("karaoke_gen.utils.gen_cli.OutputGenerator") as generator, \
         patch("karaoke_gen.utils.gen_cli.OutputConfig") as output_config:
        countdown.return_value.process.return_value = (reviewed, str(lrc_run.track["input_audio_wav"]), False, 0)
        generator.return_value.generate_outputs.return_value = outputs
        await _run_async_main(lrc_run.args, lrc_run.track, review_kwargs={"return_value": (None, reviewed, False)})

    assert output_config.call_args.kwargs["generate_lrc"] is True
    assert (lrc_run.track_dir / "A - T (Karaoke).lrc").read_text().endswith("REVIEWED")
    assert (lrc_run.track_dir / "A - T (With Vocals).mkv").exists()


@pytest.mark.asyncio
async def test_non_lrc_flow_does_not_regenerate_lrc(tmp_path, monkeypatch):
    """Guard: normal (non-LRC) runs keep generate_lrc=False after review, exactly as before."""
    track_dir = tmp_path / "t"
    track_dir.mkdir()
    (track_dir / "A - T (Instrumental).flac").touch()
    (track_dir / "A - T.wav").touch()
    monkeypatch.chdir(track_dir)
    track = {
        "artist": "A", "title": "T", "input_media": "x", "input_audio_wav": str(track_dir / "A - T.wav"),
        "track_output_dir": str(track_dir),
        "separated_audio": {"clean_instrumental": {"instrumental": str(track_dir / "A - T (Instrumental).flac")}},
    }
    reviewed = MagicMock()
    reviewed.to_dict.return_value = {}
    outputs = SimpleNamespace(video=None, lrc=None, ass=None)
    with patch("karaoke_gen.utils.gen_cli.CountdownProcessor") as countdown, \
         patch("karaoke_gen.utils.gen_cli.OutputGenerator") as generator, \
         patch("karaoke_gen.utils.gen_cli.OutputConfig") as output_config:
        countdown.return_value.process.return_value = (reviewed, "x.wav", False, 0)
        generator.return_value.generate_outputs.return_value = outputs
        await _run_async_main(_args(tmp_path), track, review_kwargs={"return_value": ("clean", reviewed, False)})
    assert output_config.call_args.kwargs["generate_lrc"] is False
