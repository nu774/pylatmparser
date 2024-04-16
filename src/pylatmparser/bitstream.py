try:
    from .bitstream_flac import BitReader, BitWriter
except:
    from .bitstream_bitarray import BitReader, BitWriter

__all__ = [ 'BitReader', 'BitWriter' ]
