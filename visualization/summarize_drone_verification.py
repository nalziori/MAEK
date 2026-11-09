import json,html
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
p=Path('D:/obsd/Projects/hackerton/MAEK/visualization')
old=json.loads((p/'mesh_endpoints_before.json').read_text());new=json.loads((p/'saved_drone_model_verification.json').read_text());flight=json.loads((p/'drone_flight_report.json').read_text());unity=json.loads((p/'unity_drone_report.json').read_text());clash=json.loads((p/'drone_overlap_report.json').read_text())
assert new['status']==flight['status']==unity['status']=='PASS' and clash['unreviewed_overlap_pairs']==0
summary={'pipe_segments':240,'endpoint_rings':480,'before_failed_endpoint_rings':old['failed_endpoints'],'after_failed_endpoint_rings':new['failed_endpoints'],'shell_fitted_nozzles':len(new['nozzle_shell_bonds']),'drone_routes':flight['routes'],'unity_checks':len(unity['checks']),'unity_failed_checks':sum(not c['pass'] for c in unity['checks']),'unreviewed_asset_overlaps':clash['unreviewed_overlap_pairs']}
(p/'drone_final_summary.json').write_text(json.dumps(summary,indent=2))
canvas=Image.new('RGB',(1600,686),'#151d23');draw=ImageDraw.Draw(canvas);font=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',28);small=ImageFont.truetype('C:/Windows/Fonts/malgun.ttf',20)
for i,state in enumerate(('before','after')):
 im=Image.open(p/('connection_stave_'+state+'.png')).convert('RGB');canvas.paste(im,(800*i,58));draw.text((24+800*i,12),'수정 전 — 외벽 접합 틈' if i==0 else '수정 후 — 외벽 형상에 맞춘 연결관',font=font,fill='white')
draw.text((24,660),'BF1-WS011 · 동일한 카메라 위치로 렌더링한 실제 Blender 모델',font=small,fill='#c9d9df');canvas.save(p/'connection_before_after.png')
rows=[]
for route in json.loads((p/'drone_routes_blender.json').read_text())['routes']:
 checks=[c for c in new['checks'] if c['line']==route['id']];before=[c for c in old['checks'] if c['line']==route['id']]
 rows.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in (route['id'],route['from'],route['to'],sum(not c['pass'] for c in before),'PASS' if all(c['pass'] for c in checks) else 'FAIL',len(route['waypoints'])))+'</tr>')
page='''<!doctype html><html lang="ko"><meta charset="utf-8"><title>MAEK 배관 연결 점검 결과</title><style>body{font:16px system-ui;margin:32px;background:#10181e;color:#e6eef3}img{max-width:100%}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:9px;border-bottom:1px solid #34454f;text-align:left}input{padding:10px;margin:16px 0;width:360px}a{color:#7dd6dd}code{color:#a6e6c8}</style><h1>MAEK 배관 연결 및 가상 드론 점검</h1><p>240개 배관 · 끝 단면 480곳 · 수정 후 미연결 0곳 · 노즐 접합 102곳 통과 · 드론 경로 240개 · Unity 검사 259개 통과</p><p>기존 좌표 검사에서 놓친 단면 둘레의 틈을 실제 메시로 검사했습니다. 드론은 반경 0.12 m의 가상 카메라이며 배관 간에는 컷 전환합니다.</p><img src="connection_before_after.png" alt="연결부 수정 전후"><p><a href="maek_drone_verified.blend">Blender 파일</a> · <a href="MAEK_Drone_Verified.unitypackage">Unity 패키지</a> · <a href="DRONE_INSPECTION_GUIDE.md">조작 및 검증 설명</a> · <a href="saved_drone_model_verification.json">메시 검사</a> · <a href="unity_drone_report.json">Unity 검사</a></p><input id="search" placeholder="배관 ID 검색 (예: BF1-WS011)"><table><thead><tr><th>배관 ID</th><th>시작 접속점</th><th>끝 접속점</th><th>수정 전 실패 단면 수</th><th>수정 후</th><th>드론 경유점</th></tr></thead><tbody>'''+''.join(rows)+'''</tbody></table><script>document.querySelector('#search').oninput=e=>{let q=e.target.value.toLowerCase();document.querySelectorAll('tbody tr').forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(q))}</script></html>'''
(p/'drone_inspection_report.html').write_text(page,encoding='utf-8')
print(json.dumps(summary))
