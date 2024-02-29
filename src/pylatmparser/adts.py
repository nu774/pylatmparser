from __future__ import annotations
from dataclasses import dataclass
from typing import IO, Iterable
from .bitstream import BitReader, BitWriter
from .asc import Format

__all__ = [ 'ADTSHeader', 'adts_sequence' ]

ADTS_HEADER_LENGTH = 7

@dataclass(eq=True, slots=True)
class ADTSHeader(Format):
    id: int = 0
    layer: int = 0
    protection_absent: int = 0
    private_bit: int = 0
    original_copy: int = 0
    home: int = 0
    copyright_identification_bit: int = 0
    copyright_identification_start: int = 0
    aac_frame_length: int = 0
    adts_buffer_fullness: int = 0
    number_of_raw_data_blocks_in_frame: int = 0

    @classmethod
    def decode(cls, bits: BitReader) -> ADTSHeader:
        obj = ADTSHeader()
        sync = bits.read(12)
        if sync != 0xfff:
            raise ValueError(f'invalid ADTS header: sync={sync}')
        obj.id = bits.read(1)
        obj.layer = bits.read(2)
        if obj.layer != 0:
            raise ValueError(f'invalid ADTS header: layer={obj.layer}')
        obj.protection_absent = bits.read(1)
        obj.audio_object_type = bits.read(2) + 1
        obj.sampling_frequency_index = bits.read(4)
        obj.private_bit = bits.read(1)
        obj.channel_configuration = bits.read(3)
        obj.original_copy = bits.read(1)
        obj.home = bits.read(1)
        obj.copyright_identification_bit = bits.read(1)
        obj.copyright_identification_start = bits.read(1)
        obj.aac_frame_length = bits.read(13)
        obj.adts_buffer_fullness = bits.read(11)
        obj.number_of_raw_data_blocks_in_frame = bits.read(2)
        if obj.number_of_raw_data_blocks_in_frame != 0:
            raise NotImplementedError(f'ADTS: number_of_raw_data_blocks_in_frame > 0 is not supported')
        return obj
    
    @classmethod
    def from_format(cls, format: Format, payload_len: int) -> ADTSHeader:
        if format.audio_object_type != 2 or format.channel_configuration == 0:
            raise NotImplementedError(f'ADTS: format not supported')
        obj = ADTSHeader()
        obj.protection_absent = 1
        obj.audio_object_type = format.audio_object_type
        obj.sampling_frequency_index = format.sampling_frequency_index
        obj.channel_configuration = format.channel_configuration
        obj.aac_frame_length = payload_len + ADTS_HEADER_LENGTH
        obj.adts_buffer_fullness = 0x7ff
        return obj

    def encode(self, bits: BitWriter):
        bits.write(0xfff, 12)
        bits.write(self.id, 1)
        bits.write(self.layer, 2)
        bits.write(self.protection_absent, 1)
        bits.write(self.audio_object_type - 1, 2)
        bits.write(self.sampling_frequency_index, 4)
        bits.write(self.private_bit, 1)
        bits.write(self.channel_configuration, 3)
        bits.write(self.original_copy, 1)
        bits.write(self.home, 1)
        bits.write(self.copyright_identification_bit, 1)
        bits.write(self.copyright_identification_start, 1)
        bits.write(self.aac_frame_length, 13)
        bits.write(self.adts_buffer_fullness, 11)
        bits.write(self.number_of_raw_data_blocks_in_frame, 2)
    
    def tobytes(self) -> bytes:
        bits = BitWriter()
        self.encode(bits)
        return bits.tobytes()


def resync(fp: IO[bytes], buf: memoryview) -> int:
    if not fp.readinto(buf[:1]):
        return 0
    word = buf[0]
    while True:
        if not fp.readinto(buf[:1]):
            return 0
        word = (word << 8 | buf[0]) & 0xffff
        if word >> 4 != 0xfff:
            continue
        return word


def adts_sequence(fp: IO[bytes]) -> Iterable[tuple[ADTSHeader, bytes]]:
    buf = memoryview(bytearray(0x2000))
    while True:
        word = resync(fp, buf)
        if word >> 4 != 0xfff:
            break
        buf[0] = word >> 8
        buf[1] = word & 0xff
        if fp.readinto(buf[2:ADTS_HEADER_LENGTH]) != ADTS_HEADER_LENGTH - 2:
            break
        hdr = ADTSHeader.decode(BitReader(buf[:ADTS_HEADER_LENGTH]))
        if fp.readinto(buf[ADTS_HEADER_LENGTH:hdr.aac_frame_length]) != hdr.aac_frame_length - ADTS_HEADER_LENGTH:
            break
        # we only handle the case where number_of_raw_data_blocks_in_frame == 0
        off = ADTS_HEADER_LENGTH if hdr.protection_absent else ADTS_HEADER_LENGTH + 2
        yield (hdr, buf[off:hdr.aac_frame_length].tobytes())
        