"""Serial CPU instance inference with observable NMS cache-safety guards.

The temporary NMS instrumentation is process-global: do not run other Ultralytics
inference concurrently. No ground truth or pipe geometry enters this adapter.
"""
from __future__ import annotations

import inspect
import logging
import threading

import numpy as np

from maek.thermal_learned import NAMES, PREDICT, temperature_to_rgb

_INFERENCE_LOCK = threading.RLock()
_INTEROP_CONFIGURED = False


def _array(value):
    if hasattr(value, 'detach'):
        value = value.detach().cpu().numpy()
    return np.asarray(value)


class _TimeoutHandler(logging.Handler):
    def __init__(self):
        super().__init__()
        self.timed_out = False

    def emit(self, record):
        message = record.getMessage().lower()
        if 'nms' in message and 'time limit' in message:
            self.timed_out = True


class _NMSGuard:
    """Observe NMS before segmentation drops boxes with empty projected masks."""

    def __init__(self, module, logger):
        self.module = module
        self.logger = logger
        self.handler = _TimeoutHandler()
        self.calls = 0
        self.data = {}

    def __enter__(self):
        self.original = self.module.non_max_suppression
        self.signature = inspect.signature(self.original)
        self.module.non_max_suppression = self._call
        self.logger.addHandler(self.handler)
        return self

    def __exit__(self, *_):
        self.module.non_max_suppression = self.original
        self.logger.removeHandler(self.handler)

    def _call(self, *args, **kwargs):
        self.calls += 1
        bound = self.signature.bind(*args, **kwargs)
        bound.apply_defaults()
        options = bound.arguments
        prediction = options['prediction']
        if isinstance(prediction, (list, tuple)):
            prediction = prediction[0]
        shape = tuple(int(v) for v in prediction.shape)
        if options.get('end2end', False) or (shape and shape[-1] == 6):
            raise ValueError('Unsupported end2end NMS path')
        if len(shape) != 3 or shape[0] != 1:
            raise ValueError('Expected batch-one BCN raw prediction shape')
        if options.get('agnostic', False) or options.get('multi_label', False):
            raise ValueError('Expected class-aware, single-label NMS')
        if options.get('return_idxs', False):
            raise ValueError('Unsupported return_idxs NMS path')
        cap = int(options.get('max_nms', 30000))
        if shape[-1] > min(cap, 30000):
            raise ValueError('Raw anchor count may trigger max_nms truncation')
        if int(options.get('max_det', 300)) != 300:
            raise ValueError('Expected fixed max_det=300')
        if not np.isfinite(_array(prediction)).all():
            raise ValueError('Raw NMS predictions must be finite')
        outputs = self.original(*args, **kwargs)
        if not isinstance(outputs, (list, tuple)) or len(outputs) != 1:
            raise ValueError('Expected one NMS result')
        counts = [len(output) for output in outputs]
        if any(count >= 300 for count in counts):
            raise ValueError('NMS max_det saturation before mask filtering')
        if any(not np.isfinite(_array(output)).all() for output in outputs):
            raise ValueError('NMS outputs must be finite')
        self.data = {
            'raw_shape': list(shape), 'anchor_count': shape[-1],
            'pre_mask_counts': counts, 'max_det': 300, 'max_nms': cap,
            'class_aware': True, 'end2end': False,
        }
        return outputs

    def finish(self):
        if self.calls != 1:
            raise ValueError('Expected exactly one NMS instrumentation call')
        if self.handler.timed_out:
            raise ValueError('NMS timeout observed; cache is unsafe')
        return {**self.data, 'timeout': False, 'calls': self.calls}


