from pathlib import Path
root=Path('D:/obsd/Projects/hackerton/MAEK')
f=root/'unity/MAEKInspection/Assets/MAEK/Scripts/MAEKFurnaceSimulation.cs';s=f.read_text(encoding='utf-8-sig')
s=s.replace('if(info.assetId=="BF1.CASTHOUSE"||info.assetId=="BF2.CASTHOUSE")','if(info.assetId=="BF1.CASTHOUSE"||info.assetId=="BF2.CASTHOUSE"||info.assetId=="BF1.CONVEYOR"||info.assetId=="BF2.CONVEYOR"||info.assetId=="BF1.CASTHOUSE.CRANE"||info.assetId=="BF2.CASTHOUSE.CRANE")')
s=s.replace('bool initialized,paused,autoTap=true;int selected;double pendingTime;','bool initialized,paused,autoTap=true;int selected;double pendingTime;float orbitYaw,orbitPitch,orbitDistance;')
old='void Focus(){float x=selected==0?-62:62;processCamera.transform.position=new Vector3(x+18,44,90);processCamera.transform.LookAt(new Vector3(x,23,25));}'
new='''void Focus(){var offset=new Vector3(18,21,65);orbitDistance=offset.magnitude;orbitYaw=Mathf.Atan2(offset.x,offset.z)*Mathf.Rad2Deg;orbitPitch=Mathf.Asin(offset.y/orbitDistance)*Mathf.Rad2Deg;Orbit();}
  void Orbit(){float x=selected==0?-62:62;var target=new Vector3(x,23,25);processCamera.transform.position=target+Quaternion.Euler(-orbitPitch,orbitYaw,0)*Vector3.forward*orbitDistance;processCamera.transform.LookAt(target);}'''
assert old in s;s=s.replace(old,new)
s=s.replace('if(!ProcessView)return;if(Input.GetKeyDown(KeyCode.Alpha1))','if(!ProcessView)return;if(Input.GetMouseButton(1)){orbitYaw+=Input.GetAxis("Mouse X")*2;orbitPitch=Mathf.Clamp(orbitPitch-Input.GetAxis("Mouse Y")*2,5,70);Orbit();}float zoom=Input.GetAxis("Mouse ScrollWheel");if(Mathf.Abs(zoom)>.001f){orbitDistance=Mathf.Clamp(orbitDistance-zoom*25,35,140);Orbit();}if(Input.GetKeyDown(KeyCode.Alpha1))')
s=s.replace('P: return | 1/2: furnace | Space: pause','P: return | 1/2: furnace | Space: pause\nRight mouse: orbit | Wheel: zoom')
# Preserve the newline as a C# string escape.
s=s.replace('Space: pause\nRight mouse:', 'Space: pause\\nRight mouse:')
f.write_text(s,encoding='utf-8')
f=root/'unity/MAEKInspection/Assets/MAEK/Editor/BuildFurnaceScene.cs';s=f.read_text(encoding='utf-8-sig');needle='   check("section does not remove physical environment colliders"';idx=s.index(needle)
s=s[:idx]+'''   check("section hides occluding conveyors",UnityEngine.Object.FindObjectsByType<MAEKAssetInfo>(FindObjectsSortMode.None).Where(i=>i.assetId=="BF1.CONVEYOR"||i.assetId=="BF2.CONVEYOR").All(i=>!i.GetComponent<Renderer>().enabled),"Render-only hiding while retaining colliders");
'''+s[idx:];f.write_text(s,encoding='utf-8')
f=root/'visualization/build_furnace_physics_blender.py';s=f.read_text(encoding='utf-8-sig').replace("'BF1.CASTHOUSE','BF2.CASTHOUSE')", "'BF1.CASTHOUSE','BF2.CASTHOUSE','BF1.CONVEYOR','BF2.CONVEYOR','BF1.CASTHOUSE.CRANE','BF2.CASTHOUSE.CRANE')");s=s.replace("if aid.endswith('CASTHOUSE'):","if aid.endswith(('CASTHOUSE','CONVEYOR','CRANE')):");s=s.replace('ca.lens=24;sc.camera=cam','ca.lens=23;sc.camera=cam').replace("(600,'RUNNER DRAINED')","(600,'RESIDUAL FILM')");s=s.replace('sc.frame_set(433)','sc.render.resolution_x=1400;sc.render.resolution_y=1000;sc.render.resolution_percentage=100\nsc.frame_set(433)');f.write_text(s,encoding='utf-8')
for f in [root/'visualization/FURNACE_PHYSICS_GUIDE.md',root/'unity/MAEKInspection/Assets/MAEK/FURNACE_PHYSICS_GUIDE.md']:
 s=f.read_text(encoding='utf-8-sig').replace('- 화면 버튼으로 출선구 개폐','- 단면에서 마우스 오른쪽 버튼을 누르고 드래그하면 회전, 휠로 확대·축소합니다. 단면을 가리는 컨베이어·크레인은 이 모드에서만 시각적으로 숨기며 Collider는 유지합니다.\n- 화면 버튼으로 출선구 개폐');f.write_text(s,encoding='utf-8')
