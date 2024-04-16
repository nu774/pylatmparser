from __future__ import annotations
from dataclasses import dataclass, field
from .bitstream import BitReader
import sys

__all__ = [
    'ChannelElement',
    'CCElement',
    'MatrixMixdown',
    'ProgramConfigElement',
    'Format',
    'BSACExtension',
    'ERExtension',
    'GASpecificConfig',
    'SBRHeaderExtra1',
    'SBRHeaderExtra2',
    'SBRHeader',
    'ELDSBRConfig',
    'ELDSpecificConfig',
    'AudioSpecificConfig',
]

@dataclass(eq=True, slots=True)
class ChannelElement:
    is_cpe: int = 0
    tag_select: int = 0

    @classmethod
    def decode(cls, bits: BitReader, decode_cpe: bool) -> ChannelElement:
        obj = ChannelElement()
        obj.is_cpe = bits.read(1) if decode_cpe else 0
        obj.tag_select = bits.read(4)
        return obj

@dataclass(eq=True, slots=True)
class CCElement:
    is_ind_sw: int = 0
    tag_select: int = 0

    @classmethod
    def decode(cls, bits: BitReader) -> CCElement:
        obj = CCElement()
        obj.is_ind_sw = bits.read(1)
        obj.tag_select = bits.read(4)
        return obj

@dataclass(eq=True, slots=True)
class MatrixMixdown:
    idx: int = 0
    psuedo_surround_enable: int = 0

    @classmethod
    def decode(cls, bits: BitReader) -> MatrixMixdown:
        obj = MatrixMixdown()
        obj.idx = bits.read(2)
        obj.psuedo_surround_enable = bits.read(1)
        return obj

@dataclass(eq=True, slots=True)
class ProgramConfigElement:
    element_instance_tag: int = 0
    object_type: int = 0
    sampling_frequency_index: int = 0
    front_channel_elements: list[ChannelElement] = field(default_factory=list)
    side_channel_elements: list[ChannelElement] = field(default_factory=list)
    back_channel_elements: list[ChannelElement] = field(default_factory=list)
    lfe_channel_elements: list[ChannelElement] = field(default_factory=list)
    assoc_data_elements: list[ChannelElement] = field(default_factory=list)
    valid_cc_elements: list[CCElement] = field(default_factory=list)
    mono_mixdown_element_number: int | None = None
    stereo_mixdown_element_number: int | None = None
    matrix_mixdown: MatrixMixdown | None = None
    comment_field_data: bytes = b''

    @classmethod
    def decode(cls, bits: BitReader) -> ProgramConfigElement:
        obj = ProgramConfigElement()
        obj.element_instance_tag = bits.read(4)
        obj.object_type = bits.read(2)
        obj.sampling_frequency_index = bits.read(4)

        num_front_channel_elements = bits.read(4)
        num_side_channel_elements = bits.read(4)
        num_back_channel_elements = bits.read(4)
        num_lfe_channel_elements = bits.read(2)
        num_assoc_data_elements = bits.read(3)
        num_valid_cc_elements = bits.read(4)

        mono_mixdown_present = bits.read(1)
        if mono_mixdown_present:
            obj.mono_mixdown_element_number = bits.read(4)

        stereo_mixdown_present = bits.read(1)
        if stereo_mixdown_present:
            obj.stereo_mixdown_element_number = bits.read(4)

        matrix_mixdown_idx_present = bits.read(1)
        if matrix_mixdown_idx_present:
            obj.matrix_mixdown = MatrixMixdown.decode(bits)

        for _ in range(num_front_channel_elements):
            obj.front_channel_elements.append(ChannelElement.decode(bits, True))

        for _ in range(num_side_channel_elements):
            obj.side_channel_elements.append(ChannelElement.decode(bits, True))

        for _ in range(num_back_channel_elements):
            obj.back_channel_elements.append(ChannelElement.decode(bits, True))

        for _ in range(num_lfe_channel_elements):
            obj.lfe_channel_elements.append(ChannelElement.decode(bits, False))

        for _ in range(num_assoc_data_elements):
            obj.assoc_data_elements.append(ChannelElement.decode(bits, False))

        for _ in range(num_valid_cc_elements):
            obj.valid_cc_elements.append(CCElement.decode(bits))

        bits.byte_align()
        comment_field_bytes = bits.read(8)
        if comment_field_bytes:
            obj.comment_field_data = bits.read_bytes(comment_field_bytes)
        return obj


sampling_frequency_table : list[int] = [ 96000,88200,64000,48000,44100,32000,24000,22050,16000,12000,11025,8000,7350,0,0 ]


@dataclass(eq=True, slots=True)
class Format:
    audio_object_type: int = 0
    channel_configuration: int | None = None
    sampling_frequency_index: int = 0
    sampling_frequency: int | None = None

    def decode_sampling_frequency(self, bits: BitReader) -> None:
        self.sampling_frequency_index = bits.read(4)
        if self.sampling_frequency_index != 0xf:
            self.sampling_frequency = None
        else:
            self.sampling_frequency = bits.read(24)


