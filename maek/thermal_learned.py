"""Inference adapter matching the thermal Colab training input and semantic labels."""
from __future__ import annotations

import numpy as np

NAMES = {0: 'wet_insulation', 1: 'insulation_damage', 2: 'steam_leak'}
PREDICT = {'imgsz': 320, 'conf': 0.25, 'iou': 0.7, 'retina_masks': True,
           'device': 'cpu', 'verbose': False, 'save': False, 'max_det': 300}


def temperature_to_rgb(temperature):
    temperature = np.asarray(temperature, dtype=np.float32)
    if temperature.ndim != 2 or not np.isfinite(temperature).all():
        raise ValueError('Expected finite 2D temperatures in Celsius')
    gray = np.rint(np.clip((temperature + 40) / 240, 0, 1) * 255).astype(np.uint8)
    return np.repeat(gray[..., None], 3, axis=2)


def semantic_from_instances(masks, classes, scores, shape):
    """Highest box confidence owns overlaps; equal scores keep the earlier instance."""
    masks, classes, scores = map(np.asarray, (masks, classes, scores))
    if (masks.ndim != 3 or tuple(masks.shape[1:]) != tuple(shape)
            or classes.shape != (len(masks),) or scores.shape != (len(masks),)):
        raise ValueError('Instance masks must match the original image shape')
    if (not np.isfinite(masks).all() or not np.isfinite(scores).all()
            or not np.isin(classes, (0, 1, 2)).all()
            or np.any((scores < 0) | (scores > 1))):
        raise ValueError('Invalid instance values')
    result = np.zeros(shape, dtype=np.uint8)
    for i in np.argsort(-scores, kind='stable'):
        result[(masks[i] > 0.5) & (result == 0)] = int(classes[i]) + 1
    return result


class ThermalYOLO:
    def __init__(self, weights, first_temperature):
        import cv2
        import torch
        from ultralytics import YOLO

        cv2.setNumThreads(1)
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)
        self.yolo = YOLO(str(weights), task='segment')
        if self.yolo.names != NAMES:
            raise ValueError(f'Unexpected trained class names: {self.yolo.names}')
        self.predict(first_temperature)
        # Ultralytics initializes CPU thread settings on its first predict call.
        torch.set_num_threads(1)
        # Current AutoBackend can deepcopy/fuse the original model. Measure its actual model.
        self.model = self.yolo.predictor.model.backend.model
        if any(p.dtype != torch.float32 for p in self.model.parameters()):
            raise ValueError('The active predictor must use FP32 weights')
        self.model.eval()

    def predict(self, temperature):
        shape = temperature.shape
        result = self.yolo.predict(temperature_to_rgb(temperature), **PREDICT)[0]
        if tuple(result.orig_shape) != tuple(shape):
            raise ValueError('Prediction original shape changed')
        if result.masks is None:
            if len(result.boxes):
                raise ValueError('Detection boxes without segmentation masks')
            return np.zeros(shape, dtype=np.uint8)
        return semantic_from_instances(result.masks.data.cpu().numpy(),
                                       result.boxes.cls.cpu().numpy(),
                                       result.boxes.conf.cpu().numpy(), shape)

    def tensor(self, temperature):
        return self.yolo.predictor.preprocess([temperature_to_rgb(temperature)])


def paired_iou_change(before, after, seed=19, repeats=2000):
    """Bootstrap paired image TP/union counts, recomputing pooled IoU per draw."""
    before, after = np.asarray(before), np.asarray(after)
    if (before.shape != after.shape or before.ndim != 3 or before.shape[1:] != (3, 2)
            or len(before) == 0 or np.any(before < 0) or np.any(after < 0)
            or not np.isfinite(before).all() or not np.isfinite(after).all()):
        raise ValueError('Expected aligned N x 3 x (TP, union) counts')
    indices = np.random.default_rng(seed).integers(0, len(before), (repeats, len(before)))

    def ratio(counts):
        return np.divide(counts[..., 0], counts[..., 1],
                         out=np.full(counts.shape[:-1], np.nan), where=counts[..., 1] > 0)

    point = ratio(after.sum(axis=0)) - ratio(before.sum(axis=0))
    draws = ratio(after[indices].sum(axis=1)) - ratio(before[indices].sum(axis=1))
    results = {}
    for j, name in NAMES.items():
        finite = draws[:, j][np.isfinite(draws[:, j])]
        results[name] = {'change': float(point[j]) if np.isfinite(point[j]) else None,
                         'ci95': np.percentile(finite, [2.5, 97.5]).tolist()
                         if len(finite) else None, 'bootstrap_valid': len(finite)}
    return {'seed': seed, 'repeats': repeats, 'classes': results}
