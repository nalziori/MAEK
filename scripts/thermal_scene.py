"""Scene-registered synthetic thermal observation, separate from ground-truth evaluation."""
import base64, hashlib, io, json, math, re, sys, threading
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from maek import params,thermal,thermal_render
from maek.camera.composite2d import label_components

ASSET='THERMAL-DEMO-01'
CFG=params.load_config()
W,H=320,256

def sha(data):return hashlib.sha256(data).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def timestamp(s):
    t=datetime.fromisoformat(s.replace('Z','+00:00'))
    if t.tzinfo is None:raise ValueError('timezone required')
    return t.timestamp()
def identity(r):
    if r.get('assetId')!=ASSET:raise ValueError('unsupported asset domain')
    for k in ('sessionId','runId','requestId'):
        if not isinstance(r.get(k),str) or not re.fullmatch('[a-f0-9]{32}',r[k]):raise ValueError('invalid identity')
    timestamp(r['startedAt'])
    if type(r.get('sequence')) is not int or not 0<=r['sequence']<1_000_000:raise ValueError('invalid sequence')

def validate_capture(r):
    fields={'requestId','sessionId','runId','assetId','startedAt','capturedAt','sequence','condition','width','height','geometryBase64','geometrySha256','rgbBase64','rgbSha256','position','rotation','fieldOfView'}
    if set(r)!=fields:raise ValueError('unsupported capture fields; truth labels forbidden')
    identity(r);timestamp(r['capturedAt'])
    if r['condition'] not in ('normal','wet','reflective') or (r['width'],r['height'])!=(W,H):raise ValueError('unsupported capture')
    for key,fields_ in [('position',('x','y','z')),('rotation',('x','y','z','w'))]:
        if set(r[key])!=set(fields_) or not all(type(r[key][k]) in (float,int) and math.isfinite(r[key][k]) for k in fields_):raise ValueError('invalid pose')
    if not 20<=r['fieldOfView']<=90 or abs(sum(v*v for v in r['rotation'].values())-1)>.01:raise ValueError('invalid camera')
    binary=base64.b64decode(r['geometryBase64'],validate=True);rgb=base64.b64decode(r['rgbBase64'],validate=True)
    if len(binary)!=W*H*12 or len(rgb)>2_000_000 or sha(binary)!=r['geometrySha256'] or sha(rgb)!=r['rgbSha256']:raise ValueError('capture hash/size mismatch')
    with Image.open(io.BytesIO(rgb)) as image:
        if image.size!=(W,H) or image.format!='PNG':raise ValueError('invalid RGB evidence')
        image.verify()
    g=np.frombuffer(binary,dtype='<f4').reshape(H,W,3).copy()
    if not np.isfinite(g).all() or not np.isin(g[:,:,2],[0,1]).all():raise ValueError('invalid geometry')
    roi=g[:,:,2].astype(bool)
    if roi.sum()<500 or np.max(np.abs(g[:,:,0][roi]))>1.01 or np.max(np.abs(g[:,:,1][roi]))>1.01:raise ValueError('insufficient visible surface')
    return g,rgb

def synthesize(g,condition):
    """Generator reads scenario assumptions; the detector below does not receive them."""
    roi=g[:,:,2].astype(bool);axis=np.linspace(-1,1,512)
    seg=dict(temp_c=180.,od_mm=114.3,insulation_mm=50.,insulated=True)
    moisture=np.zeros_like(axis) if condition=='normal' else .8*np.exp(-.5*(axis/.15)**2)
    surface=np.array([thermal.jacket_temp_c(CFG,seg,1.,float(m),False,15.) for m in moisture])
    true_temp=np.interp(g[:,:,0],axis,surface)
    eps=.12 if condition=='reflective' else .85
    reflected=thermal.reflected_temp_c(15.,-25. if condition=='reflective' else -3.,g[:,:,1])
    apparent=thermal.apparent_temp_c(true_temp,eps,reflected,.85,15.)
    rng=np.random.default_rng(2401)
    t=np.where(roi,apparent,15.)+rng.normal(0,.05,(H,W))
    quality=dict(canInfer=eps>=.2,code='low_emissivity_assumed' if eps<.2 else 'usable',emissivity=eps,
        message='저방사율·반사 조건 가정: 판독 보류' if eps<.2 else '모의 촬영 품질 조건 통과')
    return t.astype(np.float32),quality

