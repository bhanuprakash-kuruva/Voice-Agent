
import sounddevice as sd
import numpy as np
from scipy.io.wavfile import write
from faster_whisper import WhisperModel

SAMPLE_RATE = 16000

model = WhisperModel(
    "small",
    device="cpu",
    compute_type="int8"
)


def record_audio(filename="mic_input.wav", duration=5):

    print("\n🎤 Speak now...")

    recording = sd.rec(
        int(duration * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32"
    )

    sd.wait()

    write(filename, SAMPLE_RATE, recording)

    return filename


def speech_to_text(audio_file):

    segments, _ = model.transcribe(
        audio_file,
        beam_size=5,
        vad_filter=True
    )

    text = ""

    for segment in segments:
        text += segment.text

    return text.strip()