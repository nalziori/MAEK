"""Follow hash-bound Unity observations; never read evaluation truth as input."""
import base64
import hashlib
import io
import json
import threading
import time
import urllib.request

import numpy as np


class UnityModelFeed:
    def __init__(self, models, thermal, fetch=None):
        self.models, self.thermal = models, thermal
        self.fetch = fetch or self._fetch
        self.lock = threading.Lock()
        self.pipes, self.seen = {}, set()
        self.connected = {'rgb': False, 'thermal': True}
        self.errors = {}
        self.session = None
        self.live_rgb = None
        self.live_frame = None
        self.live_status = {}
        self.live_thermal = None
        self.stream_key = None

    def _fetch(self, path):
        if not path.startswith('/api/'):
            raise ValueError('Unexpected bridge frame path')
        with urllib.request.urlopen('http://127.0.0.1:8765'+path, timeout=3) as response:
            return response.read()

    def publish(self, pipe, kind, request, raw, evidence):
        evidence.update(requestId=request, sampleId=request,
            sha256=hashlib.sha256(raw).hexdigest(), source='unity_auto_model',
            quality_status=evidence.get('quality_status', '')+' · Unity 자동 입력 · 합성 시연')
        with self.lock:
            self.pipes.setdefault(pipe, {})[kind] = evidence

    def step(self):
        try:
            state = json.loads(self.fetch('/api/camera'))
            if not state.get('preview'):
                state = json.loads(self.fetch('/api/state'))
            self.live_status = {'bridgeConnected': state.get('connected'),
                'sourceFrame': (state.get('preview') or {}).get('frameId'),
                'sourceSession': state.get('sessionId'), 'observedAt': time.time()}
            self.errors.pop('rgb', None)
            self.connected['rgb'] = state.get('connected') is True
            if not self.connected['rgb']:
                with self.lock:
                    self.live_rgb = None
            if self.connected['rgb']:
                if self.session != state.get('sessionId'):
                    with self.lock:
                        for sensors in self.pipes.values():
                            sensors.pop('rgb', None)
                    self.session = state.get('sessionId')
                    self.live_frame = None
                    self.live_rgb = None
                preview = state.get('preview')
                if preview and preview.get('frameId') != self.live_frame:
                    if not preview['url'].startswith('/api/frame/'):
                        raise ValueError('Unexpected live frame URL')
                    raw = self.fetch(preview['url'])
                    if hashlib.sha256(raw).hexdigest() != preview['imageSha256']:
                        raise ValueError('Unity live frame hash mismatch')
                    started = time.perf_counter()
                    evidence = self.models.analyse('rgb', raw)
                    inference_ms = round((time.perf_counter()-started)*1000, 2)
                    evidence.pop('src', None)
                    latest = json.loads(self.fetch('/api/camera'))
                    if latest.get('connected') and latest.get('sessionId') == self.session:
                        evidence.update(source='unity_auto_model', requestId=preview['frameId'],
                            sha256=preview['imageSha256'], sessionId=self.session,
                            analysedAt=time.time(), inferenceMs=inference_ms,
                            quality_status=evidence.get('quality_status', '')+' · 현재 영상 전체 분석 · 배관 위치 정합 미확인')
                        with self.lock:
                            self.live_rgb = evidence
                            self.live_frame = preview['frameId']
                # Process only each pipe's newest capture, never build a stale inference backlog.
                newest = {}
                for row in state.get('analyses', []):
                    newest.setdefault(row.get('pipeId'), row)
                for row in newest.values():
                    pipe, request = row.get('pipeId'), row.get('requestId')
                    key = ('rgb', state.get('sessionId'), request)
                    if not pipe or not request or key in self.seen:
                        continue
                    if not row['frameUrl'].startswith('/api/frame/'):
                        raise ValueError('Unexpected frame URL')
                    try:
                        raw = self.fetch(row['frameUrl'])
                    except urllib.error.HTTPError as error:
                        if error.code in (404, 410):
                            self.seen.add(key)
                            continue
                        raise
                    if hashlib.sha256(raw).hexdigest() != row['imageSha256']:
                        raise ValueError('Unity RGB hash mismatch')
                    result = self.models.analyse('rgb', raw)
                    latest = json.loads(self.fetch('/api/state'))
                    if not latest.get('connected') or latest.get('sessionId') != self.session:
                        continue
                    self.publish(pipe, 'rgb', request, raw, result)
                    self.seen.add(key)
        except Exception as error:  # noqa: BLE001 - isolate model failures and keep the local service available.
            self.connected['rgb'] = False
            self.errors['rgb'] = type(error).__name__
        self.step_live_thermal()
        from scripts.thermal_scene import synthesize
        for pipe, observation in self.thermal.snapshot()['pipes'].items():
            result = observation.get('result')
            if not result or observation.get('stage') != 'Complete':
                with self.lock:
                    sensors = self.pipes.get(pipe, {})
                    sensors.pop('thermal', None)
                    if sensors.get('rgb', {}).get('captureSource') == 'thermal_capture':
                        sensors.pop('rgb', None)
                continue
            request = result['requestId']
            key = ('thermal', observation['sessionId'], request)
            if key in self.seen:
                continue
            try:
                root = self.thermal.root/request
                rgb_raw = (root/'rgb.png').read_bytes()
                if hashlib.sha256(rgb_raw).hexdigest() != result['rgbSha256']:
                    raise ValueError('Unity companion RGB hash mismatch')
                rgb_prediction = self.models.analyse('rgb', rgb_raw)
                rgb_prediction['captureSource'] = 'thermal_capture'
                latest = self.thermal.snapshot()['pipes'].get(pipe, {})
                if latest.get('stage') != 'Complete' or latest.get('requestId') != request:
                    continue
                self.publish(pipe, 'rgb', request, rgb_raw, rgb_prediction)
                if not result['quality']['canInfer']:
                    with self.lock:
                        self.pipes.get(pipe, {}).pop('thermal', None)
                    self.seen.add(key)
                    continue
                raw = (root/'temperature.npy').read_bytes()
                if hashlib.sha256(raw).hexdigest() != result['temperatureSha256']:
                    raise ValueError('Unity temperature hash mismatch')
                geometry_raw = (root/'geometry.bin').read_bytes()
                if hashlib.sha256(geometry_raw).hexdigest() != result['geometrySha256']:
                    raise ValueError('Unity geometry hash mismatch')
                geometry = np.frombuffer(geometry_raw, dtype='<f4').reshape(256, 320, 3)
                current = np.load(io.BytesIO(raw), allow_pickle=False)
                # Normal reference is a declared simulator assumption, never an expected label/mask.
                out = io.BytesIO()
                pv_mode = getattr(self.models, 'thermal_input_mode', 'baseline') == 'pv_yolo'
                if pv_mode:
                    np.savez_compressed(out, current_c=current, roi_valid=geometry[:,:,2].astype(bool))
                else:
                    reference, _ = synthesize(geometry, 'normal', pipe)
                    np.savez_compressed(out, current_c=current[::2, ::2], expected_c=reference[::2, ::2],
                        roi_valid=geometry[::2, ::2, 2].astype(bool))
                prediction = self.models.analyse('thermal', out.getvalue())
                latest = self.thermal.snapshot()['pipes'].get(pipe, {})
                if latest.get('stage') != 'Complete' or latest.get('requestId') != request:
                    continue
                if pv_mode:
                    image = base64.b64decode(prediction['src'].split(',',1)[1], validate=True)
                    if hashlib.sha256(image).hexdigest() != prediction['inputSha256']:
                        raise ValueError('PV model input image hash mismatch')
                    (root/'model-input.png').write_bytes(image)
                    prediction['inputUrl'] = f'/api/thermal/file/{request}/model-input.png'
                    prediction['src'] = prediction['inputUrl']
                else:
                    prediction['quality_status'] += ' · 합성 정상 기준 사용 · 새 도메인 성능 미검증'
                self.publish(pipe, 'thermal', request, raw, prediction)
                self.seen.add(key)
            except Exception as error:  # noqa: BLE001 - isolate model failures and keep the local service available.
                self.errors['thermal'] = type(error).__name__
        with self.lock:
            self.connected['rgb'] = self.connected['rgb'] or any(
                p.get('rgb', {}).get('captureSource') == 'thermal_capture' for p in self.pipes.values())
        if len(self.seen) > 4096:
            self.seen = set(list(self.seen)[-2048:])

    def step_live_thermal(self):
        if getattr(self.models,'thermal_input_mode','baseline') != 'pv_yolo':
            return
        try:
            state=json.loads(self.fetch('/api/thermal-stream/state'))
            frame=state.get('frame')
            if not state.get('connected') or not frame or not frame.get('canInfer'):
                with self.lock:self.live_thermal=None
                return
            key=(frame['sessionId'],frame['frameId'])
            if key==self.stream_key:return
            raw=self.fetch(frame['inputUrl'])
            if hashlib.sha256(raw).hexdigest()!=frame['inputNpzSha256']:
                raise ValueError('Live thermal observation hash mismatch')
            started=time.perf_counter()
            prediction=self.models.analyse('thermal',raw)
            elapsed=round((time.perf_counter()-started)*1000,2)
            if prediction.get('inputSha256') != frame['imageSha256']:
                raise ValueError('Live thermal model pixels differ from the displayed frame')
            latest=json.loads(self.fetch('/api/thermal-stream/state'))
            if not latest.get('connected') or latest.get('frame',{}).get('sessionId') != frame['sessionId']:
                with self.lock:self.live_thermal=None
                return
            prediction.pop('src',None)
            indices_raw=self.fetch(f"/api/thermal-stream/frame/{frame['frameId']}/indices.bin")
            if hashlib.sha256(indices_raw).hexdigest()!=frame['indicesSha256']:
                raise ValueError('Live thermal pipe membership hash mismatch')
            indices=np.frombuffer(indices_raw,dtype='<u2').reshape(frame['height'],frame['width'])
            for region in prediction['regions']:
                x1,y1,x2,y2=region['bbox'];x,y=int((x1+x2)/2),int((y1+y2)/2)
                member=int(indices[y,x]) if 0<=x<frame['width'] and 0<=y<frame['height'] else 0
                region['pipeId']=frame['pipeIds'][member-1] if member else None
            prediction.update(requestId=frame['frameId'],sourceFrameId=frame['sourceFrameId'],
                sessionId=frame['sessionId'],source='unity_auto_model',analysedAt=time.time(),
                inferenceMs=elapsed,sha256=frame['imageSha256'],
                visiblePipeIds=[p['pipeId'] for p in frame['visiblePipes'] if p['canInfer']])
            prediction['quality_status'] += ' · Unity 이동 관측 · 합성 매질 온도'
            with self.lock:self.live_thermal=prediction;self.stream_key=key
            self.errors.pop('thermal_stream',None)
        except Exception as error:  # noqa: BLE001 - isolate model failures and keep the local service available.
            with self.lock:self.live_thermal=None
            if not isinstance(error,urllib.error.HTTPError) or error.code!=404:
                self.errors['thermal_stream']=type(error).__name__

    def snapshot(self, compact=False):
        with self.lock:
            pipes = {pipe: {kind: {k:v for k,v in evidence.items() if not compact or k != 'src'}
                           for kind,evidence in sensors.items()} for pipe,sensors in self.pipes.items()}
            return json.loads(json.dumps({'pipes': pipes, 'connected': self.connected, 'errors': self.errors,
                                             'liveRGB': self.live_rgb, 'liveThermal': self.live_thermal, 'liveStatus': self.live_status}))

    def run(self):
        while True:
            try:
                self.step()
            except Exception as error:  # noqa: BLE001 - isolate model failures and keep the local service available.
                self.errors['worker'] = type(error).__name__
            threading.Event().wait(.1 if self.live_thermal is not None else 1)
