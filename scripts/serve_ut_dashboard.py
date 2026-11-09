"""Read-only, loopback dashboard adapter for existing Unity V5 UT log files.

No detector inputs, Unity state or work permissions are modified. Old V5 events
lack request IDs; a result is accepted only when one same-pipe, hash-verified file
was written immediately after its RESULT event. Ambiguity remains unmeasured.
"""
import argparse
from datetime import datetime, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit

SOURCE_SHA = 'be4be1f82633378c803ff3112d43738ad89b928778c1ba69033c738a624d1e6d'
STAGES = {'Waiting','ReferenceCheck','Walking','SurfacePreparation','Couplant','Contact','Analysing','Complete','Deferred','Interrupted'}


def utc_seconds(value):
    stamp=datetime.fromisoformat(value.replace('Z','+00:00'))
    if stamp.tzinfo is None:raise ValueError('timezone required')
    return stamp.timestamp()


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def verified_result(path, pipe):
    try:
        if path.stat().st_size > 1_000_000:return None
        r=json.loads(path.read_text(encoding='utf-8-sig'))
        if not (r['pipeId']==pipe and r['requestId']==path.stem and
                re.fullmatch(r'[A-Za-z0-9_-]{1,80}',r['requestId']) and
                r['synthetic'] is True and r['workPermissionStatus']=='not_assessed' and
                r['sourceSha256']==SOURCE_SHA and type(r['sample']) is int and 0<=r['sample']<32 and
                len(r['wave'])==4096 and all(finite(v) for v in r['wave']) and
                finite(r['pitScore']) and 0<=r['pitScore']<=1 and
                finite(r['threshold']) and 0<=r['threshold']<=1 and
                type(r['pitAlarm']) is bool and r['pitAlarm']==(r['pitScore']>r['threshold']) and
                type(r['wallValid']) is bool and
                (not r['wallValid'] or finite(r['mainWallMm']) and r['mainWallMm']>0)):
            return None
        fields=('requestId','pipeId','sample','sourceSha256','synthetic','model','source','workPermissionStatus',
                'pitScore','threshold','pitAlarm','wallValid','mainWallMm','wave')
        return {k:r[k] for k in fields}
    except (OSError,ValueError,KeyError,TypeError):return None


def snapshot(log_root, known_pipes):
    if isinstance(log_root,(list,tuple)):
        return max((snapshot(p,known_pipes) for p in log_root),key=lambda r:r.get('sessionId') or '')
    response=dict(schemaVersion=1,source='unity_v5_log_follow',producerLiveness='unknown',
                  observedAt=datetime.now(timezone.utc).isoformat(),sessionId=None,pipes={})
    if not log_root.is_dir():return response
    # Timestamped V5 sessions, not editor/build directories or arbitrary files.
    sessions=sorted((p for p in log_root.iterdir() if p.is_dir() and not p.is_symlink()
                     and re.fullmatch(r'\d{8}-\d{6}-\d{3}',p.name)),reverse=True)
    for directory in sessions[:20]:
        events=[]
        try:
            file=directory/'events.jsonl'
            if file.stat().st_size>10_000_000:continue
            for line in file.read_text(encoding='utf-8-sig').splitlines():
                try:
                    e=json.loads(line)
                    if (e['pipeId'] in known_pipes and e['stage'] in STAGES and
                        e.get('workPermissionStatus')=='not_assessed' and isinstance(e['kind'],str)):
                        utc_seconds(e['utc']);events.append(e)
                except (ValueError,KeyError,TypeError):continue
        except OSError:continue
        if not events:continue
        response['sessionId']=directory.name
        for pipe in {e['pipeId'] for e in events}:
            rows=[e for e in events if e['pipeId']==pipe];last=rows[-1]
            start=max((i for i,e in enumerate(rows) if e['kind']=='REFERENCE_START'),default=0)
            row=dict(pipeId=pipe,pointId='UT-01 (시연 지점)',stage=last['stage'],
                     status=last.get('status',''),updatedAt=last['utc'],result=None,previous=None,
                     resultStatus='not_measured',steps=[e['kind'] for e in rows[start:]],
                     workPermissionStatus='not_assessed')
            results=[]
            for path in directory.glob('*.json'):
                if path.is_symlink():continue
                r=verified_result(path,pipe)
                if r:results.append((path.stat().st_mtime,r))
            def match(event):
                when=utc_seconds(event['utc'])
                candidates=[r for stamp,r in results if 0<=stamp-when<=2]
                if len(candidates)!=1:return None
                r=dict(candidates[0]);r['recordedAt']=event['utc'];return r
            if last['kind']=='RESULT' and last['stage']=='Complete':
                row['result']=match(last)
                row['resultStatus']='verified' if row['result'] else 'unverified_or_pending'
            for event in reversed(rows[:-1]):
                if event['kind']=='RESULT':
                    row['previous']=match(event)
                    if row['previous']:break
            response['pipes'][pipe]=row
        return response
    return response


