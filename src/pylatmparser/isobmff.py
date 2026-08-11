from __future__ import annotations
import struct
from dataclasses import dataclass, field
from typing import IO
from .latm import Stream, audio_sync_stream
from .asc import sampling_frequency_table

__all__ = ['Mp4Muxer', 'mux_to_mp4']

# Only single-program/single-layer LATM/LOAS streams have ever been observed in
# practice (see the conversation history / ffmpeg's own aacdec.c, which bails
# out with AVERROR_PATCHWELCOME on numProgram/numLayer > 0), so this writer
# targets the common non-fragmented "one trak per LATM stream" case. Scalable
# (layered) coding is not modeled as ISOBMFF track dependencies; each Stream
# just becomes its own independent trak.

_CHANNEL_COUNT_TABLE = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5, 6: 6, 7: 8}


def _channel_count(channel_configuration: int) -> int:
    try:
        return _CHANNEL_COUNT_TABLE[channel_configuration]
    except KeyError:
        raise NotImplementedError(f"unsupported channel_configuration for ISOBMFF mux: {channel_configuration}")


def _box(box_type: bytes, payload: bytes) -> bytes:
    return struct.pack('>I4s', len(payload) + 8, box_type) + payload


def _full_box(box_type: bytes, version: int, flags: int, payload: bytes) -> bytes:
    return _box(box_type, struct.pack('>I', (version << 24) | (flags & 0xffffff)) + payload)


def _descriptor(tag: int, payload: bytes) -> bytes:
    # ISO/IEC 14496-1 expandable class-length: base-128, MSB=1 means "more bytes follow"
    n = len(payload)
    groups = [n & 0x7f]
    n >>= 7
    while n:
        groups.append(n & 0x7f)
        n >>= 7
    groups.reverse()
    length = bytes((g | 0x80) if i < len(groups) - 1 else g for i, g in enumerate(groups))
    return bytes([tag]) + length + payload


def _ftyp() -> bytes:
    return _box(b'ftyp', b'M4A ' + struct.pack('>I', 0) + b'M4A ' + b'mp42' + b'isom')


_UNITY_MATRIX = struct.pack('>9i', 0x00010000, 0, 0, 0, 0x00010000, 0, 0, 0, 0x40000000)


def _mvhd(timescale: int, duration: int, next_track_id: int) -> bytes:
    payload = struct.pack('>IIII', 0, 0, timescale, duration)
    payload += struct.pack('>i', 0x00010000)  # rate = 1.0
    payload += struct.pack('>h', 0x0100)      # volume = 1.0
    payload += b'\x00' * 10                   # reserved
    payload += _UNITY_MATRIX
    payload += b'\x00' * 24                   # pre_defined
    payload += struct.pack('>I', next_track_id)
    return _full_box(b'mvhd', 0, 0, payload)


def _tkhd(track_id: int, duration: int) -> bytes:
    payload = struct.pack('>III', 0, 0, track_id)
    payload += struct.pack('>I', 0)           # reserved
    payload += struct.pack('>I', duration)
    payload += b'\x00' * 8                    # reserved[2]
    payload += struct.pack('>hh', 0, 0)       # layer, alternate_group
    payload += struct.pack('>h', 0x0100)      # volume = 1.0 (audio track)
    payload += struct.pack('>h', 0)           # reserved
    payload += _UNITY_MATRIX
    payload += struct.pack('>II', 0, 0)       # width, height (audio-only track)
    return _full_box(b'tkhd', 0, 0x000007, payload)  # flags: enabled|in_movie|in_preview


def _mdhd(timescale: int, duration: int) -> bytes:
    payload = struct.pack('>IIII', 0, 0, timescale, duration)
    payload += struct.pack('>H', 0x55c4)  # language = 'und'
    payload += struct.pack('>H', 0)       # pre_defined
    return _full_box(b'mdhd', 0, 0, payload)


def _hdlr() -> bytes:
    payload = struct.pack('>I4s', 0, b'soun') + b'\x00' * 12 + b'SoundHandler\x00'
    return _full_box(b'hdlr', 0, 0, payload)


def _smhd() -> bytes:
    return _full_box(b'smhd', 0, 0, struct.pack('>hH', 0, 0))