@dataclass(eq=True, slots=True)
class BSACExtension:
    num_of_sub_frames: int = 0
    layer_length: int = 0

    @classmethod
    def decode(cls, bits: BitReader) -> BSACExtension:
        obj = BSACExtension()
        obj.num_of_sub_frames = bits.read(5)
        obj.layer_length = bits.read(11)
        return obj


@dataclass(eq=True, slots=True)
class ERExtension:
    aac_section_data_resilience_flag: int = 0
    aac_scale_factor_data_resilience_flag: int = 0
    aac_spectral_data_resilience_flag: int = 0

    @classmethod
    def decode(cls, bits: BitReader) -> ERExtension:
        obj = ERExtension()
        obj.aac_section_data_resilience_flag = bits.read(1)
        obj.aac_scale_factor_data_resilience_flag = bits.read(1)
        obj.aac_spectral_data_resilience_flag = bits.read(1)
        return obj


@dataclass(eq=True, slots=True)
class GASpecificConfig:
    frame_length_flag: int = 0
    depends_on_core_coder: int = 0
    core_coder_delay: int | None = None
    extension_flag: int = 0
    program_config_elment: ProgramConfigElement | None = None
    layer_nr: int | None = None
    extension: BSACExtension | ERExtension | None = None
    extension_flag3: int | None = None

    @classmethod
    def decode(cls, bits: BitReader, format: Format) -> GASpecificConfig:
        obj = GASpecificConfig()
        obj.frame_length_flag = bits.read(1)
        obj.depends_on_core_coder = bits.read(1)
        if obj.depends_on_core_coder:
            obj.core_coder_delay = bits.read(14)
        obj.extension_flag = bits.read(1)
        if format.channel_configuration == 0:
            obj.program_config_elment = ProgramConfigElement.decode(bits)
        if format.audio_object_type in (6, 20):
            obj.layer_nr = bits.read(3)
        if obj.extension_flag:
            if format.audio_object_type == 22:
                obj.extension = BSACExtension.decode(bits)
            if format.audio_object_type in (17, 19, 20, 23):
                obj.extension = ERExtension.decode(bits)
            obj.extension_flag3 = bits.read(1)
        return obj


@dataclass(eq=True, slots=True)
class SBRHeaderExtra1:
    bs_freq_scale: int = 0
    bs_alter_scale: int = 0
    bs_noise_bands: int = 0
 
    @classmethod
    def decode(cls, bits: BitReader) -> SBRHeaderExtra1:
        obj = SBRHeaderExtra1()
        obj.bs_freq_scale = bits.read(2)
        obj.bs_alter_scale = bits.read(1)
        obj.bs_noise_bands = bits.read(2)
        return obj


@dataclass(eq=True, slots=True)
class SBRHeaderExtra2:
    bs_limiter_bands: int = 0
    bs_limiter_gains: int = 0
    bs_interpol_freq: int = 0
    bs_smoothing_mode: int = 0

    @classmethod
    def decode(cls, bits: BitReader) -> SBRHeaderExtra2:
        obj = SBRHeaderExtra2()
        obj.bs_limiter_bands = bits.read(2)
        obj.bs_limiter_gains = bits.read(2)
        obj.bs_interpol_freq = bits.read(1)
        obj.bs_smoothing_mode = bits.read(1)
        return obj


@dataclass(eq=True, slots=True)
class SBRHeader:
    bs_amp_res: int = 0
    bs_start_freq: int = 0
    bs_stop_freq: int = 0
    bs_xover_band: int = 0
    bs_header_extra_1: SBRHeaderExtra1 | None = None
    bs_header_extra_2: SBRHeaderExtra2 | None = None

    @classmethod
    def decode(cls, bits: BitReader) -> SBRHeader:
        obj = SBRHeader()
        obj.bs_amp_res = bits.read(1)
        obj.bs_start_freq = bits.read(4)
        obj.bs_stop_freq = bits.read(4)
        obj.bs_xover_band = bits.read(3)
        bs_reserved = bits.read(2)
        bs_header_extra_1 = bits.read(1)
        bs_header_extra_2 = bits.read(1)
        if bs_header_extra_1:
            obj.bs_header_extra_1 = SBRHeaderExtra1.decode(bits)
        if bs_header_extra_2:
            obj.bs_header_extra_2 = SBRHeaderExtra2.decode(bits)
        return obj


def eld_num_sbr_headers(channel_configuration: int) -> int:
    if channel_configuration in (1, 2):
        return 1
    elif channel_configuration == 3:
        return 2
    elif channel_configuration in (4, 5, 6):
        return 3
    elif channel_configuration == 7:
        return 4
    return 0


@dataclass(eq=True, slots=True)
class ELDSBRConfig:
    ld_sbr_sampling_rate: int = 0
    ld_sbr_crc_flag: int = 0
    sbr_headers: list[SBRHeader] = field(default_factory=list)

    @classmethod
    def decode(cls, bits: BitReader, channel_configuration: int) -> ELDSBRConfig:
        obj = ELDSBRConfig()
        obj.ld_sbr_sampling_rate = bits.read(1)
        obj.ld_sbr_crc_flag = bits.read(1)
        for _ in range(eld_num_sbr_headers(channel_configuration)):
            obj.sbr_headers.append(SBRHeader.decode(bits))
        return obj


