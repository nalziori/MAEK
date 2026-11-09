"""Start the repository's local RGB, worker UT and thermal/dashboard services."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.request
import webbrowser


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--services-only', action='store_true', help='Keep services running for Unity Editor verification/build.')
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    player = root / 'unity/MAEKInspection/ThermalOutput/Player/MAEK_Player.exe'
    if not args.services_only and not player.is_file():
        parser.error('Build the player first: Unity menu MAEK > Thermal > Verify and build thermal V6. Use --services-only while building.')
    logs = root / 'data/unity_sensor_logs' / time.strftime('%Y%m%d-%H%M%S')
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1',
               MAEK_THERMAL_ENDPOINT='http://127.0.0.1:8894', MAEK_UT_ENDPOINT='http://127.0.0.1:8766/ut')
    owned, handles = [], []

    def get(url):
        with urllib.request.urlopen(url, timeout=2) as response:
            return json.load(response)

    def ensure(name, url, command, valid):
        try:
            if valid(get(url)):
                return
            raise RuntimeError(f'Unexpected service at {url}; close it before starting this demo.')
        except OSError:
            pass
        handle = (logs / (name + '.log')).open('w', encoding='utf-8')
        handles.append(handle)
        process = subprocess.Popen([sys.executable, *command], cwd=root, env=env, stdout=handle, stderr=handle,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        owned.append(process)
        for _ in range(180):
            if process.poll() is not None:
                raise RuntimeError(f'{name} stopped; see {logs}')
            try:
                if valid(get(url)):
                    return
            except OSError:
                pass
            time.sleep(.2)
        raise RuntimeError(f'{name} startup timed out; see {logs}')

    try:
        source_hash = hashlib.sha256((root / 'UT/examples/ascan.npz').read_bytes()).hexdigest()
        package_hash = hashlib.sha256((root / 'UT/manifest.json').read_bytes()).hexdigest()
        ensure('ut', 'http://127.0.0.1:8766/health', ['scripts/serve_worker_ut.py', '--port', '8766'],
               lambda d: d.get('sourceSha256') == source_hash and d.get('packageSha256') == package_hash)
        ensure('dashboard', 'http://127.0.0.1:8894/api/thermal', ['scripts/serve_ut_dashboard.py', '--port', '8894'],
               lambda d: d.get('schemaVersion') == 1 and isinstance(d.get('pipes'), dict))
        ensure('rgb', 'http://127.0.0.1:8765/health', ['-m', 'maek.inspection_bridge', '--port', '8765'],
               lambda d: d.get('status') == 'ok')
        print('Dashboard: http://127.0.0.1:8894/index.html?tab=home&pipe=BF1-Q005', flush=True)
        if args.services_only:
            print('Services ready. Keep this terminal open; Ctrl+C stops only services started here.', flush=True)
            while True:
                time.sleep(1)
        webbrowser.open('http://127.0.0.1:8894/index.html?tab=home&pipe=BF1-Q005')
        return subprocess.call([str(player)], cwd=root, env=env)
    except KeyboardInterrupt:
        return 0
    finally:
        for process in reversed(owned):
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        for handle in handles:
            handle.close()


if __name__ == '__main__':
    sys.exit(main())
