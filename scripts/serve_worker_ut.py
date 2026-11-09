"""Loopback-only demo adapter: frozen synthetic UT sample -> team pitting MLP.
No case labels/expected decisions are read by this service.
"""
import argparse
import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Engine:
    def __init__(self, root):
        self.root = Path(root).resolve()
        sys.path.insert(0, str(self.root))
        import numpy as np
        import predict_ascan as model
        from package_utils import verify_package
        verify_package()
        self.package_sha = hashlib.sha256((self.root/'manifest.json').read_bytes()).hexdigest()
        self.np, self.model = np, model
        self.cal = json.loads((self.root/'normal_ut_reviewed_v1/calibrated_config.json').read_text(encoding='utf-8'))
        self.frozen = json.loads((self.root/'normal_ut_repair_v2/frozen_decisions.json').read_text(encoding='utf-8'))
        self.source = self.root/'examples/ascan.npz'
        self.sha = hashlib.sha256(self.source.read_bytes()).hexdigest()
        self.rf, self.temp, self.wall, self.navg = model.load_input(self.source, self.cal, 16)
    def predict(self, sample, request_id, pipe_id):
        if type(sample) is not int or not 0 <= sample < len(self.rf):
            raise ValueError('sample out of range')
        if not isinstance(request_id,str) or not 1<=len(request_id)<=80 or not isinstance(pipe_id,str) or len(pipe_id)>80:
            raise ValueError('invalid request identity')
        j=slice(sample,sample+1)
        scores, _groups, thresholds, walls=self.model.predict(self.rf[j],self.temp[j],self.wall[j],self.navg,self.cal,self.frozen)
        valid=bool(self.np.isfinite(walls[0]))
        wave=self.rf[sample]
        return {'requestId': request_id,'pipeId': pipe_id,'sample': sample,'sourceSha256': self.sha,
                    'source': 'UT/examples/ascan.npz','synthetic': True,'model': 'frozen pitting MLP ensemble D',
                    'sampleId': f'bundled-pit-{sample}','pitScore': float(scores[0]),'threshold': float(thresholds[0]),
                    'pitAlarm': bool(scores[0]>thresholds[0]),'wallValid': valid,'mainWallMm': float(walls[0]) if valid else 0,
                    'nominalWallMm': float(self.wall[sample]),'observedTempC': float(self.temp[sample]),'nAvg': self.navg,
                    'wave': wave.astype(float).tolist(),'workPermissionStatus': 'not_assessed',
                    'interpretation': 'synthetic example replay at staged location; not a measurement of this Unity pipe'}

def serve(engine, port):
    class Handler(BaseHTTPRequestHandler):
        def reply(self,status,body):
            payload=json.dumps(body,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
        def do_GET(self):
            self.reply(200,{'status': 'ok','samples': len(engine.rf),'sourceSha256': engine.sha,'packageSha256': engine.package_sha}) if self.path=='/health' else self.reply(404,{'error': 'not found'})
        def do_POST(self):
            if self.path!='/ut':return self.reply(404,{'error': 'not found'})
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=2048:raise ValueError('request too large or empty')
                body=json.loads(self.rfile.read(length))
                result=engine.predict(body['sample'],body['requestId'],body['pipeId'])
                self.reply(200,result)
            except (ValueError,KeyError,TypeError) as exc:self.reply(400,{'error': str(exc)})
    HTTPServer(('127.0.0.1',port),Handler).serve_forever()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--ut-root',type=Path,default=Path(__file__).resolve().parents[1]/'UT');parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args();serve(Engine(args.ut_root),args.port)
