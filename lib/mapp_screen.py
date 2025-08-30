#!/usr/bin/env python3

try:
    from lib.config_handler import ConfigHandler

except ImportError as imp_err:
    print('There was an error importing files - From %s' % __file__)
    print('\n---{{{ Failed - ' + format(imp_err) + ' }}}---\n')
    raise


class MappScreen:

    def __init__(self, app, screen):
        self.app = app
        self.LCT = ConfigHandler().get_mapp_locators(screen, self.app.device_os)

    def _map_value(self, android, ios):
        return {
            'android': android,
            'ios': ios
        }.get(self.app.device_os)
