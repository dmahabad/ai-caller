import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server.common.storage import data_directory


class DataDirectoryTests(unittest.TestCase):
    def home(self, home):
        env = {k: v for k, v in os.environ.items() if k != 'PHONE_DATA_DIR'}
        return mock.patch.dict(os.environ, {**env, 'HOME': home}, clear=True)

    def test_old_default_folder_moves_to_new_name_once(self):
        with tempfile.TemporaryDirectory() as home, self.home(home):
            legacy = Path(home) / '.local/share/phone-call-gateway'
            (legacy / 'devices').mkdir(parents=True)
            (legacy / 'devices/pair-keys.json').write_text('{}')
            path = data_directory()
            self.assertEqual(path, Path(home) / '.local/share/ai-caller')
            self.assertTrue((path / 'devices/pair-keys.json').exists())
            self.assertFalse(legacy.exists())
            self.assertEqual(data_directory(), path)

    def test_existing_new_folder_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as home, self.home(home):
            new = Path(home) / '.local/share/ai-caller'; new.mkdir(parents=True)
            legacy = Path(home) / '.local/share/phone-call-gateway'; legacy.mkdir(parents=True)
            self.assertEqual(data_directory(), new)
            self.assertTrue(legacy.exists())

    def test_configured_folder_wins(self):
        with tempfile.TemporaryDirectory() as home, self.home(home), \
                mock.patch.dict(os.environ, {'PHONE_DATA_DIR': home + '/custom'}):
            self.assertEqual(data_directory(), Path(home) / 'custom')


if __name__ == '__main__':
    unittest.main()
