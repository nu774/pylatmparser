from collections.abc import ByteString
from flac_bitstream import BitReader as FLAC_BitReader
from flac_bitstream import BitWriter as FLAC_BitWriter
import sys

__all__ = [ 'BitReader', 'BitWriter' ]

class BitReader:
    def __init__(self, data: ByteString):
        self.data = bytes(data[:])
        self.bits = FLAC_BitReader(self.data)
    
    def read(self, nbits: int) -> int:
        return self.bits.read_bits(nbits)

    def tell(self) -> int:
        return len(self.data) * 8 - self.bits.get_input_bits_unconsumed()
    
    def skip(self, len: int) -> None:
        if len > 0:
            self.bits.skip_bits(len)
    
    def byte_align(self) -> None:
        n = self.bits.bits_left_for_byte_alignment()
        self.bits.skip_bits(n)
    
    def read_bytes(self, nbits: int) -> bytes:
        if nbits > 0:
            buf = bytearray((nbits + 7) // 8)
            self.bits.read_byte_block(buf)
        return buf
    
    def tobytes(self) -> bytes:
        bits = FLAC_BitReader(self.data + b'\0')
        n = self.tell()
        bits.skip_bits(n)
        ba = bytearray(len(self.data) - n // 8)
        bits.read_byte_block(ba)
        return ba

    def latm_get_value(self) -> int:
        bytes_for_value = self.read(2)
        value = 0
        for _ in range(bytes_for_value):
            value <<= 8
            value_tmp = self.read(8)
            value |= value_tmp
        return value

class BitWriter:
    def __init__(self):
        self.bits = FLAC_BitWriter()
    
    def write(self, value: int, nbits: int) -> None:
        self.bits.write_bits(value, nbits)

    def byte_align(self) -> None:
        self.bits.zero_pad_to_byte_boundary()
    
    def write_bytes(self, data: ByteString) -> None:
        self.bits.write_byte_block(data)
    
    def tobytes(self) -> bytes:
        self.bits.zero_pad_to_byte_boundary()
        return bytes(self.bits.get_buffer())
