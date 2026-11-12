"""PV thermal detector adapter; temperature rendering follows the supplied bundle."""
import base64
import hashlib
import io
import json
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image


def render_temperature(temperature):
    from matplotlib import colormaps
    lo, hi = np.percentile(temperature, [1, 99.5])
    return (colormaps['inferno'](np.clip((temperature-lo)/max(hi-lo, 1e-3), 0, 1))[..., :3]*255).astype(np.uint8)


class ThermalPV:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config = json.loads((self.root/'deployment.json').read_text(encoding='utf-8'))
        self.weights = (self.root/self.config['weights']).resolve()
        if not self.weights.is_relative_to(self.root) or not self.weights.is_file():
            raise ValueError('Invalid PV model weights')
        if self.config['format'] != 'yolov8-pv' or self.config['normalization'] != 'percentile_1_99.5_inferno':
            raise ValueError('Unsupported thermal model format')
        self.model = None

    def analyse(self, raw):
        import torch
        from ultralytics import YOLO
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if len(archive.infolist()) > 12 or sum(i.file_size for i in archive.infolist()) > 8_000_000:
                raise ValueError('Thermal input too large')
        with np.load(io.BytesIO(raw), allow_pickle=False) as sample:
            temperature = sample['current_c']
            roi = sample['roi_valid']
        if (temperature.ndim != 2 or temperature.size > 4_000_000 or
                roi.shape != temperature.shape or not np.isfinite(temperature).all() or
                not np.isin(roi, [0, 1]).all() or not roi.any()):
            raise ValueError('Invalid temperature or pipe ROI')
        rgb = render_temperature(temperature)
        torch.set_num_threads(1)
        if self.model is None:
            self.model = YOLO(str(self.weights))
        result = self.model.predict(rgb[:, :, ::-1].copy(), imgsz=self.config['imgsz'],
            conf=self.config['confidence'], device=0 if torch.cuda.is_available() else 'cpu',
            iou=.7, max_det=300, verbose=False)[0]
        torch.set_num_threads(1)
        regions = []
        height, width = temperature.shape
        for box in result.boxes or []:
            bbox = box.xyxy[0].cpu().tolist()
            x, y = int((bbox[0]+bbox[2])/2), int((bbox[1]+bbox[3])/2)
            if not (0 <= x < width and 0 <= y < height and roi[y,x]):
                continue
            regions.append({'bbox': bbox, 'confidence': float(box.conf[0]), 'kind': 'hot_spot'})
        image = io.BytesIO(); Image.fromarray(rgb).save(image, format='PNG')
        image = image.getvalue()
        return {'src': 'data:image/png;base64,'+base64.b64encode(image).decode(),
            'width': width, 'height': height, 'regions': regions, 'model': self.weights.name,
            'inputSha256': hashlib.sha256(image).hexdigest(),
            'analysis_summary': f'열점 후보 {len(regions)}건' if regions else '열점 후보 미검출',
            'assessment_status': 'candidate' if regions else 'no_candidate',
            'quality_status': 'PV 열점 학습 모델 · 배관 성능 미검증 · 미검출은 정상 보장 아님 · 실제 배관 ROI 사용'}
