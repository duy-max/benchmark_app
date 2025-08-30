try:
    from corelib import utils
    from pathlib import Path

except ImportError as imp_err:
    print('There was an error importing files - From %s' % __file__)
    print('\n---{{{ Failed - ' + format(imp_err) + ' }}}---\n')
    raise


class ConfigHandler:
    def __init__(self):
        project_root = Path(__file__).resolve().parent.parent
        self.CONFIG_DIR = project_root / 'config'
        self.LIB_DIR = project_root / 'lib'

    def get_mapp_locators(self, screen, device_os):
        full_locators = utils.read_config_file(f'{self.CONFIG_DIR}/mapp_locators/{screen.lower()}.yaml')
        locators = {
            locator_key: locator_value.get(device_os) if isinstance(locator_value, dict) else locator_value
            for locator_key, locator_value in full_locators.items()
        }
        return utils.dict_to_class_object(locators)
