import logging
from types import SimpleNamespace

import numpy as np
import pytest

from maek.thermal_threshold_inference import ThresholdPredictor, _instances, _NMSGuard


def result(n=1, shape=(4, 5)):
    return SimpleNamespace(
        orig_shape=shape,
        boxes=SimpleNamespace(data=np.zeros((n, 6)), cls=np.zeros(n), conf=np.full(n, .5)),
        masks=SimpleNamespace(data=np.ones((n, *shape))),
    )


def nms_module(count=1, timeout=False):
    logger = logging.getLogger('threshold-test')

    def non_max_suppression(prediction, conf_thres=.1, iou_thres=.7, classes=None,
                            agnostic=False, multi_label=False, max_det=300,
                            nc=3, max_nms=30000, end2end=False, return_idxs=False):
        if timeout:
            logger.warning('NMS time limit 2.000s exceeded')
        return [np.zeros((count, 38))]
    return SimpleNamespace(non_max_suppression=non_max_suppression), logger


def test_guard_records_before_empty_mask_filter_and_restores():
    module, logger = nms_module(2)
    original = module.non_max_suppression
    with _NMSGuard(module, logger) as guard:
        module.non_max_suppression(np.zeros((1, 39, 2100)))
    assert module.non_max_suppression is original
    assert guard.finish()['pre_mask_counts'] == [2]
    assert guard.finish()['anchor_count'] == 2100


@pytest.mark.parametrize('count,anchors,timeout,kwargs,message', [
    (300, 2100, False, {}, 'max_det'),
    (1, 30001, False, {}, 'max_nms'),
    (1, 2100, True, {}, 'timeout'),
    (1, 2100, False, {'end2end': True}, 'end2end'),
    (1, 2100, False, {'agnostic': True}, 'class-aware'),
])
def test_guard_rejects_unsafe_outputs(count, anchors, timeout, kwargs, message):
    module, logger = nms_module(count, timeout)
    original = module.non_max_suppression
    with pytest.raises(ValueError, match=message):
        with _NMSGuard(module, logger) as guard:
            module.non_max_suppression(np.zeros((1, 39, anchors)), **kwargs)
        guard.finish()
    assert module.non_max_suppression is original


def test_guard_requires_instrumented_call():
    module, logger = nms_module()
    with _NMSGuard(module, logger) as guard:
        pass
    with pytest.raises(ValueError, match='one NMS'):
        guard.finish()


def test_instances_dtypes_and_empty():
    out = _instances(result(), (4, 5), .1, None)
    assert out['masks'].dtype == np.bool_
    assert out['classes'].dtype == np.int64
    assert out['scores'].dtype == np.float32
    empty = result(0)
    empty.masks = None
    assert _instances(empty, (4, 5), .1, None)['masks'].shape == (0, 4, 5)


@pytest.mark.parametrize('change,message', [
    (lambda r: setattr(r, 'orig_shape', (5, 4)), 'shape'),
    (lambda r: setattr(r, 'masks', None), 'without masks'),
    (lambda r: setattr(r.boxes, 'cls', np.array([.5])), 'class'),
    (lambda r: setattr(r.boxes, 'conf', np.array([np.nan])), 'finite'),
    (lambda r: setattr(r.boxes, 'conf', np.array([.1])), 'threshold'),
    (lambda r: setattr(r.masks, 'data', np.zeros((1, 4, 5))), 'empty'),
    (lambda r: setattr(r.masks, 'data', np.ones((2, 4, 5))), 'shape'),
    (lambda r: setattr(r.boxes, 'data', np.full((1, 6), np.inf)), 'finite'),
])
def test_instances_reject_invalid(change, message):
    sample = result()
    change(sample)
    with pytest.raises(ValueError, match=message):
        _instances(sample, (4, 5), .1, None)


def test_infer_resets_classes_and_has_no_geometry_input():
    predictor = ThresholdPredictor.__new__(ThresholdPredictor)
    predictor._nms, predictor._logger = nms_module()
    predictor._check_runtime = lambda: None
    calls = []

    def predict(image, **kwargs):
        calls.append(kwargs)
        predictor._nms.non_max_suppression(np.zeros((1, 39, 2100)))
        return [result()]
    predictor.yolo = SimpleNamespace(predict=predict)
    predictor.infer(np.zeros((4, 5)), classes=[0])
    predictor.infer(np.zeros((4, 5)), conf=.4)
    assert calls[0]['classes'] == [0]
    assert calls[1]['classes'] is None
    assert calls[1]['agnostic_nms'] is False
    assert calls[1]['conf'] == .4
