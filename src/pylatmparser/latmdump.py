import sys
from .latm import audio_sync_stream, StreamMuxConfig
from .adts import ADTSHeader

def latmdump():
    if len(sys.argv) < 2:
        print("usage: latm2dump LATMFILE", file=sys.stderr)
        sys.exit(1)
    with open(sys.argv[1], 'rb') as fp:
        for frame in audio_sync_stream(fp):
            print(frame)
