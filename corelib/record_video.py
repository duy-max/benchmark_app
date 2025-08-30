import os
import re
import shutil
import subprocess
import threading
import time


# ==============================================================================
# ADB-based recorder with FIXED ffmpeg handling and file verification
# ============================================================================== 

class _AdbRecorder:
    def __init__(self, video_size: str, bit_rate: str, device_id: str = None):
        self.video_size = video_size
        self.bit_rate = bit_rate
        self.device_id = device_id
        self.is_recording = False
        self.recording_thread = None
        self.video_chunks_on_device = []
        self.temp_dir_local = os.path.abspath("temp_video_chunks_adb")
        os.makedirs(self.temp_dir_local, exist_ok=True)

    def _find_screenrecord_pid(self):
        """Try to find screenrecord pid on device. Return pid string or None."""
        command = "adb shell ps -A | findstr screenrecord"
        try:
            for _ in range(5):
                result = subprocess.run(command, shell=True, capture_output=True, text=True)
                stdout = (result.stdout or "") + (result.stderr or "")
                if stdout and 'screenrecord' in stdout:
                    match = re.search(r'\S+\s+(\d+)', stdout)
                    if match:
                        pid = match.group(1)
                        print(f"INFO (ADB Recorder): Tìm thấy PID của screenrecord là: {pid}")
                        return pid
                time.sleep(0.5)
        except Exception as e:
            print(f"ERROR (ADB Recorder): Không thể tìm thấy PID của screenrecord. Lỗi: {e}")
        return None

    def _graceful_stop_on_device(self, pid: str):
        if not pid:
            return
        print(f"INFO (ADB Recorder): Gửi tín hiệu dừng trực tiếp đến PID {pid} trên thiết bị...")
        cmd = f"adb shell kill -2 {pid}"
        subprocess.run(cmd, shell=True, capture_output=True)
        time.sleep(1)

    def _recording_loop(self):
        print("INFO (ADB Recorder): Luồng ghi hình 'Direct Hit' đã bắt đầu.")
        current_pid = None
        while self.is_recording:
            try:
                chunk_path = f"/sdcard/adb_chunk_{int(time.time())}.mp4"
                self.video_chunks_on_device.append(chunk_path)
                adb_command = (
                    f"adb shell screenrecord --size {self.video_size} "
                    f"--bit-rate {self.bit_rate} {chunk_path}"
                )

                # start screenrecord in background
                subprocess.Popen(adb_command, shell=True)

                current_pid = self._find_screenrecord_pid()
                if not current_pid:
                    print("ERROR (ADB Recorder): Không khởi động được tiến trình quay phim trên thiết bị.")
                    self.is_recording = False
                    break

                # record loop: allow manual stop or timeout (178s ~ 3 minutes)
                for _ in range(178):
                    if not self.is_recording:
                        break
                    time.sleep(1)

                self._graceful_stop_on_device(current_pid)
                current_pid = None

            except Exception as e:
                print(f"ERROR (ADB Recorder): Lỗi trong luồng ghi hình: {e}")
                self.is_recording = False

        if current_pid:
            self._graceful_stop_on_device(current_pid)

        print("INFO (ADB Recorder): Luồng ghi hình đã kết thúc.")

    def start(self):
        if self.is_recording:
            return
        self.is_recording = True
        self.video_chunks_on_device = []
        self.recording_thread = threading.Thread(target=self._recording_loop, daemon=True)
        self.recording_thread.start()

    def _pull_chunks(self):
        local_chunks = []
        for device_path in self.video_chunks_on_device:
            local_path = os.path.join(self.temp_dir_local, os.path.basename(device_path))
            pull_command = ["adb", "pull", device_path, local_path]
            print(f"  - Pulling: {device_path}")
            try:
                subprocess.run(pull_command, check=True, capture_output=True, timeout=60)
                if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                    local_chunks.append(local_path)
                    print(f"    ✅ Successfully pulled: {local_path} ({os.path.getsize(local_path)} bytes)")
                else:
                    print(f"    ❌ Pulled file empty or not found: {local_path}")
            except Exception as e:
                print(f"WARNING (ADB Recorder): Không thể pull file {device_path}. Lỗi: {e}")
        return local_chunks

    def _check_ffmpeg_available(self):
        """Check if ffmpeg is available in PATH"""
        ffmpeg_exe = shutil.which("ffmpeg")
        if ffmpeg_exe:
            print(f"INFO (ADB Recorder): Found ffmpeg at: {ffmpeg_exe}")
            return True
        else:
            print("WARNING (ADB Recorder): ffmpeg not found in PATH")
            return False

    def _stitch_with_ffmpeg(self, local_chunks, output_filename):
        """Stitch chunks using ffmpeg with proper error checking"""
        if not self._check_ffmpeg_available():
            return False
            
        list_file_path = os.path.join(self.temp_dir_local, "ffmpeg_list.txt")
        
        try:
            # Create concat file list
            with open(list_file_path, "w", encoding="utf-8") as f:
                for chunk_file in local_chunks:
                    # Use forward slashes and absolute paths
                    abs_path = os.path.abspath(chunk_file).replace('\\', '/')
                    f.write(f"file '{abs_path}'\n")
            
            print(f"DEBUG (ADB Recorder): Created ffmpeg list file: {list_file_path}")
            
            # Build ffmpeg command
            ffmpeg_cmd = [
                "ffmpeg", "-y", "-f", "concat", "-safe", "0", 
                "-i", list_file_path, "-c", "copy", output_filename
            ]
            
            print(f"DEBUG (ADB Recorder): Running ffmpeg command: {' '.join(ffmpeg_cmd)}")
            
            # Run ffmpeg with proper error checking
            proc = subprocess.run(
                ffmpeg_cmd, 
                check=False, 
                capture_output=True, 
                text=True, 
                timeout=300
            )
            
            if proc.returncode == 0:
                # Verify output file was created and has content
                if os.path.exists(output_filename) and os.path.getsize(output_filename) > 0:
                    file_size = os.path.getsize(output_filename)
                    print(f"✅ FFMPEG SUCCESS: Video stitched successfully ({file_size} bytes)")
                    return True
                else:
                    print(f"❌ FFMPEG ERROR: Output file not created or empty: {output_filename}")
                    return False
            else:
                print(f"❌ FFMPEG ERROR: Process failed with return code {proc.returncode}")
                print(f"STDERR: {proc.stderr}")
                print(f"STDOUT: {proc.stdout}")
                return False
                
        except subprocess.TimeoutExpired:
            print("❌ FFMPEG ERROR: Process timed out")
            return False
        except Exception as e:
            print(f"❌ FFMPEG ERROR: Exception occurred: {e}")
            return False
        finally:
            # Clean up list file
            try:
                if os.path.exists(list_file_path):
                    os.remove(list_file_path)
            except Exception:
                pass

    def _handle_single_chunk(self, local_chunks, output_filename):
        """Handle case where we have only one chunk - just move it"""
        try:
            single_chunk = local_chunks[0]
            print(f"INFO (ADB Recorder): Single chunk detected, moving {single_chunk} to {output_filename}")
            
            # Create output directory if it doesn't exist
            output_dir = os.path.dirname(output_filename)
            if output_dir and not os.path.exists(output_dir):
                os.makedirs(output_dir, exist_ok=True)
            
            shutil.move(single_chunk, output_filename)
            
            if os.path.exists(output_filename) and os.path.getsize(output_filename) > 0:
                file_size = os.path.getsize(output_filename)
                print(f"✅ SINGLE CHUNK SUCCESS: Moved to {output_filename} ({file_size} bytes)")
                return True
            else:
                print(f"❌ SINGLE CHUNK ERROR: Failed to move chunk to {output_filename}")
                return False
                
        except Exception as e:
            print(f"❌ SINGLE CHUNK ERROR: {e}")
            return False

    def _cleanup_device_and_local(self, local_chunks):
        """Clean up local chunks and device files"""
        print("PROCESS (ADB Recorder): Dọn dẹp các file tạm...")
        
        # Remove local chunks
        for chunk_file in local_chunks:
            try:
                if os.path.exists(chunk_file):
                    os.remove(chunk_file)
                    print(f"  - Removed local chunk: {chunk_file}")
            except Exception as e:
                print(f"  - Failed to remove {chunk_file}: {e}")
        
        # Remove temp directory if empty
        try:
            if os.path.isdir(self.temp_dir_local):
                remaining_files = os.listdir(self.temp_dir_local)
                if not remaining_files:
                    os.rmdir(self.temp_dir_local)
                    print(f"  - Removed temp directory: {self.temp_dir_local}")
                else:
                    print(f"  - Temp directory not empty, leaving: {remaining_files}")
        except Exception as e:
            print(f"  - Failed to remove temp directory: {e}")
        
        # Remove device chunks
        for device_path in self.video_chunks_on_device:
            try:
                subprocess.run(["adb", "shell", "rm", device_path], capture_output=True, timeout=10)
                print(f"  - Removed device chunk: {device_path}")
            except Exception as e:
                print(f"  - Failed to remove device chunk {device_path}: {e}")

    def _pull_and_stitch(self, output_filename: str):
        """Main processing method with improved error handling"""
        if not self.video_chunks_on_device:
            print("ERROR (ADB Recorder): Không có đoạn video nào được ghi lại.")
            return False

        print(f"PROCESS (ADB Recorder): Tìm thấy {len(self.video_chunks_on_device)} đoạn video để xử lý.")
        
        # Step 1: Pull chunks from device
        local_chunks = self._pull_chunks()
        if not local_chunks:
            print("ERROR (ADB Recorder): Không thể tải về bất kỳ đoạn video nào.")
            return False

        success = False
        
        try:
            # Step 2: Process chunks based on count
            if len(local_chunks) == 1:
                # Single chunk - just move it
                success = self._handle_single_chunk(local_chunks, output_filename)
            else:
                # Multiple chunks - need ffmpeg
                if self._check_ffmpeg_available():
                    success = self._stitch_with_ffmpeg(local_chunks, output_filename)
                else:
                    print("ERROR (ADB Recorder): Multiple chunks but ffmpeg not available!")
                    print(f"  - Found {len(local_chunks)} chunks in {self.temp_dir_local}")
                    print("  - Install ffmpeg or use single chunk recording")
                    success = False
            
            # Step 3: Clean up only if successful
            if success:
                self._cleanup_device_and_local(local_chunks)
                print(f"✅ SUCCESS (ADB Recorder): Video đã được lưu thành công tại: {output_filename}")
            else:
                print(f"❌ FAILED (ADB Recorder): Video processing failed for: {output_filename}")
                print(f"  - Local chunks preserved in: {self.temp_dir_local}")
                
        except Exception as e:
            print(f"ERROR (ADB Recorder): Exception in processing: {e}")
            success = False
        
        return success

    def stop(self, output_filename: str):
        """Stop recording and process video"""
        if self.is_recording:
            print("COMMAND (ADB Recorder): Yêu cầu dừng quay...")
            self.is_recording = False
            if self.recording_thread:
                self.recording_thread.join(timeout=10)
        
        return self._pull_and_stitch(output_filename)


# Global instance
_adb_recorder_instance = None

# Public API
def start_recording(device_id: str = None, video_size: str = "1920x1080", bit_rate: str = "20000000"):
    global _adb_recorder_instance
    if _adb_recorder_instance:
        print("WARNING (ADB Recorder): Recording already in progress")
        return
    rec = _AdbRecorder(video_size=video_size, bit_rate=bit_rate, device_id=device_id)
    rec.start()
    _adb_recorder_instance = rec
    # _adb_recorder_instance.start()

def stop_recording(output_filename: str = "final_video.mp4"):
    global _adb_recorder_instance
    if not _adb_recorder_instance:
        print("WARNING (ADB Recorder): stop_recording called but recorder not active.")
        return False
    
    try:
        success = _adb_recorder_instance.stop(output_filename)
        return success
    finally:
        _adb_recorder_instance = None