"""Bounded live thermal observations from first-hit Unity pipe surfaces.

Only observed temperatures, visibility and sensor validity reach the detector.
Scenario names, expected labels and comparison truth are not accepted.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
import re
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

from maek.heat import surface_temp_c
from maek.thermal_display import render_thermal_display
from maek.thermal_pv_dashboard import render_temperature

ROOT = Path(__file__).resolve().parents[1]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encode_png(rgb):
    out = io.BytesIO()
    Image.fromarray(rgb).save(out, format='PNG')
    return out.getvalue()


class ThermalStream:
    def __init__(self, source, clock=time.time):
        self.source, self.clock = source, clock
        self.settings = json.loads((ROOT/'config/thermal_stream.json').read_text(encoding='utf-8'))
        definitions = json.loads((ROOT/'config/thermal_pipe_profiles.json').read_text(encoding='utf-8'))
        self.profiles = {}
        for pipe, p in definitions.items():
            self.profiles[pipe] = {'pipeId': pipe, 'service': p['service'], 'fluidC': p['fluidC'],
                'surfaceC': float(surface_temp_c(p['fluidC'], self.settings['ambientC'], p['odMm'], 0., .04, 10.)),
                'basis': p['surfaceBasis']}
        self.profile_hash = sha(json.dumps({'settings': self.settings, 'profiles': self.profiles}, sort_keys=True).encode())
        self.lock = threading.RLock()
        self.frames = OrderedDict()
        self.session, self.sequence, self.current = None, -1, None
        self.accepted = 0
        self.seen_pipes, self.seen_services = set(), set()
        self.seen_unprofiled=set()
        self.sessions=OrderedDict()

    def profile_snapshot(self):
        return copy.deepcopy({'schemaVersion': 1, 'profileSha256': self.profile_hash,
            'width': self.settings['width'], 'height': self.settings['height'], 'fps': self.settings['fps'],
            'ambientC': self.settings['ambientC'], 'minimumPipePixels': self.settings['minimumPipePixels'],
            'readout': self.settings['readout'],
            'profiles': list(self.profiles.values()), 'synthetic': True, 'workPermissionStatus': 'not_assessed'})

    def capture(self, payload):
        fields = {'schemaVersion','frameId','sourceFrameId','sessionId','sequence','capturedAt',
            'width','height','position','rotation','fieldOfView','aspect','rgbSha256',
            'temperatureBase64','temperatureSha256','validBase64','validSha256',
            'indicesBase64','indicesSha256','pipeIds','unprofiledPipeIds','profileSha256','synthetic','workPermissionStatus'}
        if set(payload) != fields:
            raise ValueError('Unsupported thermal frame fields; scenario truth is forbidden')
        p = payload
        if p['schemaVersion'] != 1 or p['synthetic'] is not True or p['workPermissionStatus'] != 'not_assessed':
            raise ValueError('Invalid thermal observation domain')
        if (not isinstance(p['frameId'],str) or not isinstance(p['sessionId'],str) or
                not re.fullmatch('[a-f0-9]{32}', p['frameId']) or not re.fullmatch('[A-Za-z0-9_-]{1,80}', p['sessionId'])):
            raise ValueError('Invalid thermal frame identity')
        if (type(p['sequence']) is not int or p['sequence'] < 0 or
                p['sourceFrameId'] != f"{p['sessionId']}-preview-{p['sequence']}"):
            raise ValueError('Frame/sequence mismatch')
        when = datetime.fromisoformat(p['capturedAt'])
        if when.tzinfo is None or p['profileSha256'] != self.profile_hash:
            raise ValueError('Missing timestamp or changed profile assumptions')
        w, h = self.settings['width'], self.settings['height']
        if (p['width'],p['height']) != (w,h) or not math.isfinite(p['aspect']) or abs(p['aspect']-w/h) > .001:
            raise ValueError('Invalid thermal camera dimensions')
        if not 20 <= p['fieldOfView'] <= 90:
            raise ValueError('Invalid field of view')
        for key, names in [('position',('x','y','z')), ('rotation',('x','y','z','w'))]:
            if set(p[key]) != set(names) or not all(type(p[key][n]) in (int,float) and math.isfinite(p[key][n]) for n in names):
                raise ValueError('Invalid thermal pose')
        if abs(sum(v*v for v in p['rotation'].values())-1) > .01:
            raise ValueError('Invalid camera rotation')
        ids = p['pipeIds']
        if (not isinstance(ids,list) or any(not isinstance(i,str) for i in ids) or
                len(ids) > len(self.profiles) or len(ids) != len(set(ids)) or any(i not in self.profiles for i in ids)):
            raise ValueError('Unknown or duplicated thermal pipe')
        missing=p['unprofiledPipeIds']
        if (not isinstance(missing,list) or len(missing)>512 or any(not isinstance(i,str) or not re.fullmatch('[A-Za-z0-9_.-]{1,100}',i) or i in self.profiles for i in missing) or len(set(missing))!=len(missing)):
            raise ValueError('Invalid unprofiled surface identities')
        raw = {}
        for name, count in [('temperature',w*h*4),('valid',w*h),('indices',w*h*2)]:
            raw[name] = base64.b64decode(p[name+'Base64'], validate=True)
            if len(raw[name]) != count or sha(raw[name]) != p[name+'Sha256']:
                raise ValueError('Thermal array hash/size mismatch')
        temperature = np.frombuffer(raw['temperature'],dtype='<f4').reshape(h,w)
        valid = np.frombuffer(raw['valid'],dtype='u1').reshape(h,w)
        indices = np.frombuffer(raw['indices'],dtype='<u2').reshape(h,w)
        if (not np.isfinite(temperature).all() or np.max(np.abs(temperature)) > 2000 or
                not np.isin(valid,[0,1]).all() or indices.max() > len(ids) or np.any((valid>0)&(indices==0))):
            raise ValueError('Invalid thermal samples or first-hit membership')
        camera = self.source.camera_snapshot()
        if not camera['connected'] or camera.get('cameraAvailable') is False or camera['sessionId'] != p['sessionId']:
            raise ValueError('Thermal source session is not live')
        rgb = self.source.frame(p['sourceFrameId'])
        if sha(rgb) != p['rgbSha256']:
            raise ValueError('Thermal frame is not bound to the original RGB')
        files = dict(**{'model-input.png':encode_png(render_temperature(temperature)), 'rgb.png':rgb})
        display,display_meta=render_thermal_display(temperature,valid,indices,rgb)
        files['display.png']=encode_png(display)
        files.update({'values.bin':raw['temperature'],'valid.bin':raw['valid'],'indices.bin':raw['indices']})
        out = io.BytesIO(); np.save(out,temperature,allow_pickle=False); files['temperature.npy']=out.getvalue()
        roi = valid.astype(bool).copy()
        visible = []
        for i, pipe in enumerate(ids,1):
            mask = indices==i; count=int(mask.sum()); usable=int((mask&roi).sum())
            if count == 0: continue
            if usable < self.settings['minimumPipePixels']: roi[mask]=False
            values=temperature[mask]
            visible.append({'pipeId': pipe, 'service': self.profiles[pipe]['service'],'pixels': count,
                'validPixels': usable, 'canInfer': usable>=self.settings['minimumPipePixels'],
                'minC': float(values.min()), 'maxC': float(values.max()), 'meanC': float(values.mean())})
        out = io.BytesIO(); np.savez_compressed(out,current_c=temperature,roi_valid=roi);files['input.npz']=out.getvalue()
        prefix=f"/api/thermal-stream/frame/{p['frameId']}/"
        meta = {'schemaVersion': 1,'frameId': p['frameId'],'sourceFrameId': p['sourceFrameId'],
            'sessionId': p['sessionId'],'sequence': p['sequence'],'capturedAt': p['capturedAt'],
            'width': w,'height': h,'position': dict(p['position']),'rotation': dict(p['rotation']),
            'imageUrl': prefix+'model-input.png','inputUrl': prefix+'input.npz',
            'displayUrl': prefix+'display.png','displaySha256': sha(files['display.png']),'display': display_meta,
            'imageSha256': sha(files['model-input.png']),'temperatureSha256': sha(files['temperature.npy']),
            'inputNpzSha256': sha(files['input.npz']),
            'valuesSha256': p['temperatureSha256'],'rgbSha256': p['rgbSha256'],'profileSha256': self.profile_hash,
            'validSha256': p['validSha256'],'indicesSha256': p['indicesSha256'],'pipeIds': ids,
            'visiblePipes': visible,'unprofiledPipeIds': list(missing),'canInfer': bool(roi.any()),'synthetic': True,'workPermissionStatus': 'not_assessed'}
        with self.lock:
            current_camera = self.source.camera_snapshot()
            if not current_camera['connected'] or current_camera['sessionId'] != p['sessionId']:
                raise ValueError('Thermal source changed during processing')
            if self.session == p['sessionId'] and p['sequence'] <= self.sequence:
                raise ValueError('Out-of-order thermal frame')
            if self.session != p['sessionId']:
                self.frames.clear();self.seen_pipes.clear();self.seen_services.clear();self.seen_unprofiled.clear()
            self.session,self.sequence=p['sessionId'],p['sequence']
            self.accepted += 1;self.current=dict(meta,receivedAt=self.clock())
            self.frames[p['frameId']]=(meta,files)
            while len(self.frames)>self.settings['historyFrames']:self.frames.popitem(last=False)
            self.seen_pipes.update(v['pipeId'] for v in visible)
            self.seen_services.update(v['service'] for v in visible)
            self.seen_unprofiled.update(missing)
            session=self.sessions.setdefault(self.session,{'frames': 0,'pipes': set(),'services': set(),'unprofiled': set()})
            session['frames']+=1;session['pipes'].update(v['pipeId'] for v in visible);session['services'].update(v['service'] for v in visible)
            session['unprofiled'].update(missing)
            self.sessions.move_to_end(self.session)
            while len(self.sessions)>self.settings['historySessions']:self.sessions.popitem(last=False)
        return {'status': 'accepted','frameId': p['frameId'],'sourceFrameId': p['sourceFrameId'],'rgbSha256': p['rgbSha256']}

    def snapshot(self,diagnostics=True):
        camera=self.source.camera_snapshot()
        with self.lock:
            age=None if self.current is None else max(0,self.clock()-self.current['receivedAt'])
            connected=bool(camera['connected'] and camera.get('cameraAvailable') is not False and ('preview' not in camera or camera['preview'] is not None) and camera['sessionId']==self.session and age is not None and age<=self.settings['staleSeconds'])
            result={'schemaVersion': 1,'connected': connected,'ageSeconds': age,
                'frame': copy.deepcopy(self.current) if connected else None,
                'acceptedFrames': self.accepted,
                'cataloguePipes': len(self.profiles),'catalogueServices': len({p['service'] for p in self.profiles.values()})}
            if diagnostics:
                result.update(seenPipes=sorted(self.seen_pipes),seenServices=sorted(self.seen_services),
                    unprofiledPipes=sorted(self.seen_unprofiled),
                    sessionStats=[{'sessionId': key,'frames': value['frames'],'seenPipes': sorted(value['pipes']),'seenServices': sorted(value['services']),'unprofiledPipes': sorted(value['unprofiled'])} for key,value in self.sessions.items()])
            return result

    def file(self, frame_id, name):
        with self.lock:
            meta,files=self.frames[frame_id]
            return json.dumps(meta,ensure_ascii=False).encode() if name=='metadata.json' else files[name]
