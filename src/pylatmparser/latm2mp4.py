import sys
from .isobmff import mux_to_mp4

def latm2mp4():
    if len(sys.argv) < 3:
        print("usage: latm2mp4 LATMFILE MP4FILE", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], 'rb') as sp:
        with open(sys.argv[2], 'wb') as dp:
            mux_to_mp4(sp, dp)
