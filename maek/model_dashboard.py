"""Same-origin photo inference dashboard, portable between PC and Jetson."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import threading
import zipfile
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

from scripts.serve_ut_dashboard import Handler as SensorHandler


class PhotoModels:
    def __init__(self, corrosion, thermal):
        self.corrosion_path, self.thermal_dir = Path(corrosion), Path(thermal)
        self.rgb_model = self.thermal_model = None
        self.pv_model = None
        self.thermal_input_mode = 'pv_yolo' if (self.thermal_dir/'deployment.json').is_file() else 'baseline'
        self.lock = threading.Lock()

    def analyse(self, kind, raw):
        # CUDA models share one bounded inference queue on small Jetson devices.
        with self.lock:
            if kind == 'ndt':
                from maek.ndt_dashboard import analyse
                result, image = analyse(raw)
                return dict(result, src=png(image))
            return self._rgb(raw) if kind == 'rgb' else self._thermal(raw)

    def _rgb(self, raw):
        import torch
        from ultralytics import YOLO
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 4_000_000:
                raise ValueError('사진은 400만 픽셀 이하여야 합니다')
            rgb = np.array(image.convert('RGB'))
        if self.rgb_model is None:
            self.rgb_model = YOLO(str(self.corrosion_path))
        torch.set_num_threads(1)
        result = self.rgb_model.predict(rgb[:, :, ::-1].copy(), imgsz=640,
            device=0 if torch.cuda.is_available() else 'cpu', conf=.25,
            iou=.7, max_det=300, verbose=False)[0]
        # Ultralytics CPU initialization can override the process startup thread budget.
        torch.set_num_threads(1)
        regions = []
        if result.boxes is not None:
            for box in result.boxes:
                regions.append({'bbox': box.xyxy[0].cpu().tolist(),
                    'confidence': float(box.conf[0]),
                    'kind': str(result.names[int(box.cls[0])])})
        names = {'corrosion': '외부 부식', 'rust': '외부 부식',
                 'cui': 'CUI 외관 징후', 'cui_sign': 'CUI 외관 징후', 'leak_stain': '누설 흔적'}
        summary = 'RGB 의심 미검출'
        if regions:
            kinds = ' · '.join(dict.fromkeys(names.get(r['kind'].lower(), r['kind']) for r in regions))
            summary = f'{kinds} 후보 {len(regions)}건 · 신뢰도 {max(r["confidence"] for r in regions):.1%}'
        return {'src': png(rgb), 'width': rgb.shape[1], 'height': rgb.shape[0], 'regions': regions,
            'model': self.corrosion_path.name, 'assessment_status': 'candidate' if regions else 'no_candidate',
            'analysis_summary': summary,
            'quality_status': '모델 관측 · 확정 결함 판정 아님'}

    def _thermal(self, raw):
        if self.thermal_input_mode == 'pv_yolo':
            from maek.thermal_pv_dashboard import ThermalPV
            if self.pv_model is None:
                self.pv_model = ThermalPV(self.thermal_dir)
            return self.pv_model.analyse(raw)
        import cv2
        import torch

        from maek.thermal_observation_data import encode_pair
        from maek.thermal_observation_model import build_model
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist()) > 24 or sum(i.file_size for i in archive.infolist()) > 8_000_000:
                raise ValueError('열 데이터 압축 해제 크기 초과')
        with np.load(io.BytesIO(raw), allow_pickle=False) as sample:
            missing = {'expected_c', 'current_c', 'roi_valid'} - set(sample.files)
            if missing:
                raise ValueError('판독 보류: 정상 기준·현재 온도·배관 영역이 필요합니다: ' + ', '.join(sorted(missing)))
            ref, cur, roi = (sample[k] for k in ('expected_c', 'current_c', 'roi_valid'))
            if cur.shape != (128, 160) or roi.shape != cur.shape:
                raise ValueError('열화상 입력은 정합된 128×160 온도 지도와 ROI여야 합니다')
            if not np.isin(roi, [0, 1]).all() or not roi.any():
                raise ValueError('유효한 배관 관심영역이 필요합니다')
            roi = roi.astype(bool)
            x = encode_pair(ref, cur) * roi[None]
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        if self.thermal_model is None:
            self.thermal_model = build_model().eval().to(device)
            ck = torch.load(self.thermal_dir/'baseline_flip_19.pt', map_location='cpu', weights_only=True)
            self.thermal_model.load_state_dict(ck.get('state_dict', ck.get('model_state', ck)))
        threshold = json.loads((self.thermal_dir/'baseline_flip_19.json').read_text())['threshold']
        with torch.inference_mode():
            score = self.thermal_model(torch.from_numpy(x[None]).to(device)).softmax(1)[0, 1].cpu().numpy()
        if not np.isfinite(score).all():
            raise ValueError('모델 출력이 유한하지 않습니다')
        _, labels, stats, _ = cv2.connectedComponentsWithStats(((score > threshold) & roi).astype('uint8'), 8)
        keep = stats[:, cv2.CC_STAT_AREA] >= 9
        keep[0] = False
        mask = keep[labels]
        regions = [{'bbox': [int(x), int(y), int(x+w), int(y+h)], 'kind': 'thermal_anomaly'}
            for x, y, w, h, area in stats[1:] if area >= 9]
        lo, hi = float(cur.min()), float(cur.max())
        gray = np.clip((cur-lo)/max(hi-lo, .01)*255, 0, 255).astype('uint8')
        view = cv2.cvtColor(cv2.applyColorMap(gray, cv2.COLORMAP_INFERNO), cv2.COLOR_BGR2RGB)
        pixels = int(mask.sum())
        return {'src': png(view), 'width': 160, 'height': 128, 'regions': regions,
            'model': 'baseline_flip_19', 'assessment_status': 'anomaly_observed' if pixels else 'no_anomaly_observed',
            'analysis_summary': f'열 이상 {len(regions)}영역 · {pixels}픽셀' if pixels else '열 이상 미검출',
            'quality_status': '기준정보 제공 · 현장 성능 미검증', 'threshold': threshold,
            'anomaly_pixels': pixels, 'roi_pixels': int(roi.sum())}


def png(array):
    out = io.BytesIO()
    Image.fromarray(array).save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()


class Handler(SimpleHTTPRequestHandler):
    json_reply = SensorHandler.json_reply

    def do_GET(self):
        if self.path.startswith('/api/live-camera/'):
            from maek.live_camera import serve
            return serve(self)
        if self.path.split('?')[0] == '/api/model-results':
            return self.reply(200, self.server.model_feed.snapshot(compact=self.path.endswith('?summary=1')))
        if self.path.split('?')[0].startswith(('/api/ut', '/api/thermal')):
            return SensorHandler.do_GET(self)
        return super().do_GET()

    def __init__(self, *args, models, dashboard, **kwargs):
        self.models = models
        super().__init__(*args, directory=str(dashboard), **kwargs)

    def do_POST(self):
        if self.path in ('/api/thermal/event', '/api/thermal/capture'):
            return SensorHandler.do_POST(self)
        if self.path != '/api/photo-inference':
            self.send_error(404)
            return
        try:
            # Same-origin API: reject cross-site browser writes to this local device.
            origin = self.headers.get('Origin')
            if origin and origin not in ('http://' + self.headers.get('Host', ''), 'https://' + self.headers.get('Host', '')):
                raise ValueError('다른 출처의 요청은 허용하지 않습니다')
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 12_000_000:
                raise ValueError('파일은 8MB 이하로 선택하세요')
            payload = json.loads(self.rfile.read(size))
            kind, pipe, request = (payload[k] for k in ('kind', 'pipeId', 'requestId'))
            if kind not in ('rgb', 'thermal', 'ndt') or not all(isinstance(v, str) and 0 < len(v) <= 100 for v in (pipe, request)):
                raise ValueError('사진 종류·배관·요청 번호가 필요합니다')
            raw = base64.b64decode(payload['fileBase64'], validate=True)
            if not raw or len(raw) > 8_000_000:
                raise ValueError('파일 크기 오류')
            evidence = self.models.analyse(kind, raw)
            evidence.update(requestId=request, sampleId=payload.get('filename', request),
                sha256=hashlib.sha256(raw).hexdigest(), source='model_inference')
            self.reply(200, {'pipeId': pipe, 'requestId': request, 'kind': kind, 'evidence': evidence})
        except (ValueError, KeyError, TypeError, OSError) as error:
            self.reply(400, {'error': str(error)})
        except Exception:  # noqa: BLE001 - isolate model failures and keep the local service available.
            self.log_error('Model inference failed')
            self.reply(503, {'error': '모델 실행 실패: 서버 모델 경로·의존성을 확인하세요'})

    def reply(self, status, value):
        raw = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(raw)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--corrosion', required=True)
    p.add_argument('--thermal', required=True)
    p.add_argument('--dashboard', type=Path, default=Path(__file__).resolve().parents[1]/'dashboard')
    p.add_argument('--port', type=int, default=8878)
    p.add_argument('--unity-port', type=int, default=8894)
    args = p.parse_args()
    import torch
    torch.set_num_threads(1)
    models = PhotoModels(args.corrosion, args.thermal)
    handler = partial(Handler, models=models, dashboard=args.dashboard)
    print(f'Dashboard http://127.0.0.1:{args.port}', flush=True)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    import re

    from scripts.thermal_scene import ThermalStore
    root = Path(__file__).resolve().parents[1]
    catalogue = (args.dashboard/'operations-data.js').read_text(encoding='utf-8-sig')
    server.known_pipes = set(re.findall(r'"id"\s*:\s*"([A-Za-z0-9_.-]+)"', catalogue))
    local = Path.home()/'AppData/LocalLow/MAEK'
    server.ut_log_root = [local/'MAEK Worker UT V5/MAEK-worker-ut', local/'MAEK Thermal and UT V6/MAEK-worker-ut']
    server.thermal = ThermalStore(root/'data/unity_thermal')
    from maek.unity_model_feed import UnityModelFeed
    server.model_feed = UnityModelFeed(models, server.thermal)
    threading.Thread(target=server.model_feed.run, daemon=True).start()
    if args.unity_port != args.port:
        unity_server = ThreadingHTTPServer(('127.0.0.1', args.unity_port), handler)
        for field in ('thermal', 'model_feed', 'known_pipes', 'ut_log_root'):
            setattr(unity_server, field, getattr(server, field))
        threading.Thread(target=unity_server.serve_forever, daemon=True).start()
    server.serve_forever()


if __name__ == '__main__':
    main()
