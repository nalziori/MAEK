"""Read-only loopback proxy for the existing Unity camera bridge."""
import json
import re
import urllib.request


def fetch(path):
    with urllib.request.urlopen('http://127.0.0.1:8765' + path, timeout=2) as response:
        data = response.read(8_000_001)
    if len(data) > 8_000_000:
        raise ValueError('camera payload too large')
    return data


def camera_state(fetcher=fetch):
    state = json.loads(fetcher('/api/camera'))
    online = state.get('connected') is True
    preview = state.get('preview') if online else None
    if preview and not re.fullmatch(r'/api/frame/[A-Za-z0-9_.~-]+', preview.get('url', '')):
        raise ValueError('invalid frame URL')
    return {'connected': online, 'sessionId': state.get('sessionId'),
                'ageSeconds': state.get('ageSeconds'), 'preview': preview,
                'activePipe': state.get('activePipe') or (state.get('telemetry') or {}).get('activePipe')}


def serve(handler):
    path = handler.path.split('?')[0]
    try:
        if path == '/api/live-camera/state':
            return handler.reply(200, camera_state())
        match = re.fullmatch(r'/api/live-camera/frame/([A-Za-z0-9_.~-]{1,160})', path)
        if not match:
            return handler.send_error(404)
        raw = fetch('/api/frame/' + match[1])
        handler.send_response(200)
        handler.send_header('Content-Type', 'image/png')
        handler.send_header('Content-Length', str(len(raw)))
        handler.send_header('Cache-Control', 'no-store')
        handler.end_headers()
        handler.wfile.write(raw)
    except (OSError, ValueError):
        handler.reply(503, {'connected': False, 'error': 'camera_unavailable'})
