import hashlib
import json

import pytest

from maek.unity_model_feed import UnityModelFeed


class Thermal:
    def snapshot(self): return {'pipes': {}}


class Models:
    def __init__(self): self.calls = 0
    def analyse(self, kind, raw):
        assert kind == 'rgb' and raw == b'camera-png'
        self.calls += 1
        return {'regions': [], 'analysis_summary': '미검출'}


def test_live_camera_latest_frames_are_inferred_without_pipe_assignment():
    raw = b'camera-png'
    state = {'connected': True, 'sessionId': 'live', 'analyses': [], 'preview': {
        'frameId': 'frame1', 'url': '/api/frame/frame1', 'imageSha256': hashlib.sha256(raw).hexdigest()}}
    models = Models()
    feed = UnityModelFeed(models, Thermal(), lambda path: json.dumps(state).encode() if path in ('/api/state','/api/camera') else raw)
    feed.step(); feed.step()
    assert models.calls == 1
    assert feed.snapshot()['liveRGB']['requestId'] == 'frame1'
    assert feed.snapshot()['pipes'] == {}
    state['preview']['frameId'] = 'frame9'
    feed.step()
    assert models.calls == 2 and feed.snapshot()['liveRGB']['requestId'] == 'frame9'
    state['connected'] = False
    feed.step()
    assert feed.snapshot()['liveRGB'] is None


def test_live_camera_drops_result_if_session_changes_during_inference():
    raw = b'camera-png'
    state = {'connected': True, 'sessionId': 'live', 'analyses': [], 'preview': {
        'frameId': 'frame1', 'url': '/api/frame/frame1', 'imageSha256': hashlib.sha256(raw).hexdigest()}}
    class ChangingModels(Models):
        def analyse(self, kind, raw):
            state['sessionId'] = 'new'
            return super().analyse(kind, raw)
    feed = UnityModelFeed(ChangingModels(), Thermal(), lambda path: json.dumps(state).encode() if path in ('/api/state','/api/camera') else raw)
    feed.step()
    assert feed.snapshot()['liveRGB'] is None


def test_expired_archive_frame_cannot_cancel_live_inference():
    from urllib.error import HTTPError
    raw = b'camera-png'
    state = {'connected': True, 'sessionId': 'live', 'preview': {'frameId': 'current',
        'url': '/api/frame/current', 'imageSha256': hashlib.sha256(raw).hexdigest()},
        'analyses': [{'pipeId': 'P','requestId': 'old','frameUrl': '/api/frame/old','imageSha256': '0'*64}]}
    def fetch(path):
        if path in ('/api/state','/api/camera'): return json.dumps(state).encode()
        if path.endswith('/old'): raise HTTPError(path,404,'expired',None,None)
        return raw
    feed = UnityModelFeed(Models(),Thermal(),fetch)
    feed.step()
    assert feed.snapshot()['liveRGB']['requestId'] == 'current'
    assert feed.snapshot()['connected']['rgb'] is True


def test_compact_snapshot_omits_image_payload_without_mutating_evidence():
    feed = UnityModelFeed(Models(),Thermal())
    feed.pipes = {'P': {'rgb': {'src':'large-png', 'analysis_summary':'result'}}}
    assert 'src' not in feed.snapshot(compact=True)['pipes']['P']['rgb']
    assert feed.snapshot()['pipes']['P']['rgb']['src'] == 'large-png'


def test_unity_capture_is_automatic_deduplicated_and_hash_bound():
    raw = b'camera-png'
    state = {'connected': True, 'sessionId': 'S', 'analyses': [{'pipeId': 'P', 'requestId': 'R',
        'frameUrl': '/api/frame/F', 'imageSha256': hashlib.sha256(raw).hexdigest()}]}
    def fetch(path): return json.dumps(state).encode() if path in ('/api/state','/api/camera') else raw
    models = Models(); feed = UnityModelFeed(models, Thermal(), fetch)
    feed.step(); feed.step()
    assert models.calls == 1
    assert feed.snapshot()['pipes']['P']['rgb']['requestId'] == 'R'
    state['analyses'][0]['requestId'] = 'bad'
    state['analyses'][0]['imageSha256'] = '0'*64
    feed.step()
    assert models.calls == 1 and feed.snapshot()['connected']['rgb'] is False


def test_old_session_evidence_is_removed():
    state = {'connected': True, 'sessionId': 'new', 'analyses': []}
    feed = UnityModelFeed(Models(), Thermal(), lambda _: json.dumps(state).encode())
    feed.pipes = {'P': {'rgb': {'requestId': 'old'}}}
    feed.step()
    assert 'rgb' not in feed.snapshot()['pipes']['P']


@pytest.mark.parametrize('pv_mode',[False,True])
def test_completed_capture_automatically_enters_thermal_model(tmp_path,pv_mode):
    import importlib.util
    from pathlib import Path

    from scripts.thermal_scene import ThermalStore
    spec = importlib.util.spec_from_file_location('capture_fixture', Path(__file__).with_name('test_thermal_scene_adapter.py'))
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture)
    request = fixture.request(); request['assetId'] = 'BF1-G004'
    store = ThermalStore(tmp_path)
    identity = {k:request[k] for k in ('requestId','sessionId','runId','assetId','startedAt')}
    store.event(dict(identity, sequence=0, stage='Launching'))
    store.event(dict(identity, sequence=4, stage='Analysing'))
    store.capture(request)
    class ThermalModels:
        calls = 0
        thermal_input_mode = 'pv_yolo' if pv_mode else 'baseline'
        def analyse(self, kind, raw):
            import io

            import numpy as np
            if kind == 'rgb':
                return {'analysis_summary':'same-capture RGB fixture', 'regions':[]}
            assert kind == 'thermal'
            with np.load(io.BytesIO(raw)) as z:
                assert z['current_c'].shape == ((256,320) if pv_mode else (128,160))
                assert z['roi_valid'].dtype == bool
                assert ('expected_c' in z) != pv_mode
            self.calls += 1
            if pv_mode:
                import base64

                from PIL import Image
                image=io.BytesIO();Image.fromarray(np.zeros((256,320,3),dtype='uint8')).save(image,format='PNG')
                data=image.getvalue()
                return {'analysis_summary': 'PV fixture','quality_status': 'fixture','inputSha256': hashlib.sha256(data).hexdigest(),'src': 'data:image/png;base64,'+base64.b64encode(data).decode()}
            return {'analysis_summary':'test inference', 'quality_status':'test fixture'}
    models = ThermalModels()
    feed = UnityModelFeed(models,store,lambda _: json.dumps({'connected':False}).encode())
    feed.step(); feed.step()
    assert models.calls == 1
    assert feed.snapshot()['pipes']['BF1-G004']['thermal']['requestId'] == request['requestId']
    assert feed.snapshot()['pipes']['BF1-G004']['rgb']['requestId'] == request['requestId']
    assert feed.snapshot()['connected']['rgb'] is True
    if pv_mode:
        result=feed.snapshot()['pipes']['BF1-G004']['thermal']
        assert result['inputUrl'].endswith('/model-input.png')
        assert hashlib.sha256((store.root/request['requestId']/'model-input.png').read_bytes()).hexdigest()==result['inputSha256']
    store.event(dict(identity,requestId='5'*32,runId='5'*32,startedAt='2026-11-10T00:00:00Z',sequence=0,stage='Launching'))
    feed.step()
    assert 'thermal' not in feed.snapshot()['pipes']['BF1-G004']
