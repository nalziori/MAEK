import json

import pytest

from maek.inspection_dashboard import DashboardState
from maek.live_camera import camera_state


def test_camera_snapshot_skips_expensive_network_history_and_expires():
    now = [100]
    state = DashboardState(clock=lambda:now[0])
    class History:
        def __deepcopy__(self, memo): raise AssertionError('camera copied full history')
    state.session = 's'; state.updated = 99
    state.telemetry = {'activePipe': 'P', 'access': History()}
    state.preview = {'frameId': 'f','url': '/api/frame/f'}
    state.analyses.append(History())
    result = state.camera_snapshot()
    assert result['connected'] and result['activePipe'] == 'P'
    result['preview']['url'] = 'changed'
    assert state.preview['url'] == '/api/frame/f'
    now[0] = 111
    assert state.camera_snapshot()['preview'] is None


def test_preview_is_small_and_does_not_include_full_network_or_analysis_images():
    state = {'connected': True, 'sessionId': 's', 'ageSeconds': .1,
                 'preview': {'url': '/api/frame/s_1', 'frameId': 's_1'},
                 'telemetry': {'activePipe': 'P', 'access': ['large']*100}, 'analyses': ['large']*100}
    result = camera_state(lambda _: json.dumps(state).encode())
    assert result['activePipe'] == 'P' and result['preview']['frameId'] == 's_1'
    assert 'analyses' not in result and 'telemetry' not in result
    state['connected'] = False
    assert camera_state(lambda _: json.dumps(state).encode())['preview'] is None


def test_preview_url_cannot_escape_loopback_frame_route():
    with pytest.raises(ValueError):
        camera_state(lambda _: json.dumps({'connected': True,'preview': {'url': 'https://example.com/x'}}).encode())


def test_camera_cors_is_read_only_and_limited_to_dashboard_origins():
    import io

    from maek.inspection_bridge import Handler
    class Response:
        def __init__(self, origin, path):
            self.headers={'Origin':origin}; self.path=path; self.sent={}; self.wfile=io.BytesIO()
        def send_response(self, status): pass
        def send_header(self, key, value): self.sent[key]=value
        def end_headers(self): pass
    for origin,path,allowed in [
        ('http://127.0.0.1:8878','/api/camera',True),
        ('http://localhost:8878','/api/frame/f1',True),
        ('https://example.com','/api/camera',False),
        ('http://127.0.0.1:8878','/api/state',False),
    ]:
        response=Response(origin,path)
        Handler.send_bytes(response,200,b'{}','application/json')
        assert ('Access-Control-Allow-Origin' in response.sent) == allowed