@dataclass(eq=True, slots=True)
class ELDSpecificConfig(ERExtension):
    frame_length_flag: int = 0
    sbr_config: ELDSBRConfig | None = None
    extensions: list[tuple[int, bytes]] = field(default_factory=list)

    @classmethod
    def decode(cls, bits: BitReader, channel_configuration: int) -> ELDSpecificConfig:
        obj = ELDSpecificConfig()
        obj.frame_length_flag = bits.read(1)
        obj.aac_section_data_resilience_flag = bits.read(1)
        obj.aac_scale_factor_data_resilience_flag = bits.read(1)
        obj.aac_spectral_data_resilience_flag = bits.read(1)
        ld_sbr_present_flag = bits.read(1)
        if ld_sbr_present_flag:
            obj.sbr_config = ELDSBRConfig.decode(bits, channel_configuration)
        while True:
            eld_ext_type = bits.read(4)
            if eld_ext_type == 0: break
            eld_ext_len = bits.read(4)
            if eld_ext_len == 0xf:
                eld_ext_len_add = bits.read(8)
                eld_ext_len += eld_ext_len_add
                if eld_ext_len_add == 0xff:
                    eld_ext_len += bits.read(16)
            ext_bytes = bits.read_bytes(eld_ext_len)
            obj.extensions.append((eld_ext_type, ext_bytes))
        return obj


def decode_audio_object_type(bits: BitReader) -> int:
    aot = bits.read(5)
    if aot == 31:
        aot = 32 + bits.read(6)
    return aot


@dataclass(eq=True, slots=True)
class AudioSpecificConfig:
    format: Format = field(default_factory=Format)
    extension_format: Format | None = None
    sbr_present_flag: int = -1
    ps_present_flag: int = -1
    ep_config: int | None = None
    codec_specific_config: GASpecificConfig | ELDSpecificConfig | None = None

    @classmethod
    def decode(cls, bits: BitReader, bits_to_decode: int=0) -> AudioSpecificConfig:
        # Since PCE needs byte_align() relative to the beginning of ASC, we need new BitStream
        bits1 = BitReader(bits.tobytes())
        obj = AudioSpecificConfig()
        obj.format.audio_object_type = decode_audio_object_type(bits1)
        obj.format.decode_sampling_frequency(bits1)
        obj.format.channel_configuration = bits1.read(4)

        if obj.format.audio_object_type in (5, 29):
            obj.extension_format = Format(audio_object_type=5)
            obj.sbr_present_flag = 1
            if obj.format.audio_object_type == 29:
                obj.ps_present_flag = 1
            obj.extension_format.decode_sampling_frequency(bits1)
            obj.format.audio_object_type = decode_audio_object_type(bits1)
            if obj.format.audio_object_type == 22:
                obj.extension_format.channel_configuration = bits1.read(4)
        if obj.format.audio_object_type in (1, 2, 3, 4, 6, 7, 17, 19, 20, 21, 22, 23):
            obj.codec_specific_config = GASpecificConfig.decode(bits1, obj.format)
        elif obj.format.audio_object_type == 39:
            obj.codec_specific_config = ELDSpecificConfig.decode(bits1, obj.format.channel_configuration)
        else:
            raise NotImplementedError(f"unsupported AOT: {obj.format.audio_object_type}")
        if obj.format.audio_object_type in (17, 19, 20, 21, 22, 23, 24, 25, 26, 27, 39):
            obj.ep_config = bits1.read(2)
            if obj.ep_config in (2, 3):
                raise NotImplementedError(f"error protection is unsupported: ep_config: {obj.ep_config}")
        if obj.sbr_present_flag == -1 and bits_to_decode - bits1.tell() >= 16:
            if bits1.read(11) == 0x2b7:
                obj.extension_format = Format()
                obj.extension_format.audio_object_type = decode_audio_object_type(bits1)
                if obj.extension_format.audio_object_type == 5:
                    obj.sbr_present_flag = bits1.read(1)
                    if obj.sbr_present_flag:
                        obj.extension_format.decode_sampling_frequency(bits1)
                        if bits_to_decode - bits1.tell() >= 12:
                            if bits1.read(11) == 0x548:
                                obj.ps_present_flag = 1
                if obj.extension_format.audio_object_type == 22:
                    obj.sbr_present_flag = bits1.read(1)
                    if obj.sbr_present_flag:
                        obj.extension_format.decode_sampling_frequency(bits1)
                    obj.extension_format.channel_configuration = bits1.read(4)
        # consume the original BitStream
        if bits_to_decode:
            bits.skip(bits_to_decode)
        else:
            bits.skip(bits1.tell())
        return obj
    
    @property
    def num_samples_per_frame(self) -> int:
        if self.format.audio_object_type in (1, 2, 3, 4, 6, 7, 17, 19, 20, 21, 22):
            return [1024, 960][self.codec_specific_config.frame_length_flag]
        elif self.format.audio_object_type in (23, 39):
            return [512, 480][self.codec_specific_config.frame_length_flag]
