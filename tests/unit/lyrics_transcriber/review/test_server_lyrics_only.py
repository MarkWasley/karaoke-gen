"""ReviewServer(lyrics_only=True): the review finishes when lyrics are submitted.

Used by LRC import mode, where the instrumental is already chosen. The frontend always redirects from lyrics review
to an instrumental review page after saving, and that page needs backing-vocals analysis that doesn't exist here, so
the server must (a) complete the review on lyrics submission and (b) answer that redirect with a harmless page.
"""
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from karaoke_gen.lyrics_transcriber.core.config import OutputConfig
from karaoke_gen.lyrics_transcriber.lyrics.lrc_import import build_correction_result, lrc_to_segments, parse_lrc
from karaoke_gen.lyrics_transcriber.review.server import ReviewServer


@pytest.fixture
def fake_frontend(tmp_path, monkeypatch) -> Path:
    root = tmp_path / "out"
    root.mkdir()
    (root / "index.html").write_text("<html>root</html>")
    (root / "_next" / "static" / "chunks").mkdir(parents=True)
    (root / "en" / "app").mkdir(parents=True)  # locales are discovered from the static export's subdirs
    monkeypatch.setattr("karaoke_gen.nextjs_frontend.get_nextjs_assets_dir", lambda: root)
    monkeypatch.setattr("karaoke_gen.nextjs_frontend.is_nextjs_frontend_available", lambda: True)
    return root


def _make_server(fake_frontend, tmp_path, lyrics_only):
    audio = tmp_path / "main.mp3"
    audio.write_bytes(b"ID3\x03\x00\x00\x00" + b"\x00" * 256)
    cache = tmp_path / "cache"
    cache.mkdir()
    segments = lrc_to_segments(parse_lrc("[00:05.00]Hello darkness\n[00:09.00]my old friend\n"))
    result = build_correction_result(segments, artist="A", title="T", audio_filepath=str(audio))
    result.metadata["audio_hash"] = "abc123"
    server = ReviewServer(
        correction_result=result,
        output_config=OutputConfig(output_styles_json="", cache_dir=str(cache), output_dir=str(cache)),
        audio_filepath=str(audio),
        logger=logging.getLogger("test"),
        lyrics_only=lyrics_only,
    )
    return server, TestClient(server.app)


def _human_edit_payload(client, new_start):
    """Load what the UI loads, then nudge the first word's start time like a human timing words."""
    data = client.get("/api/correction-data").json()
    data["corrected_segments"][0]["words"][0]["start_time"] = new_start
    return data


def test_lyrics_submission_completes_review_and_keeps_human_timing(fake_frontend, tmp_path):
    server, client = _make_server(fake_frontend, tmp_path, lyrics_only=True)
    assert server.review_completed is False

    r = client.post("/api/jobs/local/corrections", json={"corrections": _human_edit_payload(client, 5.25)})

    assert r.status_code == 200, r.text
    assert server.review_completed is True
    assert server.instrumental_selection is None
    assert server.correction_result.corrected_segments[0].words[0].start_time == 5.25
    # No AI/matching artefacts were introduced by the review round trip
    assert server.correction_result.reference_lyrics == {}
    assert server.correction_result.anchor_sequences == []


def test_redirect_target_serves_a_done_page_not_the_broken_instrumental_page(fake_frontend, tmp_path):
    _, client = _make_server(fake_frontend, tmp_path, lyrics_only=True)

    for url in ("/app/jobs/local/instrumental", "/en/app/jobs/local/instrumental"):
        r = client.get(url)
        assert r.status_code == 200, url
        assert "Lyrics saved" in r.text and "close this tab" in r.text


def test_unknown_locale_on_done_page_is_404(fake_frontend, tmp_path):
    _, client = _make_server(fake_frontend, tmp_path, lyrics_only=True)
    assert client.get("/zz-not-a-locale/app/jobs/local/instrumental").status_code == 404


def test_default_behaviour_is_unchanged_submission_does_not_complete(fake_frontend, tmp_path):
    server, client = _make_server(fake_frontend, tmp_path, lyrics_only=False)

    r = client.post("/api/jobs/local/corrections", json={"corrections": _human_edit_payload(client, 5.25)})

    assert r.status_code == 200, r.text
    assert server.review_completed is False  # still waiting for the instrumental step
    assert server.corrections_saved is True


def test_default_server_does_not_register_the_done_page(fake_frontend, tmp_path):
    _, client = _make_server(fake_frontend, tmp_path, lyrics_only=False)
    r = client.get("/app/jobs/local/instrumental")
    assert "Lyrics saved" not in r.text