def analyse_temperature(t,roi,quality):
    """Observation-only interface: no case name, defect kind or expected mask."""
    if t.shape!=(H,W) or roi.shape!=t.shape or not np.isfinite(t).all() or roi.sum()<500:raise ValueError('invalid observation')
    values=t[roi];reference=float(np.percentile(values,20));findings=[]
    if quality['canInfer']:
        predicted=thermal_render.detect_ir(CFG,t,roi)
        labels,count=label_components((predicted>0)&roi)
        for k in range(1,count+1):
            yy,xx=np.nonzero(labels==k)
            if len(xx)<12:continue
            findings.append(dict(kind='surface_temperature_anomaly',bbox=[int(xx.min()),int(yy.min()),int(xx.max()+1),int(yy.max()+1)],pixelCount=len(xx)))
    return dict(status='indeterminate' if not quality['canInfer'] else 'anomaly_observed' if findings else 'no_anomaly_observed',
        minC=float(values.min()),maxC=float(values.max()),meanC=float(values.mean()),referenceC=reference,
        deltaC=float(values.max()-reference),roiPixels=int(roi.sum()),findings=findings)

def palette(t):
    # Fixed, documented 10..100 C display range; never used as detector input.
    stops=np.array([[16,20,61],[38,55,142],[21,154,168],[233,196,61],[249,88,34],[255,244,223]],float)
    f=np.clip((t-10)/90,0,1)*5;i=np.minimum(f.astype(int),4);a=(f-i)[...,None]
    return ((1-a)*stops[i]+a*stops[i+1]).astype(np.uint8)

class ThermalStore:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.lock=threading.RLock();self.current={}
        try:self.current=json.loads((self.root/'current.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
    def save(self):
        temp=self.root/'current.tmp';temp.write_text(json.dumps(self.current,ensure_ascii=False,allow_nan=False),encoding='utf-8');temp.replace(self.root/'current.json')
    def event(self,e):
        identity(e)
        if e['stage'] not in ('Launching','Approaching','Settling','Analysing','Interrupted','Deferred'):raise ValueError('invalid stage')
        with self.lock:
            c=self.current
            if e['stage']=='Launching':
                if c and timestamp(e['startedAt'])<=timestamp(c['startedAt']):raise ValueError('old run')
            elif not c or any(c[k]!=e[k] for k in ('sessionId','runId','requestId','assetId')) or e['sequence']<=c['sequence']:raise ValueError('stale event')
            self.current={k:e[k] for k in ('sessionId','runId','requestId','assetId','startedAt','sequence','stage')}
            self.current.update(updatedAt=now(),result=None,source='unity_scene_thermal',producerLiveness='unknown');self.save()
        return dict(ok=True)
    def snapshot(self):
        with self.lock:return dict(schemaVersion=1,observation=json.loads(json.dumps(self.current)) if self.current else None)
    def active(self,r):
        c=self.current
        return bool(c) and all(c[k]==r[k] for k in ('sessionId','runId','requestId','assetId','sequence')) and c['stage']=='Analysing'
    def capture(self,r):
        with self.lock:
            if not self.active(r):raise ValueError('inactive capture')
        g,rgb=validate_capture(r);t,q=synthesize(g,r['condition']);a=analyse_temperature(t,g[:,:,2].astype(bool),q)
        folder=self.root/r['requestId']
        with self.lock:
            if not self.active(r):raise ValueError('cancelled capture')
            folder.mkdir(exist_ok=False)
            (folder/'rgb.png').write_bytes(rgb);np.save(folder/'temperature.npy',t)
            Image.fromarray(np.rint((t+50)*100).astype(np.uint16)).save(folder/'temperature16.png')
            Image.fromarray(palette(t)).save(folder/'thermal.png');Image.fromarray((g[:,:,2]*255).astype(np.uint8)).save(folder/'roi.png')
            (folder/'geometry.bin').write_bytes(base64.b64decode(r['geometryBase64']))
            metadata={k:v for k,v in r.items() if not k.endswith('Base64')};(folder/'capture.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
            prefix='/api/thermal/file/'+r['requestId']+'/'
            result={k:r[k] for k in ('requestId','sessionId','runId','assetId','capturedAt','rgbSha256','geometrySha256','width','height')}
            result.update(a,quality=q,synthetic=True,workPermissionStatus='not_assessed',temperatureUnit='apparent_surface_C',
                temperatureSha256=sha((folder/'temperature.npy').read_bytes()),thermalSha256=sha((folder/'thermal.png').read_bytes()),
                thermalUrl=prefix+'thermal.png',rgbUrl=prefix+'rgb.png',temperatureUrl=prefix+'temperature.npy',
                thermalPngBase64=base64.b64encode((folder/'thermal.png').read_bytes()).decode(),paletteMinC=10,paletteMaxC=100,
                scope='훈련용 보온배관 · 180C/50mm/방사율 등 가정 · 배경 15C · 현장 실측 아님',model='MAEK thermal.detect_ir / temperature-rule baseline')
            (folder/'response.json').write_text(json.dumps(result,ensure_ascii=False,allow_nan=False),encoding='utf-8')
            self.current.update(stage='Complete',result=result,updatedAt=now());self.save();return result