def _dinf() -> bytes:
    url = _full_box(b'url ', 0, 0x000001, b'')  # flags=1: self-contained, no location needed
    dref = _full_box(b'dref', 0, 0, struct.pack('>I', 1) + url)
    return _box(b'dinf', dref)


def _esds(asc_bytes: bytes, track_id: int) -> bytes:
    dsi = _descriptor(0x05, asc_bytes)  # DecoderSpecificInfo
    dec_cfg_payload = struct.pack('>B', 0x40)      # objectTypeIndication: MPEG-4 Audio
    dec_cfg_payload += struct.pack('>B', 0x15)     # streamType=Audio(5)<<2 | upStream(0)<<1 | reserved(1)
    dec_cfg_payload += (0).to_bytes(3, 'big')      # bufferSizeDB
    dec_cfg_payload += struct.pack('>II', 0, 0)    # maxBitrate, avgBitrate (unknown)
    dec_cfg_payload += dsi
    dec_cfg = _descriptor(0x04, dec_cfg_payload)
    sl_cfg = _descriptor(0x06, b'\x02')            # predefined = MP4 file
    es_payload = struct.pack('>H', track_id & 0xffff) + struct.pack('>B', 0)  # ES_ID, flags
    es_payload += dec_cfg + sl_cfg
    return _full_box(b'esds', 0, 0, _descriptor(0x03, es_payload))


def _mp4a(channel_count: int, sample_rate: int, asc_bytes: bytes, track_id: int) -> bytes:
    if sample_rate > 0xffff:
        raise NotImplementedError(f"sample rate too high for AudioSampleEntry: {sample_rate}")
    entry = b'\x00' * 6 + struct.pack('>H', 1)     # reserved[6], data_reference_index=1
    entry += b'\x00' * 8                            # reserved[2]
    entry += struct.pack('>HHHH', channel_count, 16, 0, 0)  # channelcount, samplesize, pre_defined, reserved
    entry += struct.pack('>I', sample_rate << 16)
    entry += _esds(asc_bytes, track_id)
    return _box(b'mp4a', entry)


def _stsd(track: '_Track') -> bytes:
    entry = _mp4a(track.channel_count, track.sample_rate, track.asc_bytes, track.track_id)
    return _full_box(b'stsd', 0, 0, struct.pack('>I', 1) + entry)


def _stts(deltas: list[int]) -> bytes:
    entries: list[list[int]] = []
    for d in deltas:
        if entries and entries[-1][1] == d:
            entries[-1][0] += 1
        else:
            entries.append([1, d])
    payload = struct.pack('>I', len(entries))
    for count, delta in entries:
        payload += struct.pack('>II', count, delta)
    return _full_box(b'stts', 0, 0, payload)


def _stsc(sample_count: int) -> bytes:
    if sample_count == 0:
        return _full_box(b'stsc', 0, 0, struct.pack('>I', 0))
    payload = struct.pack('>I', 1) + struct.pack('>III', 1, 1, 1)
    return _full_box(b'stsc', 0, 0, payload)


def _stsz(sizes: list[int]) -> bytes:
    payload = struct.pack('>II', 0, len(sizes))
    for s in sizes:
        payload += struct.pack('>I', s)
    return _full_box(b'stsz', 0, 0, payload)


def _stco_or_co64(offsets: list[int]) -> bytes:
    if offsets and max(offsets) > 0xffffffff:
        payload = struct.pack('>I', len(offsets))
        for o in offsets:
            payload += struct.pack('>Q', o)
        return _full_box(b'co64', 0, 0, payload)
    payload = struct.pack('>I', len(offsets))
    for o in offsets:
        payload += struct.pack('>I', o)
    return _full_box(b'stco', 0, 0, payload)


def _stbl(track: '_Track') -> bytes:
    payload = _stsd(track)
    payload += _stts(track.sample_deltas)
    payload += _stsc(len(track.sample_sizes))
    payload += _stsz(track.sample_sizes)
    payload += _stco_or_co64(track.sample_offsets)
    return _box(b'stbl', payload)


def _minf(track: '_Track') -> bytes:
    return _box(b'minf', _smhd() + _dinf() + _stbl(track))


