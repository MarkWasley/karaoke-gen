# Lightweight Docker setup for LRC import

This image is intended for tracks where audio separation has already been done and lyrics are supplied as a line-timed LRC file.

It deliberately does **not** install PyTorch, audio-separator, Demucs, Whisper, transformers, spaCy, Ollama or the LangChain/LLM integrations. The container handles the LRC import, Human Review, and the normal non-AI output steps.

## Build

From the repository root:

```bash
docker compose build
```

The image builds the Next.js Human Review UI as a separate Node build stage, then copies the static files into a Python runtime image. Node and npm are not present in the final image.

## Prepare files

Put the track files under `./data` on the Docker host. For example:

```text
data/
  My Song Vocals.wav
  My Song Instrumental.flac
  My Song.lrc
cache/
```

The LRC file should contain standard line timestamps such as `[00:12.34]Lyric line`.

## Run

```bash
docker compose run --rm --service-ports karaoke-gen \
  --skip-separation \
  --lrc_file "/data/My Song.lrc" \
  --existing_instrumental "/data/My Song Instrumental.flac" \
  "/data/My Song Vocals.wav" "Artist" "My Song"
```

The CLI starts Human Review. Open [http://localhost:8000/app/jobs/local/review](http://localhost:8000/app/jobs/local/review) in a browser on the Docker host. Keep the terminal open until review is complete.

If you access Docker from another computer or phone, create a `.env` file and set `LYRICS_REVIEW_URL` to the Docker host's LAN address, for example:

```dotenv
LYRICS_REVIEW_URL=http://192.168.1.20:8000/app/jobs/local/review
LYRICS_REVIEW_PORT=8000
```

The browser must be able to reach the Docker host on the configured port.

## Data and cache

- `./data` is mounted at `/data`; input and generated track files persist on the host.
- `./cache` is mounted at `/cache`; review sessions and processing cache persist on the host.
- The review server listens on container port 8000. Change the host-side port with `LYRICS_REVIEW_PORT`.

The first build downloads the Node and Python dependencies and builds the frontend. Subsequent builds use Docker's layer cache.
