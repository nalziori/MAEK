import base64
import hashlib
import io
import json
from types import SimpleNamespace

import numpy as np
import pytest
from PIL import Image

from maek.thermal_pv_dashboard import ThermalPV

torch = pytest.importorskip('torch')
pytest.importorskip('ultralytics')


def bundle(tmp_path):
    (tmp_path/'weights.pt').write_bytes(b'fixture')
    (tmp_path/'deployment.json').write_text(json.dumps({'format': 'yolov8-pv','weights': 'weights.pt',
        'imgsz': 640,'confidence': .26,'normalization': 'percentile_1_99.5_inferno'}))
    return ThermalPV(tmp_path)


def sample(temperature, roi):
    output=io.BytesIO(); np.savez_compressed(output,current_c=temperature,roi_valid=roi)
    return output.getvalue()


def test_temperature_input_palette_roi_and_provenance(tmp_path):
    model=bundle(tmp_path); received={}
    def predict(image, **kwargs):
        received.update(image=image,kwargs=kwargs)
        boxes=[SimpleNamespace(xyxy=torch.tensor([[2.,2.,6.,6.]]),conf=torch.tensor([.8])),
               SimpleNamespace(xyxy=torch.tensor([[0.,0.,2.,2.]]),conf=torch.tensor([.9]))]
        return [SimpleNamespace(boxes=boxes)]
    model.model=SimpleNamespace(predict=predict)
    roi=np.zeros((8,10),dtype=bool);roi[2:6,2:8]=True
    result=model.analyse(sample(np.arange(80).reshape(8,10),roi))
    assert received['image'][0,0].tolist()==[3,0,0]
    assert received['image'][-1,-1].tolist()==[164,254,252]
    assert received['kwargs']['conf']==.26 and received['kwargs']['imgsz']==640
    assert len(result['regions'])==1 and '정상' in result['quality_status']
    image=base64.b64decode(result['src'].split(',')[1])
    assert hashlib.sha256(image).hexdigest()==result['inputSha256']
    assert Image.open(io.BytesIO(image)).size==(10,8)
    assert torch.get_num_threads()==1


def test_invalid_temperature_and_empty_roi_never_reach_model(tmp_path):
    model=bundle(tmp_path)
    for temperature,roi in [(np.full((3,4),np.nan),np.ones((3,4))),
                            (np.ones((3,4)),np.zeros((3,4)))]:
        with pytest.raises(ValueError): model.analyse(sample(temperature,roi))
