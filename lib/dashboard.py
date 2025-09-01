try:
    from lib.mapp_screen import MappScreen
    from corelib.logger import Logger
    from locators import dashboard_screen as locators
    from corelib.speaker_checker import run_speaker_test
    from corelib.camera_checker import compare_two_screenshot
    import logging
    from pathlib import Path
    from datetime import datetime

except ImportError as imp_err:
    print('There was an error importing files - From %s' % __file__)
    print('\n---{{{ Failed - ' + format(imp_err) + ' }}}---\n')
    raise


class Dashboard:
    """
    Handle initial screens and login screen
    """
    def __init__(self, app):
        self.app = app
        self.LCT = locators
        self.logger = Logger(name="benchmark_app", level=logging.DEBUG, filename="apphandler.log", dir_name="logs")
    
    
    def start_benchmark_app(self):
        self.app.desired_caps.update(appPackage='com.innova.benchmark',
                                         appActivity='com.innova.benchmark.views.activities.MainActivity',
                                         autoGrantPermissions=True)
        self.app.start_app()

    def start_test(self):
        if self.app.wait_visibility_of_element_located(self.LCT.RUN_ANYWAY_BTN):
            self.app.tap(self.LCT.RUN_ANYWAY_BTN)

    def check_touch_point(self, use_random_coordinates=True):
        if self.app.wait_visibility_of_all_elements_located(self.LCT.TOUCH_POINTS):
                self.app.tap_by_coordinates()
            # Tap các touch points với random coordinates
                for i in range(1, 6):
                    touch_point_locator = f"{self.LCT.TOUCH_POINTS}[{i}]"
                    if use_random_coordinates:
                        self.app.tap_with_random_offset(touch_point_locator)
                    else:
                        self.app.tap(touch_point_locator)

    def check_multi_touch(self, use_random_coordinates=True):
        """
        Multi-touch test với option random coordinates
        :param use_random_coordinates: (bool) True để random coordinates trong bounds
        """
        if self.app.wait_visibility_of_element_located(self.LCT.MULTI_TOUCH):
            if use_random_coordinates:
                self.app.multi_touch_five_fingers_random(self.LCT.MULTI_TOUCH)
            else:
                self.app.multi_touch_five_fingers(self.LCT.MULTI_TOUCH)


    def check_back_camera(self, is_good = True):
        if self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_BTN):
            self.app.tap(self.LCT.SNAPSHOT_BTN)
            if is_good:
                self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_CONFIRM_YES)
                self.app.tap(self.LCT.SNAPSHOT_CONFIRM_YES)
            else:
                self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_CONFIRM_NO)
                self.app.tap(self.LCT.SNAPSHOT_CONFIRM_NO)

    def check_front_camera(self, is_good = True):
        if self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_BTN):
            self.app.tap(self.LCT.SNAPSHOT_BTN)
            if is_good:
                self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_CONFIRM_YES)
                self.app.tap(self.LCT.SNAPSHOT_CONFIRM_YES)
            else:
                self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_CONFIRM_NO)
                self.app.tap(self.LCT.SNAPSHOT_CONFIRM_NO)


    def check_back_light(self):
        if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_YES):
            if self.app.is_brightness_increasing():
                self.app.tap(self.LCT.CONFIRM_YES)
            else:
                raise RuntimeError("Brightness check failed: screen brightness did not increase as expected")

    def check_flash_light(self):
        if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_YES):
            if self.app.check_flashlight():
                self.app.tap(self.LCT.CONFIRM_YES)
            else:
                raise RuntimeError("Flashlight check failed: Flashlight is OFF when it should be ON")


    def check_speaker(self, is_speaker_active = True):
        if is_speaker_active:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_YES):
                self.app.tap(self.LCT.CONFIRM_YES)
        else:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_NO):
                self.app.tap(self.LCT.CONFIRM_NO)

    def check_voice_recorder(self, is_playback = True):
        if is_playback:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_YES):
                self.app.tap(self.LCT.CONFIRM_YES)
        else:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_NO):
                self.app.tap(self.LCT.CONFIRM_NO)

    def check_back_camera_ver2(self):
        if self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_BTN):
            snapbtn_element = self.app.get_element(self.LCT.SNAPSHOT_BTN)

            # Prepare temp screenshot directory at project root
            project_root = Path(__file__).resolve().parent.parent
            temp_dir = project_root / "temp_screenshot"
            temp_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            preview_path = temp_dir / f"preview_{ts}.png"
            captured_path = temp_dir / f"captured_{ts}.png"

            # Save preview screenshot
            try:
                self.app.driver.save_screenshot(str(preview_path))
            except Exception:
                # fallback: if save_screenshot signature differs, try get_screenshot_as_file
                try:
                    self.app.driver.get_screenshot_as_file(str(preview_path))
                except Exception as e:
                    self.logger.warning(f"Failed to save preview screenshot: {e}")

            # Trigger snapshot
            self.app.tap(snapbtn_element)

            # Wait for confirm dialog and capture screenshot after tap
            if self.app.wait_visibility_of_element_located(self.LCT.YES_NO_DIALOG):
                yn_dialog_element = self.app.get_element(self.LCT.YES_NO_DIALOG)
                try:
                    self.app.driver.save_screenshot(str(captured_path))
                except Exception:
                    try:
                        self.app.driver.get_screenshot_as_file(str(captured_path))
                    except Exception as e:
                        self.logger.warning(f"Failed to save captured screenshot: {e}")

                # Run comparison
                cmp = compare_two_screenshot(
                    preview_screenshot=preview_path,
                    snapbtn_element=snapbtn_element,
                    captured_screenshot=captured_path,
                    yn_dialog_element=yn_dialog_element,
                    threshold_ssim=0.5
                )

                self.logger.info(f"Camera compare result: ssim={cmp['ssim']:.4f} ssim_pass={cmp['ssim_pass']} template_pass={cmp['template_pass']} overall_pass={cmp['passed']}")

                if cmp['passed']:
                    # remove temp screenshots on pass
                    try:
                        if preview_path.exists():
                            preview_path.unlink()
                        if captured_path.exists():
                            captured_path.unlink()
                    except Exception as rm_ex:
                        self.logger.warning(f"Failed to remove temp screenshots: {rm_ex}")
                    # accept result in app
                    self.app.tap(self.LCT.SNAPSHOT_CONFIRM_YES)
                else:
                    # keep screenshots for later collection and raise to trigger crash handler
                    raise RuntimeError("Back camera comparison failed - keeping screenshots for diagnostics")
            else:
                raise RuntimeError("Snapshot confirm dialog not shown")


    def check_front_camera_ver2(self, is_good = True):
        if self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_BTN):
            snapbtn_element = self.app.get_element(self.LCT.SNAPSHOT_BTN)

            # Prepare temp screenshot directory at project root
            project_root = Path(__file__).resolve().parent.parent
            temp_dir = project_root / "temp_screenshot"
            temp_dir.mkdir(parents=True, exist_ok=True)

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            preview_path = temp_dir / f"preview_{ts}.png"
            captured_path = temp_dir / f"captured_{ts}.png"

            # Save preview screenshot
            try:
                self.app.driver.save_screenshot(str(preview_path))
            except Exception:
                # fallback: if save_screenshot signature differs, try get_screenshot_as_file
                try:
                    self.app.driver.get_screenshot_as_file(str(preview_path))
                except Exception as e:
                    self.logger.warning(f"Failed to save preview screenshot: {e}")

            # Trigger snapshot
            self.app.tap(snapbtn_element)

            # Wait for confirm dialog and capture screenshot after tap
            if self.app.wait_visibility_of_element_located(self.LCT.YES_NO_DIALOG):
                yn_dialog_element = self.app.get_element(self.LCT.YES_NO_DIALOG)
                try:
                    self.app.driver.save_screenshot(str(captured_path))
                except Exception:
                    try:
                        self.app.driver.get_screenshot_as_file(str(captured_path))
                    except Exception as e:
                        self.logger.warning(f"Failed to save captured screenshot: {e}")

                # Run comparison
                cmp = compare_two_screenshot(
                    preview_screenshot=preview_path,
                    snapbtn_element=snapbtn_element,
                    captured_screenshot=captured_path,
                    yn_dialog_element=yn_dialog_element,
                    threshold_ssim=0.5
                )

                self.logger.info(f"Camera compare result: ssim={cmp['ssim']:.4f} ssim_pass={cmp['ssim_pass']} template_pass={cmp['template_pass']} overall_pass={cmp['passed']}")

                if cmp['passed']:
                    # remove temp screenshots on pass
                    try:
                        if preview_path.exists():
                            preview_path.unlink()
                        if captured_path.exists():
                            captured_path.unlink()
                    except Exception as rm_ex:
                        self.logger.warning(f"Failed to remove temp screenshots: {rm_ex}")
                    # accept result in app
                    self.app.tap(self.LCT.SNAPSHOT_CONFIRM_YES)
                else:
                    # keep screenshots for later collection and raise to trigger crash handler
                    raise RuntimeError("Back camera comparison failed - keeping screenshots for diagnostics")
            else:
                raise RuntimeError("Snapshot confirm dialog not shown")

    def check_speaker_ver2(self):
        if self.app.wait_visibility_of_element_located(self.LCT.YES_NO_DIALOG):
            if run_speaker_test():
                self.app.tap(self.LCT.CONFIRM_YES)
            else:
                raise RuntimeError("Speaker does not perform")


    def check_voice_recorder_ver2(self, is_playback = True):
        if self.app.wait_visibility_of_element_located(self.LCT.YES_NO_DIALOG):
            if run_speaker_test():
                self.app.tap(self.LCT.CONFIRM_YES)
            else:
                raise RuntimeError("Speaker does not perform")

    def check_headset(self):
        if self.app.wait_visibility_of_element_located(self.LCT.HEADSET_DIALOG, inverse=True):
            if not self.app.is_headset_plugged():
                raise RuntimeError(f"Precondition failed: Headset check returned False")


    def check_sd_card(self):
        if self.app.wait_visibility_of_element_located(self.LCT.SD_CARD_DIALOG, inverse=True):
            if not self.app.is_sdcard_mounted():
                raise RuntimeError(f"Precondition failed: SD card check returned False")


    def check_wifi(self):
        if self.app.wait_visibility_of_element_located(self.LCT.WIFI_DIALOG, inverse=True):
            if not self.app.is_wifi_enabled():
                raise RuntimeError(f"Precondition failed: Wifi check returned False")


    def check_bluetooth(self):
        if self.app.wait_visibility_of_element_located(self.LCT.BLUETOOTH_DIALOG, inverse=True):
            if not self.app.is_bluetooth_enabled():
                raise RuntimeError(f"Precondition failed: Bluetooth check returned False")


    def get_status(self):
        if self.app.wait_visibility_of_element_located(self.LCT.BACK_BTN, timeout = 75):
        # time.sleep(75)
            keys = [
                "Touch Point",
                "Multi-Touch",
                "Back Camera",
                "Front Camera",
                "Backlight",
                "Flashlight",
                "Speaker",
                "Voice Recorder",
                "Headset",
                "SD-Card",
                "Wifi",
                "Bluetooth",
                "Battery Charging"
            ]
            result = {}
            for idx, key in enumerate(keys, start=1):
                result[key] = self.app.get_text(f"{self.LCT.FUNC_STATUS}[{idx}]")
            return result
        return {}


