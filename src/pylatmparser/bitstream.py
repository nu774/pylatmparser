from collections.abc import ByteString
from bitarray import bitarray
from bitarray.util import ba2int, int2ba

__all__ = [ 'BitReader', 'BitWriter' ]

class BitReader:
    def __init__(self, data: ByteString):
        self.bits = bitarray()
        self.bits.frombytes(data)
        self.pos = 0
    
    def read(self, nbits: int) -> int:
        value = ba2int(self.bits[self.pos:self.pos+nbits])
        self.pos += nbits
        return value

    def tell(self) -> int:
        return self.pos
    
    def seek(self, pos: int) -> None:
        self.pos = pos
    
    def byte_align(self) -> None:
        self.pos = ((self.pos + 7) // 8) * 8
    
    def read_bytes(self, nbits: int) -> bytes:
        value = self.bits[self.pos:self.pos+nbits].tobytes()
        self.pos += nbits
        return value
    
    def tobytes(self) -> bytes:
        return self.bits[self.pos:].tobytes()

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
        self.bits = bitarray()
    
    def write(self, value: int, nbits: int) -> None:
        self.bits.extend(int2ba(value, length=nbits))

    def byte_align(self) -> None:
        pos = ((len(self.bits) + 7) // 8) * 8
        while len(self.bits) < pos:
            self.bits.append(0)
    
    def write_bytes(self, data: ByteString) -> None:
        self.bits.frombytes(data)
    
    def tobytes(self) -> bytes:
        return self.bits.tobytes()
