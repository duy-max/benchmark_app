import argparse
import shutil
import time
from datetime import datetime
from pathlib import Path

from corelib.app_handler import AppHandler
from corelib.camera_checker import get_temp_screenshot_files
from corelib.logger import Logger
from corelib.record_video import start_recording, stop_recording
from corelib.speaker_checker import get_latest_temp_audio_file
from lib.dashboard import Dashboard


def setup_run_logger():
    """
    Tạo logger riêng cho run session với file trong logs_run/
    """
    # create logs_run dir
    project_root = Path(__file__).resolve().parent
    logs_run_dir = project_root / 'logs_run'
    logs_run_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    log_filename = f"run_session_{timestamp}.log"
    run_logger = Logger(name=f"run_session_{timestamp}", filename=log_filename, dir_name="logs_run")
    print(f"📝 Run session log: {run_logger.log_path}")
    run_logger.info(f"=== RUN SESSION STARTED at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    return run_logger


def log_and_print(run_logger, message, level="info"):
    """
    Helper function to log and print
    """
    print(message)  # Console output
    # File logging
    if level == "info":
        run_logger.info(message)
    elif level == "warning":
        run_logger.warning(message)
    elif level == "error":
        run_logger.error(message)


def get_full_collected_tag(collected_files, tag):
    """
    Extract full tag from collected files
    """
    if not collected_files:
        return tag

    # find the first file to extract full tag
    for file_type, filepath in collected_files.items():
        if filepath and ('logcat' in file_type or 'dmesg' in file_type):
            filename = Path(filepath).name
            # Extract tag from filename: logcat_device_tag_timestamp.txt
            if '_' in filename:
                parts = filename.replace('.txt', '').split('_')
                if len(parts) >= 3:
                    # Reconstruct full tag from filename
                    full_tag = '_'.join(parts[1:])  # remove prefix (logcat/dmesg)
                    return full_tag

    return tag


def _check_resumed_activity(dashboard):
    """Check if our app is the currently resumed/foreground activity"""
    try:
        cmd = ["shell", "dumpsys", "activity", "activities"]
        rc, out, err = dashboard.app.run_adb(cmd = cmd, timeout=10)

        if rc != 0:
            return False, "Failed to get activity dump"

        output = out
        # Look for mResumedActivity line
        for line in output.splitlines():
            if "mResumedActivity:" in line:
                if "com.innova.benchmark" in line:
                    return True, f"App is in foreground: {line.strip()}"
                else:
                    return False, f"App not in foreground - resumed activity: {line.strip()}"

        return False, "Could not determine resumed activity"

    except Exception as ex:
        return False, f"Failed to check resumed activity: {ex}"

def _check_driver(dashboard):
    if not dashboard.app.driver:
        return False, "Driver is None - session may be terminated"
    return True, None

def _check_session(dashboard):
    try:
        if not dashboard.app.driver.session_id:
            return False, "No active session ID"
    except Exception as ex:
        return False, f"Session check failed: {ex}"
    return True, None

def _check_process(dashboard):
    try:
        cmd = ["shell", "pidof", "com.innova.benchmark"]
        rc, out, err = dashboard.app.run_adb(cmd = cmd, timeout=5)
        if rc != 0 or not out.strip():
            return False, "App process not running (killed externally)"
    except Exception:
        pass
    return True, None

def check_app_health(dashboard):
    """Run multiple health checks on the app"""
    for check in (_check_driver, _check_session, _check_process, _check_resumed_activity):
        ok, reason = check(dashboard)
        if not ok:
            return False, reason
    return True, "App is healthy"

def classify_error_type(exception_str):
    """
    Phân loại loại lỗi để xử lý thống kê phù hợp
    Returns: ('crash_type', 'description')
    """
    exception_lower = str(exception_str).lower()

    if 'instrumentation process is not running' in exception_lower:
        return 'uiautomator_crash', 'UiAutomator2 instrumentation crashed'
    elif "am crash detected" in exception_lower or "am_crash" in exception_lower:
        return "app_crash", "App process crashed (am_crash)"
    elif 'cannot be proxied' in exception_lower and 'instrumentation' in exception_lower:
        return 'uiautomator_crash', 'UiAutomator2 proxy failed - instrumentation issue'
    elif 'socket hang up' in exception_lower:
        return 'network_crash', 'Network/Socket connection lost'
    elif 'could not proxy command' in exception_lower:
        return 'proxy_crash', 'Command proxy failed'
    elif 'session' in exception_lower and ('deleted' in exception_lower or 'not found' in exception_lower):
        return 'session_crash', 'Driver session terminated'
    else:
        return 'unknown_crash', f'Unknown error: {str(exception_str)[:100]}'

def restart_app_after_crash(dashboard, run_logger, crash_type, run_idx):
    """
    Restart app sau khi crash, với logic khác nhau tùy crash type
    Returns: (success, error_message)
    """
    try:
        if crash_type == 'uiautomator_crash':
            log_and_print(run_logger, "UiAutomator crashed - performing thorough restart")
            # Force kill instrumentation
            try:
                cmd_kill_inst = ["shell", "pkill", "-f", "uiautomator"]
                dashboard.app.run_adb(cmd = cmd_kill_inst, timeout=10)
                log_and_print(run_logger, "Killed uiautomator processes")
                time.sleep(2)
            except Exception:
                pass

        # Standard restart sequence
        dashboard.app.quit_all("com.innova.benchmark")
        time.sleep(3)
        dashboard.app.start_app()
        time.sleep(3)

        # Verify restart by launching explicitly
        try:
            cmd_launch = ["shell", "am", "start", "-n", "com.innova.benchmark/.views.activities.MainActivity"]
            dashboard.app.run_adb(cmd = cmd_launch, timeout=10)
            log_and_print(run_logger, "Explicitly launched app via adb")
            time.sleep(3)
        except Exception:
            pass

        log_and_print(run_logger, "✓ App restart completed")
        return True, None

    except Exception as restart_ex:
        error_msg = f"App restart failed: {restart_ex}"
        log_and_print(run_logger, error_msg, "error")
        return False, error_msg


def _stop_and_save_video(step_name, crash_type, run_idx, logs_dir, run_logger, video_started):
    video_stopped = False
    try:
        if video_started:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            video_name = f"VIDEO_{crash_type.upper()}_{step_name}_run{run_idx}_{ts}.mp4"
            video_path = logs_dir / video_name
            stop_recording(str(video_path))
            video_stopped = True
            log_and_print(run_logger, f"📹 Crash video saved: {str(video_path)}")
    except Exception as ex:
        log_and_print(run_logger, f"Failed to stop/save crash video: {ex}", "warning")
    return video_stopped


def _collect_diagnostics(dashboard, run_logger, step_name, crash_type, run_idx, logs_dir):
    collected = {}
    full_tag = None
    try:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        tag = f"run{run_idx}_{step_name}_{crash_type}_{ts}"
        collected = dashboard.app.collect_on_failure(
            reason=f"{crash_type} in step {step_name}",
            output_dir=logs_dir,
            tag=tag
        )
        full_tag = get_full_collected_tag(collected, tag)
        log_and_print(run_logger, f"Collected {crash_type} crash logs: {full_tag}")
        return True, collected, full_tag
    except Exception as ex:
        log_and_print(run_logger, f"Failed to collect crash logs: {ex}", "error")
        return False, collected, full_tag


def _collect_temp_audio(run_logger, crash_type, step_name, run_idx, logs_dir):
    try:
        temp_audio_latest = get_latest_temp_audio_file()
        if temp_audio_latest and temp_audio_latest.exists():
            ts2 = datetime.now().strftime('%Y%m%d_%H%M%S')
            audio_name = f"AUDIO_{crash_type.upper()}_{step_name}_run{run_idx}_{ts2}.wav"
            audio_dest = logs_dir / audio_name
            shutil.copy2(temp_audio_latest, audio_dest)
            log_and_print(run_logger, f"🔊 Collected failed audio: {audio_dest}")
            try:
                temp_audio_latest.unlink()
                log_and_print(run_logger, f"Removed temp audio: {temp_audio_latest}")
            except Exception as rm_ex:
                log_and_print(run_logger, f"Failed to remove temp audio {temp_audio_latest}: {rm_ex}", "warning")
    except Exception as audio_ex:
        log_and_print(run_logger, f"Failed to collect temp audio: {audio_ex}", "warning")


def _collect_temp_screenshots(run_logger, crash_type, step_name, run_idx, logs_dir):
    try:
        temp_screens = get_temp_screenshot_files()
        if not temp_screens:
            return

        # Prefer to collect matching captured + preview pair if present
        captured = next((p for p in temp_screens if p.name.lower().startswith("captured_")), None)
        to_copy = []
        if captured:
            ts_name = captured.name.replace("captured_", "").replace(".png", "")
            preview = captured.parent / f"preview_{ts_name}.png"
            if preview.exists():
                to_copy = [preview, captured]
            else:
                to_copy = [captured]
        else:
            # fallback: take up to two newest screenshots
            to_copy = temp_screens[:2]

        for idx, temp_shot in enumerate(to_copy, start=1):
            try:
                lower = temp_shot.name.lower()
                if lower.startswith("preview_"):
                    role = "PREVIEW"
                elif lower.startswith("captured_"):
                    role = "CAPTURED"
                else:
                    role = "SCREENSHOT"

                ts2 = datetime.now().strftime('%Y%m%d_%H%M%S')
                shot_name = f"SCREEN_{role}_{crash_type.upper()}_{step_name}_run{run_idx}_{idx}_{ts2}.png"
                shot_dest = logs_dir / shot_name
                shutil.copy2(temp_shot, shot_dest)
                log_and_print(run_logger, f"🖼️  Collected failed screenshot: {shot_dest}")

                try:
                    temp_shot.unlink()
                    log_and_print(run_logger, f"Removed temp screenshot: {temp_shot}")
                except Exception as rm_ex:
                    log_and_print(run_logger, f"Failed to remove temp screenshot {temp_shot}: {rm_ex}", "warning")

            except Exception as copy_ex:
                log_and_print(run_logger, f"Failed to copy temp screenshot {temp_shot}: {copy_ex}", "warning")

    except Exception as ex:
        log_and_print(run_logger, f"Screenshot collection failed: {ex}", "warning")


def handle_step_crash(dashboard, run_logger, step_name, exception, run_idx, video_started, logs_dir):
    """
    Refactored handler: log, stop/save video, collect diagnostics, collect temp audio/screenshots,
    restart and return the same tuple as before.
    """
    crash_type, crash_desc = classify_error_type(exception)
    log_and_print(run_logger, f"ERROR in {step_name}: {exception}", "error")
    log_and_print(run_logger, f"Crash type: {crash_type} - {crash_desc}")
    dashboard.logger.exception(f"Exception in step {step_name}: {exception}")

    # Stop and save video if started
    video_stopped = _stop_and_save_video(step_name, crash_type, run_idx, logs_dir, run_logger, video_started)

    # Collect diagnostics (logcat, dmesg, etc.)
    diagnostics_collected, collected_map, collected_tag = _collect_diagnostics(
        dashboard, run_logger, step_name, crash_type, run_idx, logs_dir
    )

    # Collect temp audio left by speaker test
    _collect_temp_audio(run_logger, crash_type, step_name, run_idx, logs_dir)

    # Collect temp screenshots left by camera checks
    _collect_temp_screenshots(run_logger, crash_type, step_name, run_idx, logs_dir)

    # Restart app after crash
    log_and_print(run_logger, f"{crash_type} detected - attempting restart")
    restart_success, restart_error = restart_app_after_crash(dashboard, run_logger, crash_type, run_idx)
    if not restart_success:
        log_and_print(run_logger, f"Restart failed: {restart_error}", "error")

    should_break = True
    return crash_type, step_name, video_stopped, diagnostics_collected, should_break


def compare_expected_vs_actual(expected_map, actual_status):
    """
    Compare expected vs actual status, handle "Not Test" as special case
    """
    mismatches = []
    for key, expected in (expected_map or {}).items():
        actual = actual_status.get(key, "Missing")

        # Handle "Not Test" case - treat as status_failed rather than assertion_failed
        if actual == "Not Test":
            # Don't count as assertion failure, this indicates app didn't run tests properly
            continue
        elif actual != expected:
            mismatches.append(f"{key}: expected {expected}, got {actual}")

    return mismatches


def handle_get_status(dashboard, run_logger, run_idx, logs_dir, video_started = False):
    """
    Single-attempt get_status with proper "Not Test" handling
    """
    try:
        log_and_print(run_logger, "Start get_status")
        status = dashboard.get_status()
        log_and_print(run_logger, "End get_status")
        time.sleep(1)

        if not status:
            return {}, "status_failed", "Empty status returned"

        # Check if all values are "Not Test" - indicates app restart issue
        all_not_test = all(v == "Not Test" for v in status.values() if v is not None)
        if all_not_test:
            return status, "status_failed", "All tests show 'Not Test' - app may need more time or restart"

        return status, None, None

    except Exception as ex:
        err_type, err_desc = classify_error_type(ex)
        log_and_print(run_logger, f"get_status error: {ex}", "error")

        if err_type in ("uiautomator_crash", "session_crash", "proxy_crash", "network_crash"):
            log_and_print(run_logger, f"{err_type} detected in get_status - restarting app")
            ok, restart_err = restart_app_after_crash(dashboard, run_logger, err_type, run_idx)
            if not ok:
                return {}, "uiautomator_crashed", f"{err_desc}; restart failed: {restart_err}"
            return {}, "uiautomator_crashed", err_desc

        return {}, "status_failed", err_desc

def calculate_run_result(step_crashed, crashed_step, crash_type, failed_steps, status_error_type):
    """
    Tính toán kết quả run với phân loại chi tiết - merged uiautomator errors
    Returns: (result_type, result_details)
    """
    if step_crashed:
        if crash_type in ('uiautomator_crash', 'uiautomator_crashed'):
            return 'uiautomator_failed', f"UiAutomator crashed at step {crashed_step}"
        else:
            return 'step_crashed', f"Step crashed ({crash_type}) at step {crashed_step}"
    elif status_error_type:
        if status_error_type in ('uiautomator_crash', 'uiautomator_crashed'):
            return 'uiautomator_failed', f"UiAutomator failed during get_status"
        else:
            # Treat other status errors as uiautomator_failed too since we removed status_failed
            return 'uiautomator_failed', f"Status read failed ({status_error_type})"
    elif failed_steps:
        return 'assertion_failed', f"Failed assertions: {failed_steps}"
    else:
        return 'passed', "All steps and assertions passed"

def cleanup_video_at_run_end(video_started, video_stopped, run_logger, result_type, run_idx, logs_dir):
    """
    Cleanup video cuối mỗi run nếu chưa được stop
    """
    if video_started and not video_stopped:
        try:
            if result_type == 'passed':
                # For passed runs, stop video nhưng không lưu (temporary cleanup)
                temp_video_path = Path(f"temp_passed_run{run_idx}.mp4")
                stop_recording(str(temp_video_path))
                if temp_video_path.exists():
                    temp_video_path.unlink()
                log_and_print(run_logger, f"📹 Cleaned up passed run video")
            else:
                # For other cases, still save to logs
                cleanup_filename = f"UnknownCrash_{result_type.upper()}_run{run_idx}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                cleanup_fullpath = logs_dir / cleanup_filename
                stop_recording(str(cleanup_fullpath))
                log_and_print(run_logger, f"Unknown crash video saved: {cleanup_fullpath}")
        except Exception as cleanup_ex:
            log_and_print(run_logger, f"Failed to cleanup video: {cleanup_ex}", "error")


def test_suite(dashboard, runs=1000, expected_map=None):
    run_logger = setup_run_logger()
    if expected_map is None:
        expected_map = {
            "Touch Point": "Passed", "Multi-Touch": "Passed",
            "Back Camera": "Passed", "Front Camera": "Passed",
            "Backlight": "Passed", "Flashlight": "Passed",
            "Speaker": "Passed", "Voice Recorder": "Passed",
            "Headset": "Failed", "SD-Card": "Failed",
            "Wifi": "Passed", "Bluetooth": "Passed",
            "Battery Charging": "Passed"
        }

    # full test os
    steps = [
        "touch_point", "multi_touch", "back_camera", "front_camera",
        "back_light", "flash_light", "speaker", "voice_recorder", "headset", "sd_card"
    ]

    project_root = Path(__file__).resolve().parent
    logs_dir = project_root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    run_statistics = {
        'total_runs': runs,
        'passed_runs': 0,
        'assertion_failed_runs': 0,
        'step_crashed_runs': 0,
        'uiautomator_failed_runs': 0,
        'run_times': [],
        'overall_start_time': time.time(),
        'run_details': []
    }
    any_run_passed = False

    for run_idx in range(1, runs + 1):
        log_and_print(run_logger, f"\n=== Run {run_idx}/{runs} START ===")
        result = run_single_test_full_os(dashboard, run_logger, runs,run_idx, steps, expected_map, logs_dir)
        run_statistics['run_details'].append(result)
        run_statistics['run_times'].append(result['duration'])
        if result['passed']:
            run_statistics['passed_runs'] += 1
            any_run_passed = True
        if result['assertion_failed']:
            run_statistics['assertion_failed_runs'] += 1
        if result['step_crashed']:
            run_statistics['step_crashed_runs'] += 1
        if result['uiautomator_failed']:
            run_statistics['uiautomator_failed_runs'] += 1

    pass_rate = summarize_results(run_logger, run_statistics)
    return {
        'any_run_passed': any_run_passed,
        'statistics': run_statistics,
        'pass_rate': pass_rate
    }

def summarize_results(run_logger, run_statistics):
    total_time = time.time() - run_statistics['overall_start_time']
    avg_time = sum(run_statistics['run_times']) / len(run_statistics['run_times']) if run_statistics['run_times'] else 0
    pass_rate = (run_statistics['passed_runs'] / run_statistics['total_runs']) * 100

    log_and_print(run_logger, "\n" + "=" * 60)
    log_and_print(run_logger, "🏁 FINAL TEST RESULTS")
    log_and_print(run_logger, "=" * 60)
    log_and_print(run_logger, f"Total Runs: {run_statistics['total_runs']}")
    log_and_print(run_logger, f"✅ Passed Runs: {run_statistics['passed_runs']}/{run_statistics['total_runs']} ({pass_rate:.1f}%)")
    log_and_print(run_logger, f"❌ Assertion Failed: {run_statistics['assertion_failed_runs']}/{run_statistics['total_runs']}")
    log_and_print(run_logger, f"💥 Step Crashed: {run_statistics['step_crashed_runs']}/{run_statistics['total_runs']}")
    log_and_print(run_logger, f"🔧 UiAutomator Failed: {run_statistics['uiautomator_failed_runs']}/{run_statistics['total_runs']}")
    log_and_print(run_logger, "------------------------------------------------------------")
    log_and_print(run_logger, f"⏱️  Average Run Time: {avg_time:.2f} seconds")
    log_and_print(run_logger, f"⏱️  Total Execution Time: {total_time:.2f} seconds")
    log_and_print(run_logger, "------------------------------------------------------------")
    log_and_print(run_logger, "📋 Detailed Run Results:")

    for detail in run_statistics['run_details']:
        status_map = {
            'passed': 'PASSED',
            'assertion_failed': 'ASSERTION_FAILED',
            'step_crashed': 'STEP_CRASHED',
            'uiautomator_failed': 'UIAUTOMATOR_FAILED'
        }
        status_display = status_map.get(detail['result'], detail['result'].upper())
        details_short = detail['details'][:50] + "..." if len(detail['details']) > 50 else detail['details']
        log_and_print(run_logger, f"   Run {detail['run']}: {status_display} - {details_short} ({detail['duration']:.2f}s)")
    log_and_print(run_logger, "=" * 60)
    return pass_rate


def run_single_test_full_os(dashboard, run_logger, runs, run_idx, steps, expected_map, logs_dir):
    run_start_time = time.time()
    video_started, video_stopped = False, False

    # Start video recording (bind to correct device)
    try:
        device_id = dashboard.app.get_device_id()
        start_recording(device_id = device_id)
        log_and_print(run_logger, f"📹 Started video recording for run {run_idx}")
        video_started = True
    except Exception as video_ex:
        log_and_print(run_logger, f"Failed to start video: {video_ex}", "warning")

    # Health check
    is_healthy, health_reason = check_app_health(dashboard)
    if not is_healthy:
        log_and_print(run_logger, f"App health check failed: {health_reason}", "warning")
        # restart app after checking healthy failed
        ok, err = restart_app_after_crash(dashboard, run_logger, "health_unhealthy", run_idx)
        if not ok:
            log_and_print(run_logger, f"Restart failed: {err}", "error")
        else:
            # small settle time
            time.sleep(2)
    # Clear logcat before every run (all buffers)
    try:
        cmd = ["logcat", "-b", "all", "-c"]
        dashboard.app.run_adb(cmd = cmd, timeout=5)
        log_and_print(run_logger, f"Cleared logcat (all buffers) for run {run_idx}")
    except Exception:
        pass

    # If we are in the first half of the runs (run_idx <= runs/2)
    # → only test Speaker and Voice Recorder (unplug headset and SD-card)
    if run_idx <= runs / 2:
        steps_to_run = [step.lower() for step in steps if step.lower() not in ("headset", "sd_card") ]
        log_and_print(run_logger, f"Run {run_idx}: Testing Speaker + Voice Recorder only (no headset, SD-card)")
    else:
        steps_to_run = [step.lower() for step in steps if step.lower() not in ("speaker", "voice_recorder") ]
        log_and_print(run_logger, f"Run {run_idx}: Testing Speaker + Voice Recorder only (no headset, SD-card)")

    # Step execution
    step_crashed, crashed_step, crash_type = False, None, None
    getattr(dashboard, "start_test")()
    log_and_print(run_logger,"Turn off wifi and bluetooth before testing")
    dashboard.app.disable_wifi_bluetooth()
    for step_name in steps_to_run:
        if step_crashed:
            break

        try:
            # Execute the step
            log_and_print(run_logger, f"Start checking {step_name}")
            getattr(dashboard, f"check_{step_name}")()

        except Exception as ex:
            # Regular step crash path
            crash_type, crashed_step, video_stopped, _, should_break = handle_step_crash(
                dashboard, run_logger, step_name, ex, run_idx, video_started, logs_dir
            )
            step_crashed = True
            if should_break:
                break
        finally:
            log_and_print(run_logger, f"End checking {step_name}")

    # expected_devices_status = {"charging": True, "sdcard": True, "headset": True}
    # actual_devices_status = getattr(dashboard, "check_setup_status")()
    # actual_devices_status = dashboard.app.check_device_status()
    # assert_value_status(actual_devices_status, expected_devices_status, "Headset - SD card - Battery charging are all set")
    # Status check
    status, status_error_type, status_error_message = {}, None, None
    if not step_crashed:
        status, status_error_type, status_error_message = handle_get_status(dashboard, run_logger, run_idx, logs_dir)
        if status_error_type:
            log_and_print(run_logger, f"get_status failed: {status_error_message}", "warning")

    # Assertion check
    failed_steps = []
    if not step_crashed and not status_error_type and status:
        failed_steps = compare_expected_vs_actual(expected_map, status)

    # Result calculation
    result_type, result_details = calculate_run_result(
        step_crashed, crashed_step, crash_type, failed_steps, status_error_type
    )
    if failed_steps:
        result_type = 'assertion_failed'
        result_details = f"Failed assertions: {failed_steps}"

    # Pass/Fail summary for this run (shown before duration)
    if result_type == 'passed':
        log_and_print(run_logger, f"Run {run_idx} passed")
    else:
        log_and_print(run_logger, f"Run {run_idx} failed")

    # Run time
    run_end_time = time.time()
    run_duration = run_end_time - run_start_time
    log_and_print(run_logger, f"Run {run_idx} execution time: {run_duration:.2f} seconds")

    # Cleanup video
    cleanup_video_at_run_end(video_started, video_stopped, run_logger, result_type, run_idx, logs_dir)
    log_and_print(run_logger, f"=== Run {run_idx} END ===\n")

    return {
        'run': run_idx,
        'result': result_type,
        'details': result_details,
        'duration': run_duration,
        'passed': result_type == 'passed',
        'assertion_failed': result_type == 'assertion_failed',
        'step_crashed': result_type == 'step_crashed',
        'uiautomator_failed': result_type in ('uiautomator_crashed', 'uiautomator_failed')
    }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Benchmark app execution.\n')
    parser.add_argument('--desired-caps', help='desired capabilities config file')
    arguments = parser.parse_args()
    app = AppHandler(arguments.desired_caps)
    dashboard_instance = Dashboard(app)
    dashboard_instance.start_benchmark_app()
    test_suite(dashboard_instance)