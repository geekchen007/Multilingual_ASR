"""Normalize uploaded recordings for fair ASR comparisons."""

import hashlib
import subprocess
import uuid
import wave

from flask import Flask, abort
from werkzeug.datastructures import FileStorage


def normalize_audio(
    app: Flask, upload: FileStorage, start: float, end: float | None
) -> tuple[str, float, str]:
    """Save a mono 16 kHz WAV clip and return its filename, duration and hash."""
    if not upload or not upload.filename:
        abort(400, "请提供音频或视频文件")
    raw = app.config["DATA"] / (uuid.uuid4().hex + ".upload")
    clip = app.config["DATA"] / (uuid.uuid4().hex + ".wav")
    try:
        upload.save(raw)
        limit = end - start if end is not None else 120
        command = [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file,pipe",
            "-ss",
            str(start),
            "-i",
            str(raw),
            "-t",
            str(limit),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-y",
            str(clip),
        ]
        subprocess.run(command, check=True, capture_output=True, timeout=90)
        with wave.open(str(clip), "rb") as audio:
            duration = audio.getnframes() / audio.getframerate()
        if duration < 0.1:
            raise ValueError("empty clip")
        return clip.name, duration, hashlib.sha256(clip.read_bytes()).hexdigest()
    except FileNotFoundError:
        clip.unlink(missing_ok=True)
        abort(503, "未找到 FFmpeg，请安装并加入 PATH")
    except (subprocess.SubprocessError, ValueError, wave.Error, EOFError):
        clip.unlink(missing_ok=True)
        abort(400, "无法读取音频，或选段超出文件范围")
    finally:
        raw.unlink(missing_ok=True)
