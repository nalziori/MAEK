"""Read actual catalogue telemetry, then send only pause/resume via the existing UI."""
import argparse
import hashlib
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--base', default='http://127.0.0.1:8765')
parser.add_argument('--timeout', type=int, default=1200)
parser.add_argument('--output', type=Path)
parser.add_argument('--unity-project', type=Path,
                    help='Optional cached Unity project; executed runtime sources must match this checkout')
args = parser.parse_args()
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
BASE = args.base.rstrip('/')
OUT = args.output or ROOT / 'visualization/inspection_scenarios/dashboard' / (
    'live-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {'origin': BASE + '/dashboard', 'kind': 'actual Unity Play catalogue; real HTTP producer; no injected telemetry',
          'commands': [], 'screens': {}, 'errors': [], 'responses': [], 'completed': False}


def emit(message, **data):
    print(json.dumps({'message': message, **data}, ensure_ascii=True), flush=True)


def state():
    with urllib.request.urlopen(BASE + '/api/state', timeout=5) as response:
        return json.load(response)


def summary(s):
    t = s.get('telemetry') or {}
    return {key: s.get(key) for key in ('sessionId', 'connected', 'ageSeconds')} | {
        key: t.get(key) for key in ('phase', 'active', 'paused', 'scenarioId', 'activePipe',
                                  'analysedPipes', 'plannedPipes', 'captures', 'expectedCaptures')}


def catalogue(s):
    t = s.get('telemetry') or {}
    return (s.get('connected') is True and t.get('active') is True
            and t.get('plannedPipes', 0) == 247
            and s.get('ageSeconds', 999) <= 5
            and len(t.get('access', [])) == 247
            and not re.fullmatch(r'S\d\d', str(t.get('scenarioId', ''))))


def wait_ack(command, paused, session):
    deadline = time.monotonic() + 30
    transitions = []
    previous = None
    while time.monotonic() < deadline:
        s = state()
        if s.get('sessionId') != session:
            raise RuntimeError('Session changed during pause/resume QA')
        last = s.get('lastCommand') or {}
        item = {'commandId': last.get('commandId'), 'command': last.get('command'),
                'status': last.get('status'), 'paused': (s.get('telemetry') or {}).get('paused')}
        if item != previous:
            transitions.append(item)
            previous = item
        if last.get('command') == command and last.get('status') == 'applied' and item['paused'] is paused:
            REPORT['commands'].append({'command': command, 'expectedPaused': paused,
                                       'ack': last, 'state': summary(s), 'transitions': transitions})
            emit(command + ' verified', ack=last, telemetry=summary(s))
            return s
        time.sleep(.25)
    raise TimeoutError(command + ' ACK/paused state did not agree within 30 seconds')


def capture(page, name, width, height):
    page.set_viewport_size({'width': width, 'height': height})
    page.wait_for_timeout(450)
    data = page.evaluate('''async () => {
      const flow=document.querySelector('.maek-live-flow');
      const images=[...flow.querySelectorAll('img')];
      const provenance=flow.querySelector('.maek-live-meta').textContent;
      const expected=provenance.match(/SHA-256 ([a-f0-9]{64})/i)?.[1];
      let actual=null;
      if(images[1]?.src.startsWith('blob:')) {
        const bytes=await(await fetch(images[1].src)).arrayBuffer();
        actual=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))]
          .map(v=>v.toString(16).padStart(2,'0')).join('');
      }
      return {connection:document.querySelector('.maek-bridge-status').textContent,
        pipe:flow.querySelector('h2').textContent,flight:flow.querySelector('.pipe-context p').textContent,
        provenance,expectedHash:expected,actualHash:actual,
        hashMatches:expected&&actual?expected===actual:null,
        canvasHidden:flow.querySelector('canvas').hidden,
        images:images.map(i=>({src:i.getAttribute('src'),hidden:i.hidden,
          width:i.naturalWidth,height:i.naturalHeight})),
        viewportWidth:innerWidth,documentWidth:document.documentElement.scrollWidth,
        commands:[...document.querySelectorAll('#maek-bridge button')]
          .map(b=>({text:b.textContent,disabled:b.disabled}))};
    }''')
    page.screenshot(path=str(OUT / (name + '.png')), full_page=True)
    REPORT['screens'][name] = data
    emit('captured ' + name, hashMatches=data['hashMatches'], connection=data['connection'])


