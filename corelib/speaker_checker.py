# python
# File: `corelib/speaker_voice_recorder.py`

import time
import wave
from pathlib import Path

import numpy as np
import pyaudio


class DeviceSpeaker:
    def __init__(self, sample_rate=44100):
        self.sample_rate = sample_rate
        self.audio = pyaudio.PyAudio()

    def record_and_save(self, duration, output_path):
        """Record from mic and save WAV to output_path (Path)."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=1024
        )

        frames = []
        for _ in range(int(self.sample_rate / 1024 * duration)):
            data = stream.read(1024, exception_on_overflow=False)
            frames.append(data)

        stream.stop_stream()
        stream.close()

        with wave.open(str(output_path), 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(b''.join(frames))

        audio_array = np.frombuffer(b''.join(frames), dtype=np.int16).astype(np.float32) / 32768.0
        return audio_array

    def analyze_recorded_file(self, recorded_file_path, threshold=0.01):
        """Analyze WAV file and return dict with pass/fail info."""
        with wave.open(str(recorded_file_path), 'rb') as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            sample_rate = wav_file.getframerate()

        audio_data = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
        max_level = float(np.max(np.abs(audio_data))) if audio_data.size else 0.0
        rms_level = float(np.sqrt(np.mean(audio_data ** 2))) if audio_data.size else 0.0
        passed = max_level > threshold

        return {
            'max_level': max_level,
            'rms_level': rms_level,
            'passed': passed,
            'audio_data': audio_data,
            'sample_rate': sample_rate
        }

    def cleanup(self):
        try:
            self.audio.terminate()
        except Exception:
            pass


def _project_temp_audio_dir():
    # temp_audio folder next to project root (two levels up from corelib)
    return Path(__file__).resolve().parent.parent / 'temp_audio'


def get_latest_temp_audio_file():
    """Return Path to latest .wav in `temp_audio` or None."""
    d = _project_temp_audio_dir()
    if not d.exists():
        return None
    wavs = sorted(d.glob('*.wav'), key=lambda p: p.stat().st_mtime, reverse=True)
    return wavs[0] if wavs else None


def run_speaker_test(duration=10, threshold=0.005, prepare_seconds=3):
    """
    Record, analyze and return True/False.
    - On success: deletes temp WAV and returns True.
    - On failure: keeps WAV in `temp_audio` and returns False.
    """
    tester = DeviceSpeaker()
    temp_dir = _project_temp_audio_dir()
    temp_dir.mkdir(parents=True, exist_ok=True)

    # for i in range(prepare_seconds, 0, -1):
    #     time.sleep(1)

    ts = int(time.time())
    output_file = temp_dir / f"device_record_{ts}.wav"

    try:
        tester.record_and_save(duration, output_file)
        result = tester.analyze_recorded_file(output_file, threshold=threshold)

        if result['passed']:
            # remove temp file for passed tests
            try:
                output_file.unlink()
            except Exception:
                pass
            return True
        else:
            # keep the wav for later collection
            return False

    except Exception:
        # On unexpected exceptions keep file if exists for debugging
        return False

    finally:
        tester.cleanup()