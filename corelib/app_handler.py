try:
    import re
    from appium import webdriver
    from appium.webdriver.appium_service import AppiumService
    from appium.webdriver.common.appiumby import AppiumBy
    from appium.webdriver.webelement import WebElement
    from selenium.webdriver.support import expected_conditions as ec
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.common.exceptions import NoSuchElementException, TimeoutException, NoSuchWindowException
    from appium.options.android import UiAutomator2Options
    from selenium.webdriver.common.actions.pointer_input import PointerInput
    from selenium.webdriver.common.actions.action_builder import ActionBuilder
    from corelib import utils
    from corelib.logger import Logger
    from pathlib import Path
    import subprocess
    from datetime import datetime
    import random
    import time

except ImportError as imp_err:
    print('There was an error importing files - From %s' % __file__)
    print('\n---{{{ Failed - ' + format(imp_err) + ' }}}---\n')
    raise

BY_MAP = {
    'id': AppiumBy.ID,
    'xpath': AppiumBy.XPATH,
    'name': AppiumBy.NAME,
    'class_name': AppiumBy.CLASS_NAME,
    'uiautomator': AppiumBy.ANDROID_UIAUTOMATOR,
}


class AppHandler:
    DEFAULT_IMPLICIT_TIMEOUT = 8
    DEFAULT_EXPLICIT_TIMEOUT = 8

    def __init__(self, desired_caps, command_executor='http://127.0.0.1:4723',
                 implicit_timeout=DEFAULT_IMPLICIT_TIMEOUT):
        self.logger = Logger(name="benchmark_app", filename="apphandler.log", dir_name="logs")
        # Get the _log_path attribute from logger, or None if it doesn't exist
        self._local_log_path = getattr(self.logger, "log_path", None)
        self.command_executor = command_executor
        self.desired_caps = utils.read_config_file(desired_caps)
        self.implicit_timeout = implicit_timeout
        self.driver = None

    def start_app(self):
        """
        Start a new Appium session using stored desired_caps.
        If an existing driver/session exists, quit it first.
        """
        try:
            # quit existing session if present
            if getattr(self, "driver", None):
                try:
                    self.logger.info("Existing driver detected - quitting before start.")
                    self.driver.quit()
                except Exception:
                    self.logger.info("Ignoring error while quitting existing driver before start.")
                finally:
                    self.driver = None

            if not getattr(self, "desired_caps", None):
                raise RuntimeError("desired_caps not set; cannot start app")

            self.logger.info('Starting app/session')
            options = UiAutomator2Options().load_capabilities(self.desired_caps)
            self.driver = webdriver.Remote(command_executor=self.command_executor, options=options)

            # set implicit wait if configured
            try:
                self.driver.implicitly_wait(int(self.implicit_timeout))
            except Exception:
                pass

            self.logger.info('App/session started')
            return self.driver
        except Exception as e:
            self.logger.exception(f"Failed to start app/session: {e}")
            raise

    def quit_all(self, *app_ids):
        """
        Gracefully terminate provided app_ids (optional) and quit driver session.
        Safe to call even if driver is None.
        """
        try:
            if getattr(self, "driver", None):
                # try terminate specific apps first
                if app_ids:
                    for app_id in app_ids:
                        try:
                            self.logger.info(f'Terminating app: {app_id}')
                            self.driver.terminate_app(app_id)
                        except Exception:
                            self.logger.info(f"Failed to terminate {app_id}")
                # quit driver session
                try:
                    self.logger.info('Quitting driver session')
                    self.driver.quit()
                except Exception:
                    self.logger.info("Error while quitting driver")
                finally:
                    self.driver = None
            else:
                self.logger.info("quit_all called but no active driver/session")
        except Exception:
            # swallow to avoid raising during cleanup
            self.driver = None
            self.logger.info("Unexpected error in quit_all, cleaned up driver reference")
    
    # def get_device_node(self):
    #     return self

    @property
    def session(self):
        return self.driver.session

    def dump_device_logs(self, output_dir, tag: str = None):
        """
        Collect device logs via adb: logcat (-d) and dmesg.
        If tag provided it will be appended to filenames (sanitized).
        Returns dict with file paths.
        """
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        out = {}

        # sanitize tag to safe suffix (only alnum and underscore)
        suffix = ""
        if tag:
            safe = re.sub(r'[^0-9A-Za-z_]+', '_', tag)
            suffix = f"_{safe}"

        device_id = self.get_device_id()

        def _run_and_write(cmd, filepath):
            rc, out, err = self.run_adb(cmd)
            content = out if rc == 0 else err
            try:
                with open(filepath, "w", encoding="utf-8", errors="replace") as f:
                    f.write(content)
                self.logger.info(f"Wrote {filepath}")
            except Exception as ex:
                self.logger.error(f"Failed to write {filepath}: {ex}")
        # logcat
        logcat_file = output_dir / f"logcat_{device_id}{suffix}_{ts}.txt"
        _run_and_write(cmd =["logcat", "-d"], filepath = logcat_file)
        out['logcat'] = logcat_file

        # dmesg
        dmesg_file = output_dir / f"dmesg_{device_id}{suffix}_{ts}.txt"
        _run_and_write(cmd = ["shell", "dmesg"], filepath = dmesg_file)
        out['dmesg'] = dmesg_file
        return out

    def collect_on_failure(self, reason=None, output_dir=None, tag: str = None):
        """
        Collect logs & diagnostics. Optional tag used to include context in filenames.
        """
        try:
            self.logger.error(f"Collecting diagnostics due to failure: {reason}")
        except Exception:
            pass

        try:
            files = self.dump_device_logs(output_dir=output_dir, tag=tag)
        except Exception as ex:
            self.logger.error(f"dump_device_logs failed: {ex}")
            files = {}

        try:
            if hasattr(self, "_local_log_path") and self._local_log_path:
                # copy or add path, but include tag in reported name if provided
                files['apphandler_log'] = self._local_log_path
        except Exception:
            pass

        return files
    
    def wait_visibility_of_element_located(self, locator, timeout=DEFAULT_EXPLICIT_TIMEOUT, inverse=False):
        """
        Wait until the located element is present and visible which means its height and width > 0
        :param locator: (str) locator format
        :param timeout: (int) timeout
        :param inverse: (bool) False to wait until the condition met, True to wait until the condition not met
        :return: (bool) True if the expected wait happens, False otherwise
        """
        by, value = utils.parse_key_value(locator)
        result = self._wait_explicit(ec.visibility_of_element_located, (BY_MAP[by], value),
                                timeout=timeout, inverse=inverse)
        if not result:
            raise TimeoutException(f"Element {locator} not visible after {timeout}s")
        return True

    def get_text(self, locator):
        """
        Get the text of an element specified by locator.
        :param locator: (str) locator format
        :return: (str) text of the element
        """
        element = self._get_element(locator, explicit_func=self.wait_visibility_of_element_located,
                                    error_msg=f'Element is not visible to get text @ `{locator}`')
        return element.text if element else None

    def tap(self, locator_or_element):
        """
        Tap using W3C Actions (Pointer)
        :param locator_or_element: (str) locator format or (WebElement) web element
        :return: None
        """
        element = self._get_element(locator_or_element, explicit_func=self.wait_visibility_of_element_located,
                                    error_msg=f'Element is not visible to tap @ `{locator_or_element}`')

        x = element.location['x'] + element.size['width'] // 2
        y = element.location['y'] + element.size['height'] // 2

        # Tạo hành động touch tại vị trí (x, y)
        pointer = PointerInput("touch", "finger") 
        actions = ActionBuilder(self.driver, mouse=pointer)

        actions.pointer_action.move_to_location(x, y)
        actions.pointer_action.pointer_down()
        actions.pointer_action.pointer_up()

        actions.perform()

    def _get_element(self, locator_or_element,
                     explicit_func=None, explicit_timeout=DEFAULT_EXPLICIT_TIMEOUT, error_msg=None):
        """
        INTERNAL USE ONLY
        Wrap the get_element to handle both locator and WebElement
        :param locator_or_element: (str) locator format or (WebElement) web element
        :param explicit_func: (function) explicit function on locator pre-check
        :param explicit_timeout: (int) explicit timeout for explicit function
        :param error_msg: (str) error message to display if explicit check is unexpected
        :return: (WebElement) the web element
        """
        if isinstance(locator_or_element, str):
            if explicit_func:
                if not explicit_func(locator_or_element, timeout=explicit_timeout):
                    if error_msg:
                        self.logger.error(error_msg)
                        raise Exception(error_msg)
                    raise Exception
            element = self.get_element(locator_or_element)
        else:
            element = locator_or_element
        return element
    def get_element(self, locator):
        """
        Get an element
        :param locator: (str) locator format
        :return: (Element object) the element
        """
        by, value = utils.parse_key_value(locator)
        try:
            element = self.driver.find_element(by=BY_MAP[by], value=value)
            self.logger.info(f'Element @ `{locator}` located.')
        except (NoSuchElementException,):
            element = None
            self.logger.info(f'No elements @ `{locator}` located.')
        return element


    def _wait_explicit(self, func, *args, timeout, inverse):
        try:
            wait = WebDriverWait(self.driver, int(timeout))
            if not inverse:
                self.logger.info(f'Explicit wait {func.__name__} on {args} until meet')
                # func -> ec.visibility_of_element_located
                # *args -> (BY_MAP[by], value)
                wait.until(func(*args))
            else:
                self.logger.info(f'Explicit wait {func.__name__} on {args} until not meet')
                wait.until_not(func(*args))
            self.logger.info('Explicit wait final state: True')
            return True
        except TimeoutException:
            self.logger.info('Explicit wait final state: False')
            return False

    def wait_visibility_of_all_elements_located(self, locator, timeout=DEFAULT_EXPLICIT_TIMEOUT, inverse=False):
        """
        Wait until all located elements are present and visible, which means its height and width > 0
        :param locator: (str) locator format
        :param timeout: (int) timeout
        :param inverse: (bool) False to wait until the condition met, True to wait until the condition not met
        :return: (bool) True if the expected wait happens, False otherwise
        """
        by, value = utils.parse_key_value(locator)
        result = self._wait_explicit(ec.visibility_of_all_elements_located, (BY_MAP[by], value),
                                   timeout=timeout, inverse=inverse)
        if not result:
            raise TimeoutException(f"Element {locator} not visible after {timeout}s")
        return True


    def tap_by_coordinates(self, x=147, y=151):
        """
        Tap vào một điểm trên màn hình theo tọa độ x, y.

        :param x: hoành độ (int)
        :param y: tung độ (int)
        """
        finger = PointerInput("touch", "finger") 
        actions = ActionBuilder(self.driver, mouse=finger)

        actions.pointer_action.move_to_location(x, y)
        actions.pointer_action.pointer_down()
        actions.pointer_action.pointer_up()
        actions.perform()

    def multi_touch_five_fingers(self, locator, element=None):
        """
        Simultaneous 5-finger tap using W3C actions.
        Nếu element được truyền từ bên ngoài thì không gọi wait nữa.
        """
        try:
            if element is None:
                element = self._get_element(
                    locator,
                    explicit_func=self.wait_visibility_of_element_located,
                    error_msg=f'Element is not visible to multi-touch @ `{locator}`'
                )

            x = int(element.location['x'])
            y = int(element.location['y'])
            w = int(element.size['width'])
            h = int(element.size['height'])

            padding = 20
            points = [
                (x + w // 2, y + h // 2),  # center
                (x + padding, y + padding),  # top-left
                (x + w - padding, y + padding),  # top-right
                (x + padding, y + h - padding),  # bottom-left
                (x + w - padding, y + h - padding)  # bottom-right
            ]

            self.logger.info(f'Performing 5-finger multi-touch at points: {points}')

            # Build W3C action
            w3c_actions = []
            for i, (px, py) in enumerate(points):
                w3c_actions.append({
                    "type": "pointer",
                    "id": f"finger{i}",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {"type": "pointerMove", "duration": 0, "x": int(px), "y": int(py)},
                        {"type": "pointerDown", "button": 0},
                        {"type": "pause", "duration": 100},
                        {"type": "pointerUp", "button": 0}
                    ]
                })

            self.driver.execute("actions", {"actions": w3c_actions})
            self.logger.info("Performed multi-touch via execute('actions')")

        except Exception as exc:
            self.logger.error(f"Multi-touch failed: {exc}")

    def multi_touch_five_fingers_random(self, locator, randomness_factor=0.3):
        """
        5-finger multi-touch với random coordinates trong element bounds.
        Fallback sang fixed nếu random fail.
        """
        element = None
        try:
            element = self._get_element(
                locator,
                explicit_func=self.wait_visibility_of_element_located,
                error_msg=f'Element is not visible to multi-touch @ `{locator}`'
            )

            x = int(element.location['x'])
            y = int(element.location['y'])
            w = int(element.size['width'])
            h = int(element.size['height'])

            # Safe padding tránh chạm sát viền
            safe_padding = 20
            offset_x = int(w * randomness_factor)
            offset_y = int(h * randomness_factor)

            # Base positions
            base_points = [
                (x + w // 2, y + h // 2),  # center
                (x + w // 4, y + h // 4),  # top-left area
                (x + 3 * w // 4, y + h // 4),  # top-right area
                (x + w // 4, y + 3 * h // 4),  # bottom-left area
                (x + 3 * w // 4, y + 3 * h // 4)  # bottom-right area
            ]

            # Apply random offset
            points = []
            screen_size = self.driver.get_window_size()
            screen_w, screen_h = screen_size["width"], screen_size["height"]

            for base_x, base_y in base_points:
                random_offset_x = random.randint(-offset_x, offset_x)
                random_offset_y = random.randint(-offset_y, offset_y)

                final_x = max(x + safe_padding, min(base_x + random_offset_x, x + w - safe_padding))
                final_y = max(y + safe_padding, min(base_y + random_offset_y, y + h - safe_padding))

                # Clamp vào trong screen để tránh crash W3C
                final_x = max(1, min(final_x, screen_w - 1))
                final_y = max(1, min(final_y, screen_h - 1))

                points.append((final_x, final_y))

            self.logger.info(f'Performing 5-finger random multi-touch at points: {points}')

            # Build W3C action
            w3c_actions = []
            for i, (px, py) in enumerate(points):
                w3c_actions.append({
                    "type": "pointer",
                    "id": f"finger{i}",
                    "parameters": {"pointerType": "touch"},
                    "actions": [
                        {"type": "pointerMove", "duration": 0, "x": int(px), "y": int(py)},
                        {"type": "pointerDown", "button": 0},
                        {"type": "pause", "duration": 100},
                        {"type": "pointerUp", "button": 0}
                    ]
                })

            self.driver.execute("actions", {"actions": w3c_actions})
            self.logger.info("Performed random multi-touch via execute('actions')")

        except Exception as e1:
            self.logger.info(f"Random multi-touch failed: {e1}")
            self.logger.info("Fallback to fixed multi-touch")
            # Dùng lại element đã tìm thấy, không wait lại
            self.multi_touch_five_fingers(locator, element=element)


    def tap_with_random_offset(self, locator_or_element, offset_percentage=0.3):
        """
        Tap element với random offset trong bounds
        :param locator_or_element: (str) locator hoặc WebElement
        :param offset_percentage: (float) percentage của element size để random (0.0-0.5)
        """
        element = self._get_element(locator_or_element, explicit_func=self.wait_visibility_of_element_located,
                                    error_msg=f'Element is not visible to tap @ `{locator_or_element}`')

        # Get element bounds
        x = element.location['x']
        y = element.location['y']
        w = element.size['width']
        h = element.size['height']

        # Calculate random offset within percentage of element size
        max_offset_x = int(w * offset_percentage)
        max_offset_y = int(h * offset_percentage)
        
        # Random coordinates within element bounds với offset
        min_x = x + max_offset_x
        max_x = x + w - max_offset_x
        min_y = y + max_offset_y
        max_y = y + h - max_offset_y
        
        random_x = random.randint(min_x, max_x)
        random_y = random.randint(min_y, max_y)

        self.logger.info(f"Random tap at ({random_x}, {random_y}) within element bounds ({x},{y},{w},{h})")

        # Tap at random coordinates
        pointer = PointerInput("touch", "finger") 
        actions = ActionBuilder(self.driver, mouse=pointer)

        actions.pointer_action.move_to_location(random_x, random_y)
        actions.pointer_action.pointer_down()
        actions.pointer_action.pointer_up()

        actions.perform()


    def tap_by_random_coordinates_in_bounds(self, locator, tap_count=1):
        """
        Random tap trong bounds của element (thay thế tap_by_coordinates cố định)
        :param locator: (str) locator của element để lấy bounds
        :param tap_count: (int) số lần tap random
        """
        try:
            element = self._get_element(locator, explicit_func=self.wait_visibility_of_all_elements_located,
                                        error_msg=f'Elements not visible for random coordinates @ `{locator}`')
            
            # Get overall bounds của all touch points
            x = element.location['x']
            y = element.location['y'] 
            w = element.size['width']
            h = element.size['height']

            for i in range(tap_count):
                # Random coordinates trong bounds
                random_x = random.randint(x + 10, x + w - 10)  # padding 10px
                random_y = random.randint(y + 10, y + h - 10)
                
                self.logger.info(f"Random tap {i+1} at ({random_x}, {random_y})")
                
                finger = PointerInput("touch", "finger") 
                actions = ActionBuilder(self.driver, mouse=finger)

                actions.pointer_action.move_to_location(random_x, random_y)
                actions.pointer_action.pointer_down()
                actions.pointer_action.pointer_up()
                actions.perform()
                
                if i < tap_count - 1:  # pause between taps
                    time.sleep(0.2)
                    
        except Exception as e:
            self.logger.error(f"Random coordinate tap failed: {e}")
            # Fallback to fixed coordinates
            self.tap_by_coordinates()


    def _adb_base(self):
        """
        Build base adb command with device selector if udid/deviceName is provided.
        """
        try:
            device_id = self.get_device_id()
        except Exception:
            device_id = None
        cmd = ["adb"]
        if device_id:
            cmd += ["-s", str(device_id)]
        return cmd

    def run_adb(self, extra_args, timeout=6):
        """
        Run adb with extra args; return (returncode, stdout, stderr).
        """
        try:
            full = self._adb_base() + list(extra_args)
            self.logger.info(f"ADB: {' '.join(full)}")
            p = subprocess.run(full, capture_output=True, text=True, timeout=timeout)
            return p.returncode, (p.stdout or ""), (p.stderr or "")
        except Exception as ex:
            self.logger.info(f"ADB call failed: {ex}")
            return 1, "", str(ex)

    def disable_wifi_bluetooth(self, wait_sec=1.0):
        """
        Disable Wi-Fi and Bluetooth via adb.
        Tries multiple commands, logs the one that works.
        """
        cmds = {
            "wifi": [
                ["shell", "svc", "wifi", "disable"],
                ["shell", "cmd", "wifi", "set-wifi-enabled", "disabled"],
            ],
            "bluetooth": [
                ["shell", "cmd", "bluetooth_manager", "disable"],  # Android 12+
                ["shell", "cmd", "bluetooth", "disable"],  # Android 13+
                ["shell", "service", "call", "bluetooth_manager", "6"],  # legacy
                ["shell", "service", "call", "bluetooth_manager", "8"],  # legacy alt
            ]
        }

        for category, cmd_list in cmds.items():
            success = False
            for cmd in cmd_list:
                rc, out, err = self.run_adb(cmd)  # lấy tuple
                if rc == 0:
                    self.logger.info(f"{category}: success with `{cmd}` (stdout={out.strip()})")
                    success = True
                    break
                else:
                    self.logger.info(f"{category}: failed `{cmd}` -> {err.strip()}")
            if not success:
                self.logger.warning(f"{category}: all disable attempts failed")

        try:
            time.sleep(float(wait_sec))
        except Exception as ex:
            self.logger.warning(f"Failed to disable Wi‑Fi/Bluetooth: {ex}")


    # def check_device_status(self):
    #     result = {}
    #
    #     # Battery
    #     rc, out, _ = self.run_adb(["shell", "dumpsys", "battery"])
    #     charging = False
    #     if "USB powered: true" in out or "AC powered: true" in out or "Wireless powered: true" in out:
    #         charging = True
    #     if "status: 2" in out or "status: 5" in out:  # charging or full
    #         charging = True
    #     result["charging"] = charging
    #
    #     # SD Card
    #     rc, out, _ = self.run_adb(["shell", "sm", "list-volumes", "all"])
    #     sdcard = any(line.startswith("public:") and "mounted" in line for line in out.splitlines())
    #     result["sdcard"] = sdcard
    #
    #     # Headset
    #     rc, out, _ = self.run_adb(["shell", "dumpsys", "audio"])
    #     headset = ("headset" in out.lower() or "headphone" in out.lower())
    #     result["headset"] = headset
    #
    #     return result

    def is_battery_charging(self):
        rc, out, _ = self.run_adb(["shell", "dumpsys", "battery"])
        charging = False
        if "USB powered: true" in out or "AC powered: true" in out or "Wireless powered: true" in out:
            charging = True
        if "status: 2" in out or "status: 5" in out:  # charging or full
            charging = True
        return charging


    def is_headset_plugged(self):
        rc, out, _ = self.run_adb(["shell", "dumpsys", "audio"])
        headset = ("headset" in out.lower() or "headphone" in out.lower())
        return headset

    def is_sdcard_mounted(self):
        rc, out, _ = self.run_adb(["shell", "sm", "list-volumes", "all"])
        sdcard = any(line.startswith("public:") and "mounted" in line for line in out.splitlines())
        return sdcard

    def is_wifi_enabled(self):
        # This only checks if Wi-Fi is enabled (switch on/off), it does NOT check if the device is connected to a network.
        # To check if Wi-Fi is connected, use it: adb shell dumpsys wifi | grep "mNetworkInfo"
        rc, out, _ = self.run_adb(["shell", "settings", "get", "global", "wifi_on"])
        wifi = (out.strip() == "1")
        return wifi

    def is_bluetooth_enabled(self):
        rc, out, _ = self.run_adb(["shell", "settings", "get", "global", "bluetooth_on"])
        bluetooth = (out.strip() == "1")
        return bluetooth

    def get_device_id(self):
        return self.desired_caps.get('udid')

    # python
    def check_flashlight(self):
        """
        Check flashlight/torch state via adb. Returns True if appears ON, False otherwise.
        """
        try:
            probes = [
                ["shell", "dumpsys", "flashlight"],
                ["shell", "dumpsys", "media.camera"],
                ["shell", "dumpsys", "camera"],
                ["shell", "dumpsys", "device_policy"]  # fallback; harmless if unsupported
            ]
            for cmd in probes:
                rc, out, err = self.run_adb(cmd)
                text = (out or "") + (err or "")
                low = text.lower()
                # match a few common indicators
                if "torchmode=on" in low or "torch mode" in low or "torch: on" in low:
                    return True
                if "flashlight" in low and ("on" in low or "enabled" in low):
                    return True
                if "enabled=true" in low or "on=true" in low or "state: on" in low:
                    return True
            return False
        except Exception:
            return False

    def is_brightness_increasing(self, delay: float = 2.0) -> bool:
        """
        Check if screen brightness is increasing over a short interval.
        Run adb twice with a delay, compare values.
        Returns True if brightness difference > 0, else False.
        """

        def _get_level():
            rc, out, _ = self.run_adb(["shell", "settings", "get", "system", "screen_brightness"])
            if rc == 0 and (out or "").strip().isdigit():
                return int(out.strip())
            return None

        first = _get_level()
        if first is None:
            return False

        time.sleep(delay)  # wait a bit before re-checking

        second = _get_level()
        if second is None:
            return False

        return (second - first) > 0

    def check_brightness(self):
        """
        Check screen brightness via adb settings. Returns True if brightness value > 0, False otherwise.
        """
        try:
            rc, out, err = self.run_adb(["shell", "settings", "get", "system", "screen_brightness"])
            if rc != 0:
                return False
            val = (out or "").strip()
            if not val:
                return False
            # sometimes adb returns non-numeric; guard it
            try:
                iv = int(val)
                return iv > 0
            except ValueError:
                # fallback: try reading backlight sysfs (best-effort)
                try:
                    rc2, out2, err2 = self.run_adb(["shell", "cat", "/sys/class/backlight/*/brightness"])
                    if rc2 == 0 and out2.strip().isdigit():
                        return int(out2.strip()) > 0
                except Exception:
                    pass
                return False
        except Exception:
            return False

    # def check_wifi_bluetooth(self):
    #     result = {}
    #
    #     # Wi-Fi
    #     rc, out, _ = self.run_adb(["shell", "settings", "get", "global", "wifi_on"])
    #     wifi = (out.strip() == "1")
    #     result["wifi"] = wifi
    #
    #     # Bluetooth
    #     rc, out, _ = self.run_adb(["shell", "settings", "get", "global", "bluetooth_on"])
    #     bluetooth = (out.strip() == "1")
    #     result["bluetooth"] = bluetooth
    #
    #     return result
