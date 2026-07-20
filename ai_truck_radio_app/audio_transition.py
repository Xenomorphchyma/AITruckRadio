# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import List


def music_speech_crossfade_command(
    *,
    ffmpeg: str,
    music_path: Path,
    speech_path: Path,
    music_duration_sec: float,
    overlap_sec: float,
    bitrate_kbps: int,
    music_volume: float,
    speech_volume: float,
) -> List[str]:
    """Build a streaming command for the unplayed music tail + full speech.

    The caller has already streamed the song up to ``duration - overlap``.
    ``acrossfade`` then mixes that exact tail with the start of the speech and
    continues with the remaining speech, producing one gapless MP3 stream.
    """
    duration = max(0.2, float(music_duration_sec))
    overlap = max(0.15, min(float(overlap_sec), duration - 0.05))
    start = max(0.0, duration - overlap)
    music_gain = max(0.0, min(float(music_volume), 2.0))
    speech_gain = max(0.1, min(float(speech_volume), 3.0))
    bitrate = max(64, min(int(bitrate_kbps), 320))
    filter_complex = (
        f"[0:a]atrim=duration={overlap:.3f},asetpts=PTS-STARTPTS,"
        f"aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={music_gain:.3f}[music];"
        "[1:a]aresample=44100,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"highpass=f=65,acompressor=threshold=0.12:ratio=2.5:attack=5:release=120,"
        f"volume={speech_gain:.3f},alimiter=limit=0.96[speech];"
        f"[music][speech]acrossfade=d={overlap:.3f}:c1=exp:c2=tri[out]"
    )
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start:.3f}",
        "-re",
        "-i",
        str(music_path),
        "-re",
        "-i",
        str(speech_path),
        "-filter_complex",
        filter_complex,
        "-map",
        "[out]",
        "-vn",
        "-ar",
        "44100",
        "-ac",
        "2",
        "-b:a",
        f"{bitrate}k",
        "-f",
        "mp3",
        "pipe:1",
    ]
