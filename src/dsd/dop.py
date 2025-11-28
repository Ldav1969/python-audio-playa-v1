"""
Experimental DoP (DSD over PCM) packer utilities.

Notes:
- This module implements an experimental DoP packer intended to package raw
  DSD bytes into DoP 24-bit PCM frames (3 bytes per channel per PCM sample).
- DoP requires a marker byte pattern (commonly 0x05/0xFA markers alternating)
  inserted into the 3rd byte of each 3-byte word (implementation details vary).
- This implementation is a prototype and may need adjustments for real DACs.
- You must ensure ffmpeg is producing raw DSD bytes in the expected bit order.
"""

from typing import Iterator

# DoP markers alternate between 0x05 and 0xFA in the MSB of the 3rd byte of each 3-byte word
DOP_MARKER_A = 0x05
DOP_MARKER_B = 0xFA

def dop_pack_raw_dsd_to_dop_frames(raw_dsd_stream, channels: int) -> Iterator[bytes]:
    """
    Convert a raw DSD byte stream to DoP-wrapped PCM frames (24-bit, 3 bytes per channel).

    - raw_dsd_stream: a file-like object (e.g., ffmpeg stdout) returning raw bytes from DSD decode.
      The function reads from raw_dsd_stream and yields DoP-wrapped PCM frames (bytes).
    - channels: number of channels to produce per frame.

Important notes (experimental):
- This simple prototype treats incoming DSD bytes as a byte stream and groups them into
  3-byte DoP frames per channel. Real DOP packing maps multiple DSD bits across
  the 3 bytes and uses marker bytes in a specific bit position. If ffmpeg can
  be made to emit per-channel DSD bytes aligned to what this expects, this will
  work for some DACs; otherwise the packing logic needs to be adapted.
- Typically for DSD64 the PCM DoP sample rate is 176.4 kHz (DSD rate / 16),
  and for DSD128 it's 352.8 kHz (DSD rate / 8), etc. Make sure to open the ALSA
  device at the correct PCM rate when using DoP.
    """
    # We will alternate marker bytes per PCM sample across the whole stream.
    marker_toggle = False

    # We'll read per-channel DSD bytes in blocks. The precise correlation of incoming
    # raw_dsd_stream bytes to DoP frame bytes depends on how ffmpeg outputs DSD;
    # this is intentionally a small/simple first pass which you should validate on hardware.
    # Here, we read 3 * channels bytes per PCM sample and craft a 3*channels-byte DoP frame.
    # If the incoming stream provides bits at a higher density, you'll need to downsample/pack properly.

    bytes_per_dop_frame = 3 * channels

    while True:
        data = raw_dsd_stream.read(bytes_per_dop_frame)
        if not data:
            break

        # If not enough data, pad with zeroes (EOF handling)
        if len(data) < bytes_per_dop_frame:
            data = data.ljust(bytes_per_dop_frame, b'\x00')

        # Convert to mutable bytearray so we can insert marker bits
        frame = bytearray(data[:bytes_per_dop_frame])

        # Insert marker pattern into each channel's 3-byte word.
        # We'll set the LSB of the third byte (index 2 of each 3-byte word) to marker value,
        # preserving other bits. This is a simplistic approach; you may need to adjust
        # which bits/bytes contain the marker for your DAC.
        for ch in range(channels):
            base = ch * 3
            # Set MSB of that byte to marker (or full byte depending on expectations)
            frame[base + 2] = (frame[base + 2] & 0x00) | (DOP_MARKER_A if marker_toggle else DOP_MARKER_B)
        marker_toggle = not marker_toggle

        yield bytes(frame)