paths = [ROOT / 'maek/inspection_bridge.py', ROOT / 'maek/inspection_dashboard.py',
         ROOT / 'maek/camera/segment.py']
paths += list((ROOT / 'maek/web').glob('existing-dashboard-adapter.*'))
paths += [ROOT / 'dashboard' / n for n in
          ('index.html', 'operations.js', 'operations.css', 'operations-data.js', 'inspection-evidence.js')]
assets = ROOT / 'unity/MAEKInspection/Assets/MAEK'
paths += [p for p in (assets / 'Scripts').glob('*.cs') if p.name != 'MAEKStandaloneRuntime.cs']
paths += [assets / n for n in ('Editor/VerifyInspectionPlayMode.cs',
                              'Scenes/MAEKInspectionDemo.unity', 'Source/site_inspection_tour.json')]
paths.append(Path(__file__).resolve())
def hashes():
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
REPORT['sourceHashes'] = hashes()
if args.unity_project:
    for p in paths:
        if not p.is_relative_to(assets):
            continue
        counterpart = args.unity_project / 'Assets/MAEK' / p.relative_to(assets)
        if p.suffix == '.cs':
            assert p.read_text(encoding='utf-8-sig').strip() == counterpart.read_text(encoding='utf-8-sig').strip(), p
        else:
            assert p.read_bytes() == counterpart.read_bytes(), p
    REPORT['executedUnityProject'] = str(args.unity_project.resolve())
    REPORT['executedRuntimeMatchesCheckout'] = True
