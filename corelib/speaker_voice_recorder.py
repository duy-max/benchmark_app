import time
import wave

import numpy as np
import pyaudio


class DeviceSpeaker:
    def __init__(self, sample_rate=44100):
        # Setup audio recording
        self.sample_rate = sample_rate
        self.audio = pyaudio.PyAudio()
        print("✅ Audio recorder initialized")

    def record_and_save(self, duration, output_filename):
        """Ghi âm từ mic và lưu thành WAV"""
        print(f"🎤 Recording for {duration} seconds → {output_filename}")

        stream = self.audio.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=1024
        )

        frames = []
        for _ in range(int(self.sample_rate / 1024 * duration)):
            data = stream.read(1024)
            frames.append(data)

        stream.stop_stream()
        stream.close()

        with wave.open(output_filename, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(self.sample_rate)
            wav_file.writeframes(b''.join(frames))

        print(f"✅ Saved recording as {output_filename}")

        audio_array = np.frombuffer(b''.join(frames), dtype=np.int16)
        audio_array = audio_array.astype(np.float32) / 32768.0
        return audio_array

    def analyze_recorded_file(self, recorded_file_path, threshold=0.01):
        """Phân tích file WAV"""
        print(f"📊 Analyzing {recorded_file_path}...")

        with wave.open(recorded_file_path, 'rb') as wav_file:
            frames = wav_file.readframes(wav_file.getnframes())
            sample_rate = wav_file.getframerate()

        audio_data = np.frombuffer(frames, dtype=np.int16)
        audio_data = audio_data.astype(np.float32) / 32768.0

        max_level = np.max(np.abs(audio_data))
        rms_level = np.sqrt(np.mean(audio_data ** 2))
        passed = max_level > threshold

        print(f"   Max Level: {max_level:.4f}")
        print(f"   RMS Level: {rms_level:.4f}")
        print(f"   Threshold: {threshold}")
        print(f"   Status: {'✅ PASS' if passed else '❌ FAIL'}")

        return {
            'max_level': max_level,
            'rms_level': rms_level,
            'passed': passed,
            'audio_data': audio_data,
            'sample_rate': sample_rate
        }

    def cleanup(self):
        """Cleanup"""
        try:
            self.audio.terminate()
            print("🧹 Cleanup completed")
        except:
            pass


def run_speaker_test():
    tester = DeviceSpeaker()
    prepare_seconds = 5
    print(f"⏳ Get ready! Recording will start in {prepare_seconds} seconds...")
    for i in range(prepare_seconds, 0, -1):
        print(f"   Starting in {i}...", end="\r")
        time.sleep(1)
    print("\n🔔 Starting recording now!")
    output_file = f"device_record_{int(time.time())}.wav"
    record_duration = 10  # seconds
    audio_data = tester.record_and_save(record_duration, output_file)

    # Phân tích file vừa ghi âm
    result = tester.analyze_recorded_file(output_file, threshold=0.005)

    print(f"\n🏁 Test completed! Result: {'PASS' if result['passed'] else 'FAIL'}")

    tester.cleanup()


if __name__ == "__main__":
    print("🎵 Device Speaker Test")
    print("=" * 30)
    run_speaker_test()
