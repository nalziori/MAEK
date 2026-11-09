"""No ground-truth shortcuts, top-left pixel coordinates, and honest negatives."""
import base64
import hashlib
import io

import numpy as np
import pytest
from PIL import Image

from maek.inspection_bridge import analyse, regions


def payload(rgb):
    stream = io.BytesIO()
    Image.fromarray(rgb).save(stream, format="PNG")
    raw = stream.getvalue()
    return {"requestId": "capture-001", "imageBase64": base64.b64encode(raw).decode()}, raw


def test_actual_pixels_not_expected_label():
    rgb = np.full((96, 160, 3), 120, np.uint8)
    rgb[10:45, 95:140] = [130, 65, 25]
    request, raw = payload(rgb)
    request["expectedDefect"] = False
    result = analyse(request)
    assert result["requestId"] == "capture-001"
    assert result["imageSha256"] == hashlib.sha256(raw).hexdigest()
    assert result["components"]
    assert all(s["u"] > .5 and s["v"] < .5 for s in result["components"][0]["samples"])
    assert "crack_probability" not in result


def test_clean_pixels_not_promoted_by_label():
    request, _ = payload(np.full((80, 120, 3), 110, np.uint8))
    request["expectedDefect"] = True
    result = analyse(request)
    assert result["components"] == []
    assert "not proof" in result["negativeMeaning"]


def test_samples_inside_nonconvex_mask():
    mask = np.zeros((60, 90), bool)
    mask[10:50, 10:18] = True
    mask[42:50, 10:65] = True
    component = regions(mask)[0]
    for sample in component["samples"]:
        assert mask[int(sample["v"] * 60), int(sample["u"] * 90)]


def test_reject_bad_input_and_oversize():
    with pytest.raises(ValueError):
        analyse({"requestId": "x", "imageBase64": "!!!"})
    request, _ = payload(np.zeros((20, 1300, 3), np.uint8))
    with pytest.raises(ValueError, match="1280x720"):
        analyse(request)