browser = None
page = None
session = None
pause_sent = False
resumed = False
try:
    from maek.inspection_bridge import inject_adapter
    served = {'/dashboard': inject_adapter((ROOT / 'dashboard/index.html').read_bytes())}
    served.update({'/dashboard/' + n: (ROOT / 'dashboard' / n).read_bytes()
                   for n in ('operations.js', 'operations.css', 'operations-data.js', 'inspection-evidence.js')})
    served.update({'/api/' + p.name: p.read_bytes()
                   for p in (ROOT / 'maek/web').glob('existing-dashboard-adapter.*')})
    REPORT['httpSourceHashes'] = {}
    for route, expected in served.items():
        with urllib.request.urlopen(BASE + route, timeout=10) as response:
            raw = response.read()
        assert raw == expected, 'HTTP server is not serving this checkout: ' + route
        REPORT['httpSourceHashes'][route] = hashlib.sha256(raw).hexdigest()
    deadline = time.monotonic() + args.timeout
    next_notice = 0
    while time.monotonic() < deadline:
        try:
            current = state()
            if (catalogue(current) and (current.get('telemetry') or {}).get('paused') is False
                    and current.get('analyses') and (current.get('telemetry') or {}).get('mappedFindings')):
                REPORT['initial'] = summary(current)
                REPORT['coverage'] = current['telemetry']['coverage']
                REPORT['mapping'] = current['telemetry']['mappedFindings']
                REPORT['access'] = {'rows': len(current['telemetry']['access']),
                    'zeroScheduled': sum(r['scheduledImages'] == 0 for r in current['telemetry']['access'])}
                session = current['sessionId']
                emit('actual catalogue connected', telemetry=summary(current))
                break
            if time.monotonic() >= next_notice:
                emit('waiting for actual active catalogue', telemetry=summary(current))
                next_notice = time.monotonic() + 30
        except (OSError, ValueError) as error:
            if time.monotonic() >= next_notice:
                emit('waiting for bridge', error=str(error))
                next_notice = time.monotonic() + 30
        time.sleep(2)
    else:
        raise TimeoutError('No real active 247-pipe catalogue with analysis/mapping before timeout')

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel='msedge',
            headless=True, args=['--disable-gpu', '--renderer-process-limit=1'])
        try:
            page = browser.new_page(viewport={'width': 1280, 'height': 900})
            page.on('pageerror', lambda e: REPORT['errors'].append({'type': 'exception', 'message': str(e)}))
            page.on('console', lambda m: REPORT['errors'].append(
                {'type': 'console', 'message': m.text, 'location': m.location}) if m.type == 'error' else None)
            page.on('response', lambda r: REPORT['responses'].append(
                {'url': r.url, 'status': r.status}) if r.status >= 400 else None)
            page.goto(BASE + '/dashboard', wait_until='domcontentloaded', timeout=30000)
            page.locator('#maek-bridge').wait_for(timeout=15000)
            page.get_by_role('button', name='일시 정지', exact=True).wait_for(timeout=15000)
            page.wait_for_function("[...document.querySelectorAll('#maek-bridge button')].some(b=>b.textContent==='일시 정지'&&!b.disabled)", timeout=15000)
            before = state()
            if not catalogue(before) or before.get('sessionId') != session:
                raise RuntimeError('Catalogue ended/changed before UI action; no command sent')
            page.get_by_role('button', name='일시 정지', exact=True).click()
            pause_sent = True
            wait_ack('pause', True, session)
            # A pause gives the last real analysis enough time to finish image/hash validation.
            page.wait_for_function("(()=>{const i=document.querySelectorAll('.maek-live-flow img')[1];return i&&!i.hidden&&i.naturalWidth>0&&i.src.startsWith('blob:')})()", timeout=20000)
            capture(page, 'desktop-paused', 1280, 900)
            capture(page, 'mobile-paused', 390, 844)
            page.get_by_role('button', name='재개', exact=True).click()
            wait_ack('resume', False, session)
            resumed = True
            initial_position = before['telemetry']['position']
            motion_deadline = time.monotonic() + 30
            while time.monotonic() < motion_deadline:
                moving = state()
                if (catalogue(moving) and moving['sessionId'] == session
                        and moving['telemetry']['position'] != initial_position):
                    REPORT['positionUpdated'] = True
                    REPORT['motion'] = {'before': initial_position, 'after': moving['telemetry']['position']}
                    break
                time.sleep(.5)
            capture(page, 'mobile-resumed', 390, 844)
            capture(page, 'desktop-resumed', 1280, 900)
            REPORT['completed'] = (len(REPORT['commands']) == 2
                and REPORT.get('positionUpdated') is True
                and all('연결됨' in s['connection'] for s in REPORT['screens'].values())
                and all(s['hashMatches'] is True for s in REPORT['screens'].values())
                and all(s['documentWidth'] == s['viewportWidth'] for s in REPORT['screens'].values())
                and not any(e['type'] == 'exception' for e in REPORT['errors']))
        finally:
            # Never leave the catalogue paused if an evidence assertion failed after the click.
            if pause_sent and not resumed and page and not page.is_closed():
                try:
                    recovery = state()
                    if recovery.get('sessionId') == session and (recovery.get('telemetry') or {}).get('paused') is True:
                        page.get_by_role('button', name='재개', exact=True).click(timeout=5000)
                        wait_ack('resume', False, session)
                        REPORT['recoveredResume'] = True
                except Exception as error:  # noqa: BLE001 - retain cleanup error in failure report
                    REPORT['resumeRecoveryError'] = str(error)
            browser.close()
            REPORT['headlessBrowserClosed'] = True
except Exception as error:  # noqa: BLE001 - always emit a failed integration report
    REPORT['error'] = str(error)
    emit('QA stopped', error=str(error))
finally:
    REPORT['sourcesUnchanged'] = REPORT['sourceHashes'] == hashes()
    REPORT['status'] = 'PASS' if REPORT['completed'] and REPORT['sourcesUnchanged'] else 'FAIL'
    (OUT / 'report.json').write_text(json.dumps(REPORT, ensure_ascii=False, indent=2), encoding='utf-8')
    emit('QA report saved', path=str(OUT / 'report.json'), completed=REPORT['completed'])

sys.exit(0 if REPORT['status'] == 'PASS' else 1)
