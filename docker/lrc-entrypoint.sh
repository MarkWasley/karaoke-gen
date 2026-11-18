#!/bin/sh
set -eu

# With no command-line arguments (the normal "docker compose up -d" path),
# build a single-song job from the service environment. Explicit CLI arguments
# still take precedence when the container is started with "docker compose run".
if [ "$#" -eq 0 ]; then
    set -- --lrc_file "${LRC_FILE:-/work/lyrics.lrc}" \
        --existing_instrumental "${INSTRUMENTAL_FILE:-/work/instrumental.flac}"

    if [ -n "${VOCALS_FILE:-}" ]; then
        set -- "$@" --existing_vocals "$VOCALS_FILE"
    fi

    set -- "$@" "${AUDIO_FILE:-/work/song.flac}" "${ARTIST:-Artist}" "${TITLE:-Title}"
fi

has_lrc=0
has_instrumental=0

for arg in "$@"; do
    case "$arg" in
        --lrc_file|--lrc_file=*)
            has_lrc=1
            ;;
        --existing_instrumental|--existing_instrumental=*)
            has_instrumental=1
            ;;
        --skip_transcription_review|--skip-transcription-review)
            echo "This image is for interactive human word-timing review; do not skip transcription review." >&2
            exit 2
            ;;
    esac
done

if [ "$has_lrc" -ne 1 ]; then
    echo "Missing required --lrc_file argument." >&2
    echo "Supply an LRC file and pre-separated instrumental." >&2
    exit 2
fi

if [ "$has_instrumental" -ne 1 ]; then
    echo "Missing required --existing_instrumental argument." >&2
    echo "Audio separation is not included in this image." >&2
    exit 2
fi

export USE_AGENTIC_AI=0
export LYRICS_REVIEW_HOST="${LYRICS_REVIEW_HOST:-0.0.0.0}"
export LYRICS_REVIEW_PORT="${LYRICS_REVIEW_PORT:-8000}"
export LYRICS_REVIEW_OPEN_BROWSER=0
export LYRICS_REVIEW_PUBLIC_URL="${LYRICS_REVIEW_PUBLIC_URL:-http://localhost:${LYRICS_REVIEW_PORT}}"

# This container has no audio-separation models. LRC mode uses the instrumental
# supplied with --existing_instrumental and keeps review on for manual timing.
exec karaoke-gen "$@" --no-video --enable_cdg
