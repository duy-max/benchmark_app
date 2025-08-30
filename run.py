import argparse
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

from corelib.app_handler import AppHandler
from corelib.log_config import get_logger
from corelib.record_video import start_recording, stop_recording
from corelib.utils import assert_value_status
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
    run_logger = get_logger(name=f"run_session_{timestamp}", filename=log_filename, dir_name="logs_run")
    print(f"📝 Run session log: {run_logger._log_path}")
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
        device_id = _get_device_id(dashboard)
        cmd = ["adb"]
        if device_id:
            cmd += ["-s", str(device_id)]
        cmd += ["shell", "dumpsys", "activity", "activities"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return False, "Failed to get activity dump"

        output = result.stdout
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
        device_id = _get_device_id(dashboard)
        cmd = ["adb"]
        if device_id:
            cmd += ["-s", str(device_id)]
        cmd += ["shell", "pidof", "com.innova.benchmark"]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode != 0 or not result.stdout.strip():
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

def _get_device_id(dashboard):
    try:
        return dashboard.app.desired_caps.get('udid')
    except Exception:
        return None

def detect_am_crash_event(dashboard, since_epoch=0.0):
    """
    Check logcat events buffer for am_crash of our package since 'since_epoch'.
    Returns: (detected: bool, last_seen_epoch: float, raw_line: str or None)
    """
    device_id = _get_device_id(dashboard)
    pkg = "com.innova.benchmark"

    cmd = ["adb"]
    if device_id:
        cmd += ["-s", str(device_id)]
    # Only events buffer, epoch time, filter to am_crash
    cmd += ["logcat", "-b", "events", "-v", "epoch", "-d", "am_crash:I", "*:S"]

    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        out = p.stdout or ""
    except Exception:
        return False, since_epoch, None

    detected = False
    last_ts = since_epoch
    last_line = None

    for line in out.splitlines():
        if "am_crash" not in line:
            continue
        if pkg not in line:
            continue

        m = re.match(r"^\s*(\d+\.\d+)\s", line)
        if not m:
            # Some builds print integer epoch
            m = re.match(r"^\s*(\d+)\s", line)
        if not m:
            continue
        ts = float(m.group(1))
        if ts > since_epoch:
            detected = True
            if ts >= last_ts:
                last_ts = ts
                last_line = line

    return detected, last_ts, last_line

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
                device_id = _get_device_id(dashboard)
                cmd_kill_inst = ["adb"]
                if device_id:
                    cmd_kill_inst += ["-s", str(device_id)]
                cmd_kill_inst += ["shell", "pkill", "-f", "uiautomator"]
                subprocess.run(cmd_kill_inst, timeout=10, capture_output=True)
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
            device_id = _get_device_id(dashboard)
            cmd_launch = ["adb"]
            if device_id:
                cmd_launch += ["-s", str(device_id)]
            cmd_launch += ["shell", "am", "start", "-n", "com.innova.benchmark/.views.activities.MainActivity"]
            subprocess.run(cmd_launch, timeout=10, capture_output=True)
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


def handle_step_crash(dashboard, run_logger, step_name, exception, run_idx, video_started, logs_dir):
    """
    Xử lý khi step bị crash - always break to next run after crash
    """
    crash_type, crash_desc = classify_error_type(exception)
    log_and_print(run_logger, f"ERROR in {step_name}: {exception}", "error")
    log_and_print(run_logger, f"Crash type: {crash_type} - {crash_desc}")
    dashboard.logger.exception(f"Exception in step {step_name}: {exception}")

    # Stop video for crash and save it
    video_stopped = False
    if video_started:
        try:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            video_name = f"VIDEO_{crash_type.upper()}_{step_name}_run{run_idx}_{ts}.mp4"
            video_path = logs_dir / video_name
            stop_recording(str(video_path))
            video_stopped = True
            log_and_print(run_logger, f"📹 Crash video saved: {str(video_path)}")
        except Exception as stop_ex:
            log_and_print(run_logger, f"Failed to stop/save crash video: {stop_ex}", "warning")

    # Collect diagnostics
    diagnostics_collected = False
    try:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        tag = f"run{run_idx}_{step_name}_{crash_type}_{ts}"
        collected = dashboard.app.collect_on_failure(
            reason=f"{crash_type} in step {step_name}",
            output_dir=None,
            tag=tag
        )
        full_tag = get_full_collected_tag(collected, tag)
        log_and_print(run_logger, f"Collected {crash_type} crash logs: {full_tag}")
        diagnostics_collected = True
    except Exception as collect_ex:
        log_and_print(run_logger, f"Failed to collect crash logs: {collect_ex}", "error")

    # Always restart after crash and break to next run
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

        # check if wifi and bluetooth are enabled
        # actual_wifi_bluetooth_status = dashboard.app.check_wifi_bluetooth()
        # expected_wifi_bluetooth_status = {"wifi": True, "bluetooth": True}
        # assert_value_status(actual_wifi_bluetooth_status, expected_wifi_bluetooth_status, "Wi-Fi and Bluetooth are enabled")

        # handle wifi and bluetooth if crash
        wf_bt_status = dashboard.app.check_wifi_bluetooth()
        if wf_bt_status.get("wifi") is True and wf_bt_status.get("bluetooth") is True:
            log_and_print(run_logger, "Wi-Fi and Bluetooth are enabled")
        else:
            # Wi‑Fi disabled
            if wf_bt_status.get("wifi") is False:
                log_and_print(run_logger, "Wi\-Fi is disabled after get_status - collecting diagnostics", "warning")
                # reuse existing crash handler to stop video and collect logs
                handle_step_crash(
                    dashboard,
                    run_logger,
                    step_name="get_status_wifi_disabled",
                    exception=Exception("Wi‑Fi disabled after get_status"),
                    run_idx=run_idx,
                    video_started=video_started,
                    logs_dir= logs_dir
                )
                return {}, "wifi_disabled", "Wi-Fi is still disabled after trying to enable it"

            # Bluetooth disabled
            if wf_bt_status.get("bluetooth") is False:
                log_and_print(run_logger, "Bluetooth is disabled after get_status - collecting diagnostics", "warning")
                handle_step_crash(
                    dashboard,
                    run_logger,
                    step_name="get_status_bluetooth_disabled",
                    exception=Exception("Bluetooth disabled after get_status"),
                    run_idx=run_idx,
                    video_started=video_started,
                    logs_dir= logs_dir
                )
                return {}, "bluetooth_disabled", "Bluetooth is still disabled after trying to enable it"

            # end handle wifi - bluetooth
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


# def handle_get_status_failure(dashboard, run_logger, run_idx, error_type, error_message, video_started):
#     """
#     Xử lý khi get_status thất bại
#     Returns: (video_stopped, diagnostics_collected)
#     """
#     log_and_print(run_logger, f"Failed to get status: {error_message}", "error")
#
#     # Stop video for get_status failure
#     video_stopped = False
#     if video_started:
#         try:
#             status_fail_filename = f"STATUS_FAIL_{error_type.upper()}_run{run_idx}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
#             project_root = Path(__file__).resolve().parent
#             logs_dir = project_root / "logs"
#             status_fail_fullpath = logs_dir / status_fail_filename
#             stop_recording(str(status_fail_fullpath))
#             log_and_print(run_logger, f"📹 Stopped video for get_status failure: {str(status_fail_fullpath)}")
#             video_stopped = True
#
#             if status_fail_fullpath.exists():
#                 file_size = status_fail_fullpath.stat().st_size
#                 log_and_print(run_logger, f"✅ Status fail video created: {status_fail_fullpath} ({file_size} bytes)")
#         except Exception as stop_ex:
#             log_and_print(run_logger, f"Failed to stop status fail video: {stop_ex}", "error")
#
#     # Collect diagnostics
#     diagnostics_collected = False
#     try:
#         ts = datetime.now().strftime('%Y%m%d_%H%M%S')
#         tag = f"run{run_idx}_get_status_{error_type}_{ts}"
#         collected = dashboard.app.collect_on_failure(
#             reason=f"get_status failed in run {run_idx}: {error_message}",
#             tag=tag
#         )
#         full_tag = get_full_collected_tag(collected, tag)
#         log_and_print(run_logger, f"Collected get_status failure logs: {full_tag}")
#         diagnostics_collected = True
#     except Exception as collect_ex:
#         log_and_print(run_logger, f"Failed to collect get_status logs: {collect_ex}", "error")
#
#     return video_stopped, diagnostics_collected


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


def test_suite(dashboard, runs=10, expected_map=None):
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
    steps = [
        "touch_point", "multi_touch", "back_camera", "front_camera",
        "back_light", "flash_light", "speaker", "voice_recorder"
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
        result = run_single_test(dashboard, run_logger, run_idx, steps, expected_map, logs_dir)
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



def run_single_test(dashboard, run_logger, run_idx, steps, expected_map, logs_dir):
    run_start_time = time.time()
    video_started, video_stopped = False, False

    # Start video recording (bind to correct device)
    try:
        device_id = _get_device_id(dashboard)
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
        device_id = _get_device_id(dashboard)
        cmd = ["adb"]
        if device_id:
            cmd += ["-s", str(device_id)]
        cmd += ["logcat", "-b", "all", "-c"]
        subprocess.run(cmd, timeout=5)
        log_and_print(run_logger, f"Cleared logcat (all buffers) for run {run_idx}")
    except Exception:
        pass

    # Keep last-seen events epoch to detect am_crash per step
    events_last_epoch = 0.0

    # Step execution
    step_crashed, crashed_step, crash_type = False, None, None
    getattr(dashboard, "start_test")()
    log_and_print(run_logger,"Turn off wifi and bluetooth before testing")
    # getattr(dashboard, "turn_off_wifi_bluetooth")()
    dashboard.app.disable_wifi_bluetooth()
    for step_name in steps:
        if step_crashed:
            break

        try:
            # Execute the step
            log_and_print(run_logger, f"Start {step_name}")
            getattr(dashboard, step_name)()


            # Immediately check if am_crash happened during/after this step
            detected, events_last_epoch, raw_line = detect_am_crash_event(dashboard, since_epoch=events_last_epoch)
            if detected:
                crash_type, crashed_step, video_stopped, _, should_break = handle_step_crash(
                    dashboard, run_logger, step_name,
                    exception="am crash detected",
                    run_idx=run_idx,
                    video_started=video_started,
                    logs_dir= logs_dir
                )
                step_crashed = True
                if should_break:
                    break

        except Exception as ex:
            # Regular step crash path
            crash_type, crashed_step, video_stopped, _, should_break = handle_step_crash(
                dashboard, run_logger, step_name, ex, run_idx, video_started, logs_dir
            )
            step_crashed = True
            if should_break:
                break
        finally:
            log_and_print(run_logger, f"End {step_name}")

    expected_devices_status = {"charging": True, "sdcard": True, "headset": True}

    # actual_devices_status = getattr(dashboard, "check_setup_status")()
    actual_devices_status = dashboard.app.check_device_status()
    assert_value_status(actual_devices_status, expected_devices_status, "Headset - SD card - Battery charging are all set")
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
    app = AppHandler(arguments.desired_caps, command_executor='http://127.0.0.1:4723')
    dashboard = Dashboard(app)
    dashboard.start_benchmark_app()
    test_suite(dashboard)