def _instances(result, shape, conf, selected_classes):
    if tuple(result.orig_shape) != tuple(shape):
        raise ValueError('Prediction original shape changed')
    if result.boxes is None:
        raise ValueError('Prediction boxes are missing')
    boxes = _array(result.boxes.data)
    classes = _array(result.boxes.cls)
    scores = _array(result.boxes.conf)
    n = len(boxes)
    if boxes.shape != (n, 6) or classes.shape != (n,) or scores.shape != (n,):
        raise ValueError('Inconsistent box/class/score shape')
    if not all(np.isfinite(a).all() for a in (boxes, classes, scores)):
        raise ValueError('Box/class/score outputs must be finite')
    if not np.isin(classes, (0, 1, 2)).all():
        raise ValueError('Invalid predicted class')
    if np.any(scores <= conf) or np.any(scores > 1):
        raise ValueError('Prediction score violates strict confidence threshold')
    if selected_classes is not None and not np.isin(classes, selected_classes).all():
        raise ValueError('Prediction violates selected classes')
    if result.masks is None:
        if n:
            raise ValueError('Detection boxes without masks')
        masks = np.zeros((0, *shape), dtype=bool)
    else:
        masks = _array(result.masks.data)
        if masks.shape != (n, *shape):
            raise ValueError('Instance mask shape disagrees with boxes or original image')
        if not np.isfinite(masks).all():
            raise ValueError('Mask outputs must be finite')
        masks = masks > .5
        if n and not masks.reshape(n, -1).any(axis=1).all():
            raise ValueError('Unexpected empty projected mask survived filtering')
    return {'masks': masks.astype(bool, copy=True),
            'classes': classes.astype(np.int64, copy=True),
            'scores': scores.astype(np.float32, copy=True)}


class ThresholdPredictor:
    """Fixed-weight CPU FP32 predictor; infer returns unmerged instance masks."""

    def __init__(self, weights):
        import cv2
        import torch
        from ultralytics import YOLO
        from ultralytics.utils import LOGGER, nms

        global _INTEROP_CONFIGURED
        self._cv2, self._torch = cv2, torch
        self._nms, self._logger = nms, LOGGER
        cv2.setNumThreads(1)
        torch.set_num_threads(1)
        with _INFERENCE_LOCK:
            if not _INTEROP_CONFIGURED:
                if torch.get_num_interop_threads() != 1:
                    torch.set_num_interop_threads(1)
                _INTEROP_CONFIGURED = True
        self.yolo = YOLO(str(weights), task='segment')
        if self.yolo.names != NAMES:
            raise ValueError(f'Unexpected trained class names: {self.yolo.names}')
        self.yolo.model.to('cpu').float().eval()
        if getattr(self.yolo.model, 'end2end', False):
            raise ValueError('Unsupported end2end model')
        # Called after predictor setup and before processing the first image.
        self.yolo.add_callback('on_predict_start', lambda _: self._reset_threads())

    def _reset_threads(self):
        self._cv2.setNumThreads(1)
        self._torch.set_num_threads(1)

    def _check_runtime(self):
        # Predictor setup can reset intra-op threads; restore after each setup/call.
        self._reset_threads()
        if self._torch.get_num_interop_threads() != 1:
            raise ValueError('Expected one interop thread')
        active = self.yolo.predictor.model
        if getattr(active, 'fp16', False) or getattr(active, 'end2end', False):
            raise ValueError('Expected non-end2end FP32 backend')
        backend = getattr(active, 'backend', active)
        model = getattr(backend, 'model', None)
        if model is None:
            raise ValueError('Cannot inspect active predictor backend model')
        if any(p.dtype != self._torch.float32 or p.device.type != 'cpu'
               for p in model.parameters()):
            raise ValueError('Active predictor must use CPU FP32 weights')

    def infer(self, temperature, conf=.10, classes=None):
        if not np.isscalar(conf) or not np.isfinite(conf) or not 0 <= conf <= 1:
            raise ValueError('Confidence must be finite and in [0, 1]')
        if classes is not None:
            classes = list(classes)
            if not all(isinstance(c, (int, np.integer)) and c in NAMES for c in classes):
                raise ValueError('Selected classes must be integer IDs 0, 1, 2')
        rgb = temperature_to_rgb(temperature)
        shape = rgb.shape[:2]
        options = {**PREDICT, 'conf': float(conf), 'classes': classes,
                   'agnostic_nms': False, 'batch': 1}
        with _INFERENCE_LOCK:
            with _NMSGuard(self._nms, self._logger) as guard:
                results = self.yolo.predict(rgb, **options)
            guards = guard.finish()
            self._check_runtime()
            if len(results) != 1:
                raise ValueError('Expected exactly one prediction result')
            instances = _instances(results[0], shape, conf, classes)
            post_mask_count = len(instances['classes'])
            if post_mask_count > guards['pre_mask_counts'][0]:
                raise ValueError('Mask output count exceeds pre-mask NMS count')
            guards['post_mask_count'] = post_mask_count
            guards['empty_masks_removed'] = guards['pre_mask_counts'][0] - post_mask_count
            return {**instances, 'nms': guards}
