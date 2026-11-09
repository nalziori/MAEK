import hashlib
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('sensor_launcher', ROOT / 'scripts/run_unity_sensor_demo.py')
LAUNCHER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LAUNCHER)
PACKAGE_HASH = hashlib.sha256((ROOT / 'UT/manifest.json').read_bytes()).hexdigest()
SOURCE_HASH = hashlib.sha256((ROOT / 'UT/examples/ascan.npz').read_bytes()).hexdigest()


def response(body):
    return io.BytesIO(json.dumps(body).encode())


class SensorLauncher(unittest.TestCase):
    def test_reuses_matching_services_without_starting_or_stopping_them(self):
        with patch.object(LAUNCHER.sys, 'argv', ['demo', '--services-only']), \
             patch.object(LAUNCHER.urllib.request, 'urlopen', side_effect=[
                 response({'sourceSha256': SOURCE_HASH, 'packageSha256': PACKAGE_HASH}),
                 response({'schemaVersion': 1, 'pipes': {}}),
                 response({'status': 'ok'})]), \
             patch.object(LAUNCHER.subprocess, 'Popen') as start, \
             patch.object(LAUNCHER.time, 'sleep', side_effect=KeyboardInterrupt):
            self.assertEqual(LAUNCHER.main(), 0)
            start.assert_not_called()

    def test_rejects_a_different_ut_model_at_the_expected_port(self):
        with patch.object(LAUNCHER.sys, 'argv', ['demo', '--services-only']), \
             patch.object(LAUNCHER.urllib.request, 'urlopen', return_value=response({'sourceSha256': 'wrong'})), \
             patch.object(LAUNCHER.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(RuntimeError, 'Unexpected service'):
                LAUNCHER.main()
            start.assert_not_called()

    def test_same_examples_but_different_ut_package_is_rejected(self):
        with patch.object(LAUNCHER.sys, 'argv', ['demo', '--services-only']), \
             patch.object(LAUNCHER.urllib.request, 'urlopen', return_value=response({'sourceSha256': SOURCE_HASH, 'packageSha256': 'wrong'})), \
             patch.object(LAUNCHER.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(RuntimeError, 'Unexpected service'):
                LAUNCHER.main()
            start.assert_not_called()

    def test_failed_dashboard_start_cleans_up_only_owned_ut_process(self):
        process = Mock()
        process.poll.return_value = None
        with patch.object(LAUNCHER.sys, 'argv', ['demo', '--services-only']), \
             patch.object(LAUNCHER.urllib.request, 'urlopen', side_effect=[
                 URLError('not started'), response({'sourceSha256': SOURCE_HASH, 'packageSha256': PACKAGE_HASH}),
                 response({'schemaVersion': 0})]), \
             patch.object(LAUNCHER.subprocess, 'Popen', return_value=process), \
             patch.object(LAUNCHER.time, 'sleep'):
            with self.assertRaisesRegex(RuntimeError, 'Unexpected service'):
                LAUNCHER.main()
            process.terminate.assert_called_once()
            process.wait.assert_called_once()


if __name__ == '__main__':
    unittest.main()
