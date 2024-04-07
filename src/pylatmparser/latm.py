from __future__ import annotations
from collections.abc import ByteString
from dataclasses import dataclass, field
from typing import IO, Iterable
from .bitstream import BitReader
from .asc import AudioSpecificConfig

__all__ = ['Stream', 'StreamMuxConfig', 'LatmPacket', 'AudioMuxElement', 'audio_sync_stream']

@dataclass(eq=True, slots=True)
class Stream:
    id: int = 0
    program: int = 0
    layer: int = 0
    audio_specific_config: AudioSpecificConfig | None = None
    frame_length_type:int = 0
    latm_buffer_fullness:int | None = None
    core_frame_offset:int | None = None


@dataclass(eq=True, slots=True)
class StreamMuxConfig:
    audio_mux_version: int = 0
    audio_mux_version_a: int = 0
    tara_buffer_fullness: int | None = None
    all_streams_same_time_framing: int = 0
    num_sub_frames: int = 0
    num_program: int = 0
    streams: list[Stream] = field(default_factory=list)
    other_data_present: int = 0
    other_data_len_bits: int | None = None
    crc_check_present: int = 0
    crc_check_sum: int | None = None

    @classmethod
    def decode(cls, bits: BitReader) -> StreamMuxConfig:
        obj = StreamMuxConfig()
        obj.audio_mux_version = bits.read(1)
        obj.audio_mux_version_a = 0
        if obj.audio_mux_version:
            obj.audio_mux_version_a = bits.read(1)
        if obj.audio_mux_version_a != 0:
            raise NotImplementedError(f"unsupported audioMuxVersionA: {obj.audio_mux_version_a}")
        if obj.audio_mux_version:
            obj.tara_buffer_fullness = bits.latm_get_value()
        obj.all_streams_same_time_framing = bits.read(1)
        obj.num_sub_frames = bits.read(6) + 1
        obj.num_program = bits.read(4) + 1

        stream_cnt = 0
        for prog in range(obj.num_program):
            num_layer = bits.read(3) + 1
            for lay in range(num_layer):
                stream = Stream(id=stream_cnt, program=prog, layer=lay)
                stream_cnt += 1
                
                if prog == 0 and lay == 0:
                    use_same_config = 0
                else:
                    use_same_config = bits.read(1)
                
                if use_same_config:
                    stream.audio_specific_config = obj.streams[-1].audio_specific_config
                elif obj.audio_mux_version == 0:
                    stream.audio_specific_config = AudioSpecificConfig.decode(bits)
                else:
                    asc_len = bits.latm_get_value()
                    stream.audio_specific_config = AudioSpecificConfig.decode(bits, asc_len)
                
                stream.frame_length_type = bits.read(3)
                if stream.frame_length_type == 0:
                    stream.latm_buffer_fullness = bits.read(8)
                    if not obj.all_streams_same_time_framing:
                        if lay > 0 and \
                           stream.audio_specific_config.format.audio_object_type in (6, 20) and \
                           obj.streams[-1].audio_specific_config.format.audio_object_type in (8, 24):
                            stream.core_frame_offset = bits.read(6)
                else:
                    raise NotImplementedError(f"unsupported frame_length_type: {stream.frame_length_type}")
                
                obj.streams.append(stream)

        obj.other_data_present = bits.read(1)
        if obj.other_data_present:
            if obj.audio_mux_version == 1:
                obj.other_data_len_bits = bits.latm_get_value()
            else:
                obj.other_data_len_bits = 0
                while True:
                    obj.other_data_len_bits <<= 8
                    esc = bits.read(1)
                    tmp = bits.read(8)
                    obj.other_data_len_bits |= tmp
                    if not esc: break
        
        obj.crc_check_present = bits.read(1)
        if obj.crc_check_present:
            obj.crc_check_sum = bits.read(8)
        return obj


@dataclass(eq=True, slots=True)
class LatmPacket:
    stream_id: int = 0
    mux_slot_length_bytes: int = 0
    au_end_flag: int | None = None
    payload: bytes = b''

    def decode_length_info(self, bits: BitReader, stream: Stream, has_end_flags: bool) -> None:
        if stream.frame_length_type != 0:
            raise NotImplementedError(f"unsupported frame_length_type: {stream.frame_length_type}")
        self.mux_slot_length_bytes = 0
        while True:
            tmp = bits.read(8)
            self.mux_slot_length_bytes += tmp
            if tmp != 0xff: break
        if has_end_flags:
            self.au_end_flag = bits.read(1)
    
    def decode_payload(self, bits: BitReader, stream: Stream) -> None:
        if stream.frame_length_type != 0:
            raise NotImplementedError(f"unsupported frame_length_type: {stream.frame_length_type}")
        self.payload = bits.read_bytes(self.mux_slot_length_bytes * 8)


