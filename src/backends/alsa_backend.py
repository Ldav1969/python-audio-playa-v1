"""ALSA backend for best-effort hw/"exclusive" playback on Linux.

This module uses the pyalsaaudio (alsaaudio) binding to open an ALSA PCM device
and stream raw PCM data produced by ffmpeg. It's intended as a platform-specific
backend for Linux to allow opening ALSA hw devices directly (e.g. "hw:0,0").

Notes and limitations:
- This is a best-effort implementation. Actual exclusive mode behavior depends
  on the ALSA device and system configuration. For many USB DACs and hardware
  that supports the requested samplerate, opening the hw device with the file's
  samplerate will yield bit-perfect playback.
- We try float32 output first (f32le). If the device or pyalsaaudio does not
  support float, we fall back to signed 16-bit (s16le).
- The function cooperates with threading.Event stop_event and pause_event.
"""

from __future__ import annotations
import subprocess
import time
import threading
from typing import Optional

try:
    import alsaaudio
except Exception as e:
    alsaaudio = None  # will raise informative errors when used

def _ffmpeg_proc(filename: str, channels: int, samplerate: int, ff_fmt: str):
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        filename,
        "-f",
        ff_fmt,
        "-acodec",
        f"pcm_{ff_fmt}",
        "-ac",
        str(channels),
        "-ar",
        str(samplerate),
        "pipe:1",
    ]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=10 ** 6)

def play_alsa(
    filename: str,
    channels: int,
    samplerate: int,
    stop_event: threading.Event,
    pause_event: threading.Event,
    device_name: Optional[str] = None,
    try_exclusive: bool = False,
):
    """Play the given file through ALSA using pyalsaaudio.

    Parameters
    - filename: path to audio file
    - channels: number of channels to configure
    - samplerate: desired sample rate to open device with
    - stop_event, pause_event: threading.Event objects to control playback
    - device_name: ALSA device string (e.g. 'hw:0,0' or 'plughw:0,0'). If None,
      'default' is used.
    - try_exclusive: if True, open device in blocking mode which may be closer
      to exclusive behavior on some systems. If False, open non-blocking.
    """
    if alsaaudio is None:
        raise RuntimeError("pyalsaaudio (alsaaudio) is not installed. Install pyalsaaudio to use ALSA backend.")

    device = device_name or "default"

    # Try float first, then s16 as a fallback.
    fmt_candidates = [
        ("f32le", alsaaudio.PCM_FORMAT_FLOAT_LE, 4),
        ("s16le", alsaaudio.PCM_FORMAT_S16_LE, 2),
    ]

    last_err = None
    for ff_fmt, alsa_fmt, bytes_per_sample in fmt_candidates:
        pcm = None
        proc = None
        try:
            mode = alsaaudio.PCM_NORMAL if try_exclusive else alsaaudio.PCM_NONBLOCK
            pcm = alsaaudio.PCM(type=alsaaudio.PCM_PLAYBACK, mode=mode, device=device)
            pcm.setchannels(channels)
            pcm.setrate(samplerate)
            pcm.setformat(alsa_fmt)
            # Smaller periodsize gives lower latency; tune as needed
            try:
                pcm.setperiodsize(1024)
            except Exception:
                pass

            proc = _ffmpeg_proc(filename, channels, samplerate, ff_fmt)
            if proc.stdout is None:
                raise RuntimeError("ffmpeg did not produce stdout")

            # Read and write loop
            chunk_frames = 1024
            chunk_bytes = chunk_frames * channels * bytes_per_sample

            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.05)
                    continue

                data = proc.stdout.read(chunk_bytes)
                if not data:
                    # EOF
                    break

                # write may raise ALSAAudioError on underrun/device error
                try:
                    pcm.write(data)
                except Exception as e:
                    last_err = e
                    raise

            # clean normal exit
            return

        except Exception as e:
            last_err = e
            # cleanup and try next format
            try:
                if proc:
                    proc.kill()
            except Exception:
                pass
            try:
                if proc and proc.stdout:
                    proc.stdout.close()
            except Exception:
                pass
            try:
                if pcm:
                    pcm.close()
            except Exception:
                pass
            # try next candidate
            continue

    # all candidates failed
    raise RuntimeError(f"ALSA playback failed: {last_err}")
