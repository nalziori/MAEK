import base64
import hashlib
import io
import json
from datetime import UTC, datetime

import numpy as np
import pytest
from PIL import Image

from maek.thermal_stream import ThermalStream


class Source:
    def __init__(self):
        self.connected=True;self.session='S'
        image=io.BytesIO();Image.new('RGB',(640,360),'gray').save(image,format='PNG');self.raw=image.getvalue()
    def camera_snapshot(self):return {'connected': self.connected,'sessionId': self.session}
    def frame(self,identity):return self.raw


def packet(store, sequence=1, mode='normal'):
    profiles=list(store.profiles.values())
    first=profiles[0];second=next(p for p in profiles if p['service']!=first['service'])
    w,h=store.settings['width'],store.settings['height']
    indices=np.ones((h,w),dtype='<u2');indices[:,w//2:]=2
    temperature=np.where(indices==1,first['surfaceC'],second['surfaceC']).astype('<f4')
    valid=np.ones((h,w),dtype='u1')
    if mode=='hot':temperature[5:15,5:25]+=18
    if mode=='cold':temperature[5:15,5:25]-=18
    if mode=='reflective':valid[:]=0
    if mode=='occluded':indices[:]=0;valid[:]=0;temperature[:]=15
    data={'schemaVersion': 1,'frameId': f'{sequence:032x}','sourceFrameId': f'S-preview-{sequence}','sessionId': 'S','sequence': sequence,
        'capturedAt': datetime.now(UTC).isoformat(),'width': w,'height': h,'position': {'x': 0,'y': 0,'z': 0},
        'rotation': {'x': 0,'y': 0,'z': 0,'w': 1},'fieldOfView': 55,'aspect': w/h,
        'rgbSha256': hashlib.sha256(store.source.raw).hexdigest(),'pipeIds': [first['pipeId'],second['pipeId']],'unprofiledPipeIds': [],
        'profileSha256': store.profile_hash,'synthetic': True,'workPermissionStatus': 'not_assessed'}
    for name,array in [('temperature',temperature),('valid',valid),('indices',indices)]:
        raw=array.tobytes();data[name+'Base64']=base64.b64encode(raw).decode();data[name+'Sha256']=hashlib.sha256(raw).hexdigest()
    return data


def test_all_catalogue_media_profiles_are_finite_and_snapshot_is_independent():
    store=ThermalStream(Source());snapshot=store.profile_snapshot()
    assert len(snapshot['profiles'])==247
    assert len({p['service'] for p in snapshot['profiles']})==14
    assert all(np.isfinite(p['surfaceC']) and np.isfinite(p['fluidC']) for p in snapshot['profiles'])
    first=snapshot['profiles'][0];identity=first['pipeId'];first['surfaceC']=-999
    assert store.profiles[identity]['surfaceC']!=-999
    assert snapshot['readout']['enabled'] is True
    snapshot['readout']['transitSpeedScale']=0
    assert store.profile_snapshot()['readout']['transitSpeedScale']>0


def test_live_frame_pixels_membership_and_normal_hot_cold_changes():
    store=ThermalStream(Source());hashes=[];ranges=[]
    for sequence,mode in enumerate(['normal','hot','cold'],1):
        request=packet(store,sequence,mode);ack=store.capture(request);state=store.snapshot();frame=state['frame']
        assert ack['sourceFrameId']==request['sourceFrameId'] and state['connected'] and frame['canInfer']
        assert len(frame['visiblePipes'])==2
        image=store.file(frame['frameId'],'model-input.png')
        assert hashlib.sha256(image).hexdigest()==frame['imageSha256']
        assert Image.open(io.BytesIO(image)).size==(160,90)
        raw=store.file(frame['frameId'],'input.npz')
        assert hashlib.sha256(raw).hexdigest()==frame['inputNpzSha256']
        with np.load(io.BytesIO(raw),allow_pickle=False) as z:
            assert set(z.files)=={'current_c','roi_valid'} and z['roi_valid'].all()
        hashes.append(frame['imageSha256']);ranges.append(frame['visiblePipes'][0])
    assert len(set(hashes))==3
    assert ranges[1]['maxC']>ranges[0]['maxC']+17
    assert ranges[2]['minC']<ranges[0]['minC']-17


def test_display_is_hash_bound_and_does_not_replace_model_input_or_raw_temperatures():
    from maek.thermal_pv_dashboard import render_temperature
    store=ThermalStream(Source());request=packet(store);store.capture(request);frame=store.snapshot()['frame']
    display=store.file(frame['frameId'],'display.png')
    assert hashlib.sha256(display).hexdigest()==frame['displaySha256']
    assert Image.open(io.BytesIO(display)).size==(640,360)
    assert frame['displayUrl'].endswith('/display.png') and frame['imageUrl'].endswith('/model-input.png')
    raw=np.frombuffer(base64.b64decode(request['temperatureBase64']),dtype='<f4').reshape(90,160)
    expected=io.BytesIO();Image.fromarray(render_temperature(raw)).save(expected,format='PNG')
    assert store.file(frame['frameId'],'model-input.png')==expected.getvalue()
    with np.load(io.BytesIO(store.file(frame['frameId'],'input.npz'))) as data:
        np.testing.assert_array_equal(data['current_c'],raw)


@pytest.mark.parametrize('mode',['reflective','occluded'])
def test_unusable_or_occluded_frames_are_not_successful_negatives(mode):
    store=ThermalStream(Source());store.capture(packet(store,mode=mode));frame=store.snapshot()['frame']
    assert frame['canInfer'] is False
    with np.load(io.BytesIO(store.file(frame['frameId'],'input.npz'))) as z:assert not z['roi_valid'].any()


@pytest.mark.parametrize('changes',[
    {'expected_mask':'forbidden'}, {'condition':'hot'}, {'rgbSha256':'0'*64},
    {'temperatureSha256':'0'*64}, {'profileSha256':'0'*64}, {'pipeIds':['unknown']},
    {'pipeIds':[{}]}, {'synthetic':False}, {'workPermissionStatus':'approved'},
    {'width':320}, {'sourceFrameId':'another-frame'}, {'rotation':{'x': 0,'y': 0,'z': 0,'w': 0}},
])
def test_malformed_truth_or_wrong_source_is_rejected(changes):
    store=ThermalStream(Source());request=packet(store);request.update(changes)
    with pytest.raises((ValueError,TypeError)):store.capture(request)
    assert store.snapshot()['frame'] is None and store.accepted==0


def test_nonfinite_temperature_is_not_imputed():
    store=ThermalStream(Source());request=packet(store)
    raw=np.full((90,160),np.nan,dtype='<f4').tobytes()
    request['temperatureBase64']=base64.b64encode(raw).decode();request['temperatureSha256']=hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError):store.capture(request)


