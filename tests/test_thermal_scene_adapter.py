import base64,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from thermal_scene import ThermalStore, analyse_temperature, synthesize, validate_capture

def request(case='wet',identity='1'*32):
    g=np.zeros((256,320,3),dtype='<f4'); yy,xx=np.mgrid[:256,:320]
    roi=(abs(yy-128)<22)&(xx>25)&(xx<295)
    g[:,:,0]=(xx-160)/135;g[:,:,1]=(128-yy)/22;g[:,:,2]=roi
    rgb=io.BytesIO();Image.new('RGB',(320,256),(90,90,90)).save(rgb,format='PNG')
    binary=g.tobytes();png=rgb.getvalue()
    return dict(requestId=identity,sessionId='2'*32,runId=identity,assetId='THERMAL-DEMO-01',
        startedAt='2026-11-09T12:00:00Z',capturedAt='2026-11-09T12:00:10Z',sequence=4,condition=case,
        width=320,height=256,geometryBase64=base64.b64encode(binary).decode(),geometrySha256=hashlib.sha256(binary).hexdigest(),
        rgbBase64=base64.b64encode(png).decode(),rgbSha256=hashlib.sha256(png).hexdigest(),
        position=dict(x=0,y=2,z=-5),rotation=dict(x=0,y=0,z=0,w=1),fieldOfView=45)

class ThermalContract(unittest.TestCase):
    def test_real_temperature_detector_and_quality_cases(self):
        results=[]
        for case in ['normal','wet','reflective']:
            r=request(case);g,_=validate_capture(r);t,quality=synthesize(g,case)
            results.append(analyse_temperature(t,g[:,:,2].astype(bool),quality))
        self.assertEqual(results[0]['status'],'no_anomaly_observed')
        self.assertEqual(results[1]['status'],'anomaly_observed')
        self.assertGreater(results[1]['deltaC'],results[0]['deltaC']+3)
        self.assertEqual(results[2]['status'],'indeterminate')

    def test_identity_hash_dimensions_and_no_defect_truth_input(self):
        for update in [dict(assetId='UNKNOWN-PIPE'),dict(geometrySha256='0'*64),dict(width=640),dict(rgbSha256='0'*64),dict(expectedMask=[1])]:
            r=request();r.update(update)
            with self.assertRaises(ValueError):validate_capture(r)

    def test_existing_pipe_profile_and_isolated_snapshot(self):
        from thermal_scene import PROFILES
        self.assertEqual(len(PROFILES),247)
        r=request();r['assetId']='BF1-Q005'
        g,_=validate_capture(r)
        t,q=synthesize(g,'normal',r['assetId'])
        self.assertLess(float(t[g[:,:,2]>0].max()),100)
        self.assertEqual(analyse_temperature(t,g[:,:,2]>0,q,'surface_delta')['status'],'no_anomaly_observed')
        hot,q=synthesize(g,'wet',r['assetId'])
        self.assertEqual(analyse_temperature(hot,g[:,:,2]>0,q,'surface_delta')['status'],'anomaly_observed')
        with tempfile.TemporaryDirectory() as d:
            store=ThermalStore(Path(d));e={k:r[k] for k in ['requestId','sessionId','runId','assetId','startedAt']}
            store.event(dict(e,sequence=0,stage='Launching'));store.event(dict(e,sequence=4,stage='Analysing'))
            store.capture(r)
            other=dict(e,assetId='BF1-G004',requestId='4'*32,runId='4'*32,startedAt='2026-11-09T13:00:00Z')
            store.event(dict(other,sequence=0,stage='Launching'))
            state=store.snapshot()['pipes']
            self.assertEqual(state['BF1-Q005']['result']['assetId'],'BF1-Q005')
            self.assertIsNone(state['BF1-G004']['result'])
            self.assertEqual(ThermalStore(Path(d)).snapshot()['pipes']['BF1-Q005']['stage'],'Complete')

    def test_hot_process_pipe_temperature_png_does_not_wrap(self):
        with tempfile.TemporaryDirectory() as d:
            store=ThermalStore(Path(d));r=request('normal');r['assetId']='BF1-H200'
            e={k:r[k] for k in ['requestId','sessionId','runId','assetId','startedAt']}
            store.event(dict(e,sequence=0,stage='Launching'));store.event(dict(e,sequence=4,stage='Analysing'));result=store.capture(r)
            t=np.load(Path(d)/r['requestId']/'temperature.npy')
            png=np.asarray(Image.open(Path(d)/r['requestId']/'temperature16.png')).astype(float)
            np.testing.assert_allclose(png/10-100,t,atol=.051)

    def test_stats_ignore_hot_background(self):
        r=request();g,_=validate_capture(r);t,q=synthesize(g,'normal');roi=g[:,:,2].astype(bool)
        t[~roi]=500
        a=analyse_temperature(t,roi,q)
        self.assertLess(a['maxC'],100)

    def test_detector_uses_fixed_observation_not_case_truth(self):
        r=request();g,_=validate_capture(r);t,q=synthesize(g,'wet');roi=g[:,:,2].astype(bool)
        a=analyse_temperature(t,roi,q);r['condition']='normal'
        self.assertEqual(a,analyse_temperature(t.copy(),roi.copy(),q.copy()))

    def test_cancel_and_late_response_do_not_publish(self):
        with tempfile.TemporaryDirectory() as d:
            store=ThermalStore(Path(d));r=request()
            e={k:r[k] for k in ['requestId','sessionId','runId','assetId','startedAt']}
            store.event(dict(e,sequence=0,stage='Launching'))
            store.event(dict(e,sequence=4,stage='Analysing'))
            store.event(dict(e,sequence=5,stage='Interrupted'))
            with self.assertRaises(ValueError):store.capture(r)
            self.assertIsNone(store.snapshot()['observation']['result'])

    def test_write_real_files_then_clear_for_new_run(self):
        with tempfile.TemporaryDirectory() as d:
            store=ThermalStore(Path(d));r=request();e={k:r[k] for k in ['requestId','sessionId','runId','assetId','startedAt']}
            store.event(dict(e,sequence=0,stage='Launching'));store.event(dict(e,sequence=4,stage='Analysing'))
            a=store.capture(r);self.assertEqual(a['requestId'],r['requestId']);self.assertTrue((Path(d)/r['requestId']/'temperature.npy').is_file())
            self.assertEqual(a['geometrySha256'],r['geometrySha256'])
            new=dict(e,requestId='3'*32,runId='3'*32,startedAt='2026-11-09T12:01:00Z',sequence=0,stage='Launching')
            store.event(new);self.assertIsNone(store.snapshot()['observation']['result'])

if __name__=='__main__':unittest.main()
