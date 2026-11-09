using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
namespace MAEK {
 [Serializable] public class PipeServiceDefinition {
  public string code,labelKo,labelEn,medium,purpose,route,condition,inspection; public float[] color;
 }
 [Serializable] public class ServicePoint {public float[] position;}
 [Serializable] public class ServicePipe {
  public string id,serviceCode,medium,fromNode,toNode,state,fromEquipment,toEquipment,flowBasis,pressureBasis,materialBasis;
  public bool directionResolved,newGeometry;public float radius,length;public ServicePoint[] points;
 }
 [Serializable] public class UtilityAsset {public string id,label,shape,mountOn;public float[] position,size,color;}
 [Serializable] public class PipeServiceData {
  public int version; public string basis,colorBasis,coordinateMap; public float[] utilityOrigin;
  public PipeServiceDefinition[] services;public ServicePipe[] pipes;public UtilityAsset[] utilityAssets;
 }
 public sealed class MAEKPipeServices:MonoBehaviour {
  public bool showInterface=true;public TextAsset definitions;public bool colorOverlay=true;
  public PipeServiceData Data {get;private set;} public string SelectedId {get;private set;}
  public int BoundPipeCount {get{return assets.Count;}}
  readonly Dictionary<string,MAEKPipeService> assets=new Dictionary<string,MAEKPipeService>();
  readonly Dictionary<string,ServicePipe> pipes=new Dictionary<string,ServicePipe>();
  readonly Dictionary<string,PipeServiceDefinition> services=new Dictionary<string,PipeServiceDefinition>();
  readonly Dictionary<Renderer,MaterialPropertyBlock> oldBlocks=new Dictionary<Renderer,MaterialPropertyBlock>();
  bool initialized,show=true;string filter="",lastDroneId="";Vector2 listScroll,panelScroll;Font koreanFont;GUIStyle label,button;
  public static Vector3 V(float[] p){return new Vector3(p[0],p[2],p[1]);}
  public bool PointerOverPanel(Vector2 screenPoint){if(!showInterface||!show||!enabled)return false;float width=Mathf.Min(405,Screen.width*.43f);return new Rect(Screen.width-width-12,12,width,Screen.height-24).Contains(new Vector2(screenPoint.x,Screen.height-screenPoint.y));}
  public void Initialize(){if(initialized)return;initialized=true;Data=JsonUtility.FromJson<PipeServiceData>(definitions.text);foreach(var d in Data.services)services[d.code]=d;foreach(var p in Data.pipes)pipes[p.id]=p;
   foreach(var a in FindObjectsByType<MAEKPipeService>(FindObjectsSortMode.None)){if(!pipes.ContainsKey(a.lineId))continue;assets.Add(a.lineId,a);foreach(var r in a.GetComponentsInChildren<Renderer>()){var block=new MaterialPropertyBlock();r.GetPropertyBlock(block);oldBlocks[r]=block;}}
   SelectedId=Data.pipes[0].id;ApplyColors();
  }
  void Start(){Initialize();}
  public void SelectPipe(string id){Initialize();if(!pipes.ContainsKey(id))throw new ArgumentException("Unknown pipe "+id);SelectedId=id;ApplyColors();}
  public void SetFilter(string code){Initialize();if(code!=""&&!services.ContainsKey(code))throw new ArgumentException("Unknown service "+code);filter=code;if(code!=""&&pipes[SelectedId].serviceCode!=code)SelectedId=Data.pipes.First(p=>p.serviceCode==code).id;ApplyColors();}
  public void SetOverlay(bool active){Initialize();colorOverlay=active;ApplyColors();}
  public void ApplyColors(){foreach(var pair in assets){var p=pipes[pair.Key];var def=services[p.serviceCode];var c=new Color(def.color[0],def.color[1],def.color[2]);if(filter!=""&&filter!=p.serviceCode)c=new Color(.15f,.17f,.19f);foreach(var r in pair.Value.GetComponentsInChildren<Renderer>()){if(!colorOverlay){r.SetPropertyBlock(oldBlocks[r]);continue;}var block=new MaterialPropertyBlock();block.SetColor("_Color",c);if(p.id==SelectedId)block.SetColor("_EmissionColor",c*.2f);r.SetPropertyBlock(block);}}}
  public void FocusSelected(){var cfd=FindFirstObjectByType<MAEKCFDPlayback>();if(cfd&&cfd.ActiveView)cfd.SetView(false);var drone=FindFirstObjectByType<MAEKDroneInspection>();if(drone){drone.enabled=true;drone.InspectLine(SelectedId);lastDroneId=drone.CurrentLineId;}}
  public void SynchronizeInspectionSelection(){var drone=FindFirstObjectByType<MAEKDroneInspection>();if(!drone||!drone.enabled||!drone.InspectionActive){lastDroneId="";return;}if(drone.CurrentLineId==lastDroneId)return;lastDroneId=drone.CurrentLineId;if(pipes.ContainsKey(lastDroneId)){if(filter!=""&&pipes[lastDroneId].serviceCode!=filter)filter="";SelectPipe(lastDroneId);}}
  void Update(){if(Input.GetKeyDown(KeyCode.M))show=!show;if(Input.GetKeyDown(KeyCode.L))SetOverlay(!colorOverlay);
   SynchronizeInspectionSelection();
   if(!Input.GetKeyDown(KeyCode.E))return;var camera=FindObjectsByType<Camera>(FindObjectsSortMode.None).FirstOrDefault(c=>c.enabled);if(!camera)return;var ray=camera.ViewportPointToRay(new Vector3(.5f,.5f,0));if(Physics.Raycast(ray,out var hit,300,1<<8,QueryTriggerInteraction.Ignore)){var info=hit.collider.GetComponentInParent<MAEKPipeService>();if(info)SelectPipe(info.lineId);}
  }
  void Styles(){if(label!=null)return;koreanFont=Font.CreateDynamicFontFromOSFont(new[]{"Malgun Gothic","맑은 고딕","Noto Sans CJK KR","Arial"},15);label=new GUIStyle(GUI.skin.label){font=koreanFont,wordWrap=true,fontSize=15};button=new GUIStyle(GUI.skin.button){font=koreanFont,wordWrap=true,fontSize=14};}
  void OnGUI(){if(!showInterface||!initialized||!show)return;Styles();float width=Mathf.Min(405,Screen.width*.43f);var area=new Rect(Screen.width-width-12,12,width,Screen.height-24);GUI.Box(area,"");GUILayout.BeginArea(new Rect(area.x+12,area.y+10,area.width-24,area.height-20));panelScroll=GUILayout.BeginScrollView(panelScroll);
   GUILayout.Label("MAEK 배관 계통 / 용도",label);GUILayout.Label("E: 조준 배관 선택  ·  L: 색상  ·  M: 패널",label);
   var hydraulic=FindFirstObjectByType<MAEKHydraulicFlow>();if(hydraulic)hydraulic.DrawControls(label,button);
   if(GUILayout.Button(colorOverlay?"계통 색상 표시 중 / 원래 재질 보기":"계통 색상 켜기",button))SetOverlay(!colorOverlay);
   GUILayout.Label("시연용 색상 · 실제 현장 식별 규정 아님",label);
   listScroll=GUILayout.BeginScrollView(listScroll,GUILayout.Height(190));if(GUILayout.Button("전체 계통 ("+Data.pipes.Length+")",button))SetFilter("");foreach(var d in Data.services){int count=Data.pipes.Count(p=>p.serviceCode==d.code);var old=GUI.backgroundColor;GUI.backgroundColor=new Color(d.color[0],d.color[1],d.color[2]);if(GUILayout.Button((filter==d.code?"● ":"")+d.labelKo+" ("+count+")",button))SetFilter(d.code);GUI.backgroundColor=old;}GUILayout.EndScrollView();
   var choices=Data.pipes.Where(p=>filter==""||p.serviceCode==filter).ToArray();int selected=Array.FindIndex(choices,p=>p.id==SelectedId);GUILayout.BeginHorizontal();if(GUILayout.Button("이전 배관",button)&&choices.Length>0)SelectPipe(choices[(selected-1+choices.Length)%choices.Length].id);if(GUILayout.Button("다음 배관",button)&&choices.Length>0)SelectPipe(choices[(selected+1)%choices.Length].id);GUILayout.EndHorizontal();
   var pipe=pipes[SelectedId];var service=services[pipe.serviceCode];GUILayout.Label(pipe.id+"  |  "+service.labelKo,label);GUILayout.Label(service.purpose,label);GUILayout.Label("계통: "+service.route,label);GUILayout.Label("시작: "+pipe.fromNode+"\n끝: "+pipe.toNode,label);if(hydraulic)hydraulic.DrawPipe(pipe.id,label);else{GUILayout.Label("상태: "+pipe.state+"\n"+pipe.flowBasis,label);GUILayout.Label(service.condition,label);}GUILayout.Label("모델 외경 "+(pipe.radius*2).ToString("F2")+" m (실제 DN 아님)\n중심선 근사 길이 "+pipe.length.ToString("F1")+" m",label);GUILayout.Label("현장 압력: "+pipe.pressureBasis+"\n"+pipe.materialBasis,label);GUILayout.Label("MAEK 확인 항목: "+service.inspection,label);
   if(pipe.newGeometry)GUILayout.Label("별도 가상 유틸리티 시험 구역입니다. 실제 고로 공정과 연결했다고 가정하지 않습니다.",label);
   if(GUILayout.Button("이 배관으로 검사 카메라 이동",button))FocusSelected();GUILayout.Label(hydraulic?"계통 선택은 표시 필터입니다. 수치는 가정 경계조건으로 계산한 값이며 현장 측정값이 아닙니다.":"연결·용도 정보이며 배관 유량/압력 해석 결과가 아닙니다. CFD 결과도 이 설정으로 재계산되지 않습니다.",label);
   GUILayout.EndScrollView();GUILayout.EndArea();
  }
  public void RestoreColors(){foreach(var item in oldBlocks)if(item.Key)item.Key.SetPropertyBlock(item.Value);}
 }
}
