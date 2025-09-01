try:
    import time
    import yaml
    import platform
    import json
    from yaml.scanner import ScannerError
    from json.decoder import JSONDecodeError

except ImportError as imp_err:
    print('There was an error importing files - From %s' % __file__)
    print('\n---{{{ Failed - ' + format(imp_err) + ' }}}---\n')
    raise



def parse_key_value(key_value, separator=':'):
    """
    Parse key value string-alike
    :param key_value: (str) key-value string
    :param separator: (str) separator/delimiter
    :return: (tuple) key and value if to_dict is False, (dict) if to_dict is True
    """
    kv = key_value.split(separator)
    return kv[0].strip(), separator.join(kv[1:]).strip()


def read_config_file(file):
    """
    Read config file, supporting config files:
    - yaml
    - json
    :param file: (str) file path
    :return: python-format of the file content
    """
    with open(file, 'r') as f:
        try:
            return yaml.load(f, Loader=yaml.UnsafeLoader)
        except ScannerError:
            try:
                return json.load(f)
            except JSONDecodeError:
                raise Exception('The config file type is not supported or the config syntax got errors.')

def get_dict_value(dictionary, path_to_key, sep='>', default=None):
    """
    Normal access to a value in dict: ` d.get('k1').get('k2').get('k3') ` or `d['k1']['k2']['k3']`
    This method provides an alternative way to get a value in dict. Usage examples:
        - get_dict_value(d, 'k1 > k2 > k3')
        - get_dict_value(d, 'k1:k2:k3', sep=':', default='')
    :param dictionary: (dict)
    :param path_to_key: (str)
    :param sep: (str) separator/delimiter
    :param default: (Any) default value if the path key is not correct
    :return: the value, return `default value` if the path key is not correct
    """
    if not path_to_key:
        return dictionary
    if isinstance(path_to_key, str):
        return get_dict_value(dictionary, path_to_key.split(sep), sep, default)
    try:
        new_dict = dictionary.get(path_to_key[0].strip())
        return get_dict_value(new_dict, path_to_key[1:], sep, default)
    except AttributeError:
        print('No data with key path available')
        return default

def dict_to_class_object(_dict):
    """
    Convert a dict to class object
    :param _dict: (dict)
    :return: (class object)
    """
    class ObjectView:
        def __init__(self, d):
            self.__dict__ = d
    return ObjectView(_dict)

def assert_value_status(actual: dict, expected: dict, msg: str):
    """
    So sánh actual vs expected.
    Nếu khác thì catch lỗi và in chi tiết.
    Nếu pass thì in ra msg.
    """
    try:
        errors = []
        for key, exp_value in expected.items():
            act_value = actual.get(key, None)
            if act_value != exp_value:
                errors.append(f"{key}: expected={exp_value}, actual={act_value}")

        if errors:
            # thay vì raise -> chủ động tạo AssertionError để catch
            raise AssertionError(f"{msg} status mismatch:\n" + "\n".join(errors))

        print(f"✅ {msg}")

    except AssertionError as e:
        print(f"❌ {e}")

