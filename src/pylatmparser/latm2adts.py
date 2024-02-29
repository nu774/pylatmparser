import sys
from .latm import audio_sync_stream, StreamMuxConfig
from .adts import ADTSHeader

def latm2adts():
    if len(sys.argv) < 3:
        print("usage: latm2adts LATMFILE ADTSFILE", file=sys.stderr)
        sys.exit(1)
    stream_mux_config: StreamMuxConfig | None = None
    with open(sys.argv[1], 'rb') as sp:
        with open(sys.argv[2], 'wb') as dp:
            for frame in audio_sync_stream(sp):
                if frame.stream_mux_config:
                    stream_mux_config = frame.stream_mux_config
                payload = frame.sub_frames[0][0].payload
                adts_header: ADTSHeader = ADTSHeader.from_format(stream_mux_config.streams[0].audio_specific_config.format, len(payload))
                dp.write(adts_header.tobytes())
                dp.write(frame.sub_frames[0][0].payload)
