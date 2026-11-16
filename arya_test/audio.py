"""Independent PCM/Opus transport and deterministic spoken test inputs."""
import asyncio
import ctypes as C
import ctypes.util


class Opus:
    def __init__(self, rate, encode=False):
        self.rate, self.encode_mode = rate, encode
        self.lib = C.CDLL(ctypes.util.find_library('opus') or 'libopus.so.0')
        for name, restype, args in [
            ('opus_encoder_create', C.c_void_p, [C.c_int, C.c_int, C.c_int, C.POINTER(C.c_int)]),
            ('opus_decoder_create', C.c_void_p, [C.c_int, C.c_int, C.POINTER(C.c_int)]),
            ('opus_encoder_ctl', C.c_int, [C.c_void_p, C.c_int]),
            ('opus_encoder_destroy', None, [C.c_void_p]),
            ('opus_decoder_destroy', None, [C.c_void_p]),
            ('opus_encode', C.c_int, [C.c_void_p, C.c_void_p, C.c_int, C.c_void_p, C.c_int]),
            ('opus_decode', C.c_int, [C.c_void_p, C.c_void_p, C.c_int, C.c_void_p, C.c_int, C.c_int]),
            ('opus_packet_get_nb_channels', C.c_int, [C.c_void_p]),
            ('opus_packet_get_nb_samples', C.c_int, [C.c_void_p, C.c_int, C.c_int]),
        ]:
            fn = getattr(self.lib, name)
            fn.restype, fn.argtypes = restype, args
        error = C.c_int()
        if encode:
            self.ptr = self.lib.opus_encoder_create(rate, 1, 2048, C.byref(error))
        else:
            self.ptr = self.lib.opus_decoder_create(rate, 1, C.byref(error))
        assert error.value == 0 and self.ptr, 'Opus initialization failed'
        if encode:
            for request, value in [(4002, 24000), (4010, 5), (4016, 0)]:
                assert self.lib.opus_encoder_ctl(self.ptr, request, C.c_int(value)) == 0

    def encode(self, pcm):
        assert len(pcm) == self.rate // 50 * 2
        output = C.create_string_buffer(4000)
        n = self.lib.opus_encode(self.ptr, pcm, self.rate // 50, output, 4000)
        assert n > 0, 'Opus encode failed'
        return output.raw[:n]

    def decode(self, packet):
        assert packet, 'empty Opus packet'
        assert self.lib.opus_packet_get_nb_channels(packet) == 1, 'reply is not mono'
        assert self.lib.opus_packet_get_nb_samples(packet, len(packet), self.rate) == self.rate // 50, 'reply packet is not 20ms'
        output = C.create_string_buffer(self.rate // 50 * 2)
        n = self.lib.opus_decode(self.ptr, packet, len(packet), output, self.rate // 50, 0)
        assert n == self.rate // 50, 'invalid Opus reply'
        return output.raw[:n * 2]

    def close(self):
        if self.ptr:
            getattr(self.lib, 'opus_encoder_destroy' if self.encode_mode else 'opus_decoder_destroy')(self.ptr)
            self.ptr = None


async def speech(text, rate=16000):
    # Fixed synthetic microphone fixture; no network TTS or server implementation used.
    p = await asyncio.create_subprocess_exec('espeak-ng', '-v', 'en-us', '-s', '145', '--stdout', text,
                                             stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    wav, _ = await p.communicate()
    assert p.returncode == 0, 'espeak-ng failed'
    p = await asyncio.create_subprocess_exec('ffmpeg', '-v', 'error', '-i', 'pipe:0', '-f', 's16le',
                                             '-ac', '1', '-ar', str(rate), 'pipe:1',
                                             stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                             stderr=asyncio.subprocess.PIPE)
    pcm, _ = await p.communicate(wav)
    assert p.returncode == 0 and pcm, 'PCM fixture conversion failed'
    return pcm
