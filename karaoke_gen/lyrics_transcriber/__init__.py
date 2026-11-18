from importlib.metadata import version, PackageNotFoundError

# Importing the package must not load the transcription/controller stack. The
# LRC import and manual review path only needs the lightweight config/types.
from karaoke_gen.lyrics_transcriber.core.config import TranscriberConfig, LyricsConfig, OutputConfig

try:
    __version__ = version("lyrics-transcriber")
except PackageNotFoundError:
    __version__ = "unknown"


def __getattr__(name):
    """Load the AI/transcription controller only when it is explicitly requested."""
    if name == "LyricsTranscriber":
        from karaoke_gen.lyrics_transcriber.core.controller import LyricsTranscriber
        return LyricsTranscriber
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["LyricsTranscriber", "TranscriberConfig", "LyricsConfig", "OutputConfig"]