class Handler(SimpleHTTPRequestHandler):
    def json_reply(self,code,body):
        data=json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(code);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Cache-Control','no-store')
        self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_POST(self):
        if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:return self.send_error(403)
        if self.path not in ('/api/thermal/event','/api/thermal/capture'):return self.send_error(404)
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<4_000_000:raise ValueError('invalid request size')
            body=json.loads(self.rfile.read(length))
            result=self.server.thermal.event(body) if self.path.endswith('/event') else self.server.thermal.capture(body)
            self.json_reply(200,result)
        except (ValueError,KeyError,TypeError,OSError) as error:
            self.json_reply(400,dict(error=type(error).__name__,message=str(error)[:200]))
    def do_GET(self):
        if self.headers.get('Host') not in {f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}:
            return self.send_error(403)
        path_=urlsplit(self.path).path
        if path_=='/api/thermal':return self.json_reply(200,self.server.thermal.snapshot())
        match=re.fullmatch(r'/api/thermal/file/([a-f0-9]{32})/(thermal\.png|rgb\.png|roi\.png|temperature16\.png|temperature\.npy|capture\.json|response\.json|geometry\.bin)',path_)
        if match:
            file=self.server.thermal.root/match[1]/match[2]
            if not file.is_file() or file.is_symlink():return self.send_error(404)
            data=file.read_bytes();self.send_response(200);self.send_header('Content-Type','image/png' if file.suffix=='.png' else 'application/json' if file.suffix=='.json' else 'application/octet-stream')
            self.send_header('Content-Length',str(len(data)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(data);return
        if urlsplit(self.path).path=='/api/ut':
            try:body=snapshot(self.server.ut_log_root,self.server.known_pipes)
            except OSError:body=dict(schemaVersion=1,error='log_read_failed',pipes={})
            data=json.dumps(body,ensure_ascii=False,allow_nan=False).encode('utf-8')
            self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data);return
        path=Path(self.translate_path(self.path)).resolve()
        if not path.is_relative_to(Path(self.directory).resolve()):return self.send_error(404)
        super().do_GET()


def main():
    root=Path(__file__).resolve().parents[1]
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=8894)
    parser.add_argument('--log-root',type=Path,default=Path.home()/'AppData/LocalLow/MAEK/MAEK Worker UT V5/MAEK-worker-ut')
    parser.add_argument('--thermal-dir',type=Path,default=root.parent/'MAEK_Thermal_V6/evidence')
    args=parser.parse_args()
    dashboard=root/'dashboard'
    data=(dashboard/'operations-data.js').read_text(encoding='utf-8-sig')
    known=set(re.findall(r'"id"\s*:\s*"([A-Za-z0-9_.-]+)"',data))
    if not known:raise RuntimeError('No catalogue pipe IDs found')
    server=ThreadingHTTPServer(('127.0.0.1',args.port),partial(Handler,directory=str(dashboard)))
    server.ut_log_root=[args.log_root,Path.home()/'AppData/LocalLow/MAEK/MAEK Thermal and UT V6/MAEK-worker-ut'];server.known_pipes=known
    from thermal_scene import ThermalStore
    server.thermal=ThermalStore(args.thermal_dir)
    print(f'UT dashboard: http://127.0.0.1:{args.port}/index.html?tab=home&pipe=BF1-Q005',flush=True)
    server.serve_forever()


if __name__=='__main__':main()