def test_late_source_expiry_and_bounded_history():
    now=[100.];source=Source();store=ThermalStream(source,clock=lambda:now[0]);store.settings['historyFrames']=2
    first=packet(store);store.capture(first)
    with pytest.raises(ValueError):store.capture(first)
    store.capture(packet(store,2));store.capture(packet(store,3))
    assert len(store.frames)==2
    assert 'sessionStats' not in store.snapshot(diagnostics=False)
    assert 'seenPipes' not in store.snapshot(diagnostics=False)
    with pytest.raises(KeyError):store.file(first['frameId'],'metadata.json')
    now[0]+=6
    assert store.snapshot()['frame'] is None and not store.snapshot()['connected']
    source.session='new'
    with pytest.raises(ValueError):store.capture(packet(store,4))


def test_thermal_stream_worker_latest_only_and_quality_hold():
    from maek.unity_model_feed import UnityModelFeed
    source=Source();store=ThermalStream(source);store.capture(packet(store))
    class Models:
        thermal_input_mode='pv_yolo';calls=0
        def analyse(self,kind,raw):
            self.calls+=1;frame=store.snapshot()['frame']
            return {'inputSha256': frame['imageSha256'],'regions': [{'bbox': [1,1,5,5],'confidence': .9}],
                'quality_status': 'fixture','analysis_summary': 'candidate','model': 'fixture'}
    class Legacy:
        def snapshot(self):return {'pipes':{}}
    def fetch(path):
        if path=='/api/thermal-stream/state':return json.dumps(store.snapshot()).encode()
        identity,name=path.removeprefix('/api/thermal-stream/frame/').split('/')
        return store.file(identity,name)
    models=Models();feed=UnityModelFeed(models,Legacy(),fetch)
    feed.step_live_thermal();feed.step_live_thermal()
    assert models.calls==1 and feed.snapshot()['liveThermal']['regions'][0]['pipeId'] in store.profiles
    store.capture(packet(store,2,'hot'));feed.step_live_thermal();assert models.calls==2
    store.capture(packet(store,3,'reflective'));feed.step_live_thermal()
    assert models.calls==2 and feed.snapshot()['liveThermal'] is None