def _mdia(track: '_Track') -> bytes:
    duration = sum(track.sample_deltas)
    payload = _mdhd(track.sample_rate, duration)
    payload += _hdlr()
    payload += _minf(track)
    return _box(b'mdia', payload)


def _trak(track: '_Track', movie_timescale: int) -> bytes:
    media_duration = sum(track.sample_deltas)
    movie_duration = round(media_duration * movie_timescale / track.sample_rate) if track.sample_rate else 0
    return _box(b'trak', _tkhd(track.track_id, movie_duration) + _mdia(track))


def _moov(tracks: list['_Track'], movie_timescale: int) -> bytes:
    next_track_id = max((t.track_id for t in tracks), default=0) + 1
    movie_duration = max(
        (round(sum(t.sample_deltas) * movie_timescale / t.sample_rate) for t in tracks if t.sample_rate),
        default=0,
    )
    payload = _mvhd(movie_timescale, movie_duration, next_track_id)
    for t in tracks:
        payload += _trak(t, movie_timescale)
    return _box(b'moov', payload)


def _mdat_open(dp: IO[bytes]) -> int:
    # Always use the 64-bit largesize form so the header doesn't need to
    # change shape once the real size is known (streamed, not buffered).
    pos = dp.tell()
    dp.write(struct.pack('>I4s', 1, b'mdat'))
    dp.write(struct.pack('>Q', 0))
    return pos


def _mdat_close(dp: IO[bytes], pos: int) -> None:
    end = dp.tell()
    size = end - pos
    dp.seek(pos)
    dp.write(struct.pack('>I4s', 1, b'mdat'))
    dp.write(struct.pack('>Q', size))
    dp.seek(end)


@dataclass(slots=True)
class _Track:
    track_id: int
    sample_rate: int
    channel_count: int
    samples_per_frame: int
    asc_bytes: bytes
    sample_sizes: list[int] = field(default_factory=list)
    sample_deltas: list[int] = field(default_factory=list)
    sample_offsets: list[int] = field(default_factory=list)

    def add_sample(self, offset: int, payload: bytes) -> None:
        self.sample_offsets.append(offset)
        self.sample_sizes.append(len(payload))
        self.sample_deltas.append(self.samples_per_frame)


class Mp4Muxer:
    """Writes a single non-fragmented MP4 (moov-at-end) from LATM/LOAS streams.

    Each LATM Stream (program/layer combination) becomes its own audio trak;
    only the stream layout seen in the first StreamMuxConfig is used, since
    that is the only case that's been observed/testable (see the design
    discussion this module grew out of).
    """

    def __init__(self, dp: IO[bytes], streams: list[Stream]):
        self.dp = dp
        self.tracks: dict[int, _Track] = {}
        for s in streams:
            fmt = s.audio_specific_config.format
            sample_rate = fmt.sampling_frequency or sampling_frequency_table[fmt.sampling_frequency_index]
            self.tracks[s.id] = _Track(
                track_id=s.id + 1,
                sample_rate=sample_rate,
                channel_count=_channel_count(fmt.channel_configuration),
                samples_per_frame=s.audio_specific_config.num_samples_per_frame,
                asc_bytes=s.audio_specific_config_bytes,
            )
        dp.write(_ftyp())
        self._mdat_pos = _mdat_open(dp)

    def add_sample(self, stream_id: int, payload: bytes) -> None:
        track = self.tracks[stream_id]
        offset = self.dp.tell()
        self.dp.write(payload)
        track.add_sample(offset, payload)

    def finish(self) -> None:
        _mdat_close(self.dp, self._mdat_pos)
        first_track = next(iter(self.tracks.values()))
        movie_timescale = first_track.sample_rate or 1000
        self.dp.write(_moov(list(self.tracks.values()), movie_timescale))


def mux_to_mp4(sp: IO[bytes], dp: IO[bytes]) -> None:
    muxer: Mp4Muxer | None = None
    for frame in audio_sync_stream(sp):
        if frame.stream_mux_config and muxer is None:
            muxer = Mp4Muxer(dp, frame.stream_mux_config.streams)
        if muxer is None:
            continue
        for sub_frame in frame.sub_frames:
            for packet in sub_frame:
                muxer.add_sample(packet.stream_id, packet.payload)
    if muxer is not None:
        muxer.finish()