@dataclass(eq=True, slots=True)
class PayloadLengthInfo:
    num_chunk: int = 0
    chunk_stream: list[int] = field(default_factory=list)

    @classmethod
    def decode(cls, bits: BitReader, mc: StreamMuxConfig, packets: list[LatmPacket]) -> PayloadLengthInfo:
        obj = PayloadLengthInfo()
        if mc.all_streams_same_time_framing:
            for packet in packets:
                packet.decode_length_info(bits, mc.streams[packet.stream_id], False)
        else:
            obj.num_chunk = bits.read(4) + 1
            for _ in range(obj.num_chunk):
                stream_id = bits.read(4)
                obj.chunk_stream.append(stream_id)
                packets[stream_id].decode_length_info(bits, mc.streams[stream_id], True)
        return obj


def decode_payload_mux(bits: BitReader, mc: StreamMuxConfig, packets: list[LatmPacket], chunk_stream: list[int]) -> None:
    if mc.all_streams_same_time_framing:
        for packet in packets:
            packet.decode_payload(bits, mc.streams[packet.stream_id])
    else:
        for stream_id in chunk_stream:
            packets[stream_id].decode_payload(bits, mc.streams[stream_id])


@dataclass(eq=True, slots=True)
class AudioMuxElement:
    stream_mux_config: StreamMuxConfig | None = None
    sub_frames: list[list[LatmPacket]] = field(default_factory=list)
    use_same_stream_mux: int | None = None
    other_data_bit: bytes | None = None

    @classmethod
    def decode(cls, bits: BitReader, stream_mux_config: StreamMuxConfig, mux_config_present: bool) -> AudioMuxElement:
        obj = AudioMuxElement()
        if mux_config_present:
            obj.use_same_stream_mux = bits.read(1)
            if not obj.use_same_stream_mux:
                obj.stream_mux_config = StreamMuxConfig.decode(bits)
                stream_mux_config = obj.stream_mux_config
        if not stream_mux_config:
            return
        mc = stream_mux_config
        if mc.audio_mux_version_a != 0:
            raise NotImplementedError(f"unsupported audioMuxVersionA: {mc.audio_mux_version_a}")
        obj.sub_frames = [[LatmPacket(stream_id=stream.id) for stream in mc.streams] for _ in range(mc.num_sub_frames)]
        for i in range(mc.num_sub_frames):
            payload_length_info = PayloadLengthInfo.decode(bits, mc, obj.sub_frames[i])
            decode_payload_mux(bits, mc, obj.sub_frames[i], payload_length_info.chunk_stream)
        if mc.other_data_present:
            obj.other_data_bit = bits.read(mc.other_data_len_bits)
        bits.byte_align()
        return obj
    

def resync(fp: IO[bytes], buf: memoryview) -> int:
    if fp.readinto(buf[:2]) != 2:
        return 0
    word = buf[0]<<8 | buf[1]
    while True:
        if not fp.readinto(buf[:1]):
            return 0
        word = (word << 8 | buf[0]) & 0xffffff
        if word >> 13 != 0x2b7:
            continue
        return word

def audio_sync_stream(fp: IO[bytes]) -> Iterable[AudioMuxElement]:
    stream_mux_config: StreamMuxConfig | None = None
    buf = memoryview(bytearray(0x2000))
    while True:
        word = resync(fp, buf)
        if word >> 13 != 0x2b7:
            break
        audio_mux_length_bytes = word & 0x1fff
        if fp.readinto(buf[:audio_mux_length_bytes]) != audio_mux_length_bytes:
            break
        bs = BitReader(buf[:audio_mux_length_bytes])
        audio_mux_element = AudioMuxElement.decode(bs, stream_mux_config, True)
        if audio_mux_element.stream_mux_config:
            stream_mux_config = audio_mux_element.stream_mux_config
        yield audio_mux_element
