try:
    from lib.mapp_screen import MappScreen
    from corelib.log_config import get_logger
    import logging

except ImportError as imp_err:
    print('There was an error importing files - From %s' % __file__)
    print('\n---{{{ Failed - ' + format(imp_err) + ' }}}---\n')
    raise


class Dashboard(MappScreen):
    """
    Handle initial screens and login screen
    """
    def __init__(self, app):
        super().__init__(app=app, screen='dashboard')
        self.logger = get_logger(name="benchmark_app", level=logging.DEBUG, filename="apphandler.log", dir_name="logs")
    
    
    def start_benchmark_app(self):
        if self.app.device_os == 'ios':
            pass
        else:
            self.app.desired_caps.update(appPackage='com.innova.benchmark',
                                         appActivity='com.innova.benchmark.views.activities.MainActivity',
                                         autoGrantPermissions=True)
        self.app.start_app()

    def start_test(self):
        if self.app.wait_visibility_of_element_located(self.LCT.RUN_ANYWAY_BTN):
            self.app.tap(self.LCT.RUN_ANYWAY_BTN)

    # def turn_off_wifi_bluetooth(self):
    #     try:
    #         self.app.disable_wifi_bluetooth(wait_sec=1.0)
    #     except Exception as ex:
    #         self.app.logger.warning(f"Failed to disable Wi‑Fi/Bluetooth: {ex}")



    # def check_setup_status(self):
    #     return self.app.check_device_status()
    #
    # def check_wifi_bluetooth_status(self):
    #     return self.app.check_wifi_bluetooth()

    # def touch_point(self, use_random_coordinates=True):
    #     if self.app.wait_visibility_of_element_located(self.LCT.RUN_ANYWAY_BTN):
    #         self.app.tap(self.LCT.RUN_ANYWAY_BTN)
    #         # Disable Wi‑Fi and Bluetooth right after pressing "Run Anyway" (per run)
    #         try:
    #             self.app.disable_wifi_bluetooth(wait_sec=1.0)
    #         except Exception as ex:
    #             try:
    #                 self.app.logger.warning(f"Failed to disable Wi‑Fi/Bluetooth: {ex}")
    #             except Exception:
    #                 pass
    #
    #     if self.app.wait_visibility_of_all_elements_located(self.LCT.TOUCH_POINTS):
    #         self.app.tap_by_coordinates()
    #     # Tap các touch points với random coordinates
    #         for i in range(1, 6):
    #             touch_point_locator = f"{self.LCT.TOUCH_POINTS}[{i}]"
    #             if use_random_coordinates:
    #                 self.app.tap_with_random_offset(touch_point_locator)
    #             else:
    #                 self.app.tap(touch_point_locator)

    def touch_point(self, use_random_coordinates=True):
        if self.app.wait_visibility_of_all_elements_located(self.LCT.TOUCH_POINTS):
                self.app.tap_by_coordinates()
            # Tap các touch points với random coordinates
                for i in range(1, 6):
                    touch_point_locator = f"{self.LCT.TOUCH_POINTS}[{i}]"
                    if use_random_coordinates:
                        self.app.tap_with_random_offset(touch_point_locator)
                    else:
                        self.app.tap(touch_point_locator)

    def multi_touch(self, use_random_coordinates=True):
        """
        Multi-touch test với option random coordinates
        :param use_random_coordinates: (bool) True để random coordinates trong bounds
        """
        if self.app.wait_visibility_of_element_located(self.LCT.MULTI_TOUCH):
            if use_random_coordinates:
                self.app.multi_touch_five_fingers_random(self.LCT.MULTI_TOUCH)
            else:
                self.app.multi_touch_five_fingers(self.LCT.MULTI_TOUCH)


    def back_camera(self, is_good = True):
        if self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_BTN):
            self.app.tap(self.LCT.SNAPSHOT_BTN)
            if is_good:
                self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_CONFIRM_YES)
                self.app.tap(self.LCT.SNAPSHOT_CONFIRM_YES)
            else:
                self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_CONFIRM_NO)
                self.app.tap(self.LCT.SNAPSHOT_CONFIRM_NO)

    def front_camera(self, is_good = True):
        if self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_BTN):
            self.app.tap(self.LCT.SNAPSHOT_BTN)
            if is_good:
                self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_CONFIRM_YES)
                self.app.tap(self.LCT.SNAPSHOT_CONFIRM_YES)
            else:
                self.app.wait_visibility_of_element_located(self.LCT.SNAPSHOT_CONFIRM_NO)
                self.app.tap(self.LCT.SNAPSHOT_CONFIRM_NO)
    def back_light(self, is_bright = True):
        if is_bright:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_YES):
                self.app.tap(self.LCT.CONFIRM_YES)
        else:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_NO):
                self.app.tap(self.LCT.CONFIRM_NO)

    def flash_light(self, is_enabled=True):
        if is_enabled:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_YES):
                self.app.tap(self.LCT.CONFIRM_YES)
        else:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_NO):
                self.app.tap(self.LCT.CONFIRM_NO)

    def speaker(self, is_speaker_active = True):
        if is_speaker_active:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_YES):
                self.app.tap(self.LCT.CONFIRM_YES)
        else:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_NO):
                self.app.tap(self.LCT.CONFIRM_NO)

    def voice_recorder(self, is_playback = True):
        if is_playback:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_YES):
                self.app.tap(self.LCT.CONFIRM_YES)
        else:
            if self.app.wait_visibility_of_element_located(self.LCT.CONFIRM_NO):
                self.app.tap(self.LCT.CONFIRM_NO)

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


