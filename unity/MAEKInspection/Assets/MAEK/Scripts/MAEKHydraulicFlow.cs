using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;

namespace MAEK {
 [Serializable] public class HydraulicPipe {
  public string id,state;
  public float pressureFromPa,pressureToPa,massKgS,volumeM3S,volumeFromM3S,volumeToM3S;
  public float velocityMS,reynolds,mach,insideDiameterM,temperatureK;
 }
 [Serializable] public class HydraulicFurnace {
  public string unit;public float top_pressure_pa_abs,gas_feed_m3_s,blast_mass_kg_s;
  public float coupling_pressure_residual_pa;
 }
 [Serializable] public class HydraulicCase {
  public string id,label,clipName;public HydraulicPipe[] pipes;public HydraulicFurnace[] furnaces;
  public float pressureResidual,massResidual;
 }
 [Serializable] public class HydraulicDataset {
  public int version;public float atmospherePa;public string basis,coupling,scope;
  public HydraulicCase[] scenarios;
 }
 public sealed class MAEKHydraulicFlow:MonoBehaviour {
  public TextAsset results;public TextAsset[] coupledClips;public Material flowMaterial;
  public bool showFlow=true,onlySelected=false;public float playbackScale=.1f;
  public HydraulicDataset Data {get;private set;}public int CaseIndex {get;private set;}
  public int VisibleArrowCount {get;private set;}
  public HydraulicCase Current {get{return Data.scenarios[CaseIndex];}}
  MAEKPipeServices services;MAEKCFDPlayback cfd;Mesh flowMesh;GameObject glyphObject;
  Dictionary<string,HydraulicPipe> values;readonly Dictionary<string,Vector3[]> paths=new Dictionary<string,Vector3[]>();
  readonly Dictionary<string,float[]> distances=new Dictionary<string,float[]>();
  readonly List<Vector3> vertices=new List<Vector3>();readonly List<int> triangles=new List<int>();
  readonly List<Color> colors=new List<Color>();bool initialized;float elapsed;
  public void Initialize(){if(initialized)return;initialized=true;Data=JsonUtility.FromJson<HydraulicDataset>(results.text);
   if(Data.version!=1||coupledClips.Length!=Data.scenarios.Length)throw new Exception("Hydraulic data mismatch");
   services=FindFirstObjectByType<MAEKPipeServices>();services.Initialize();cfd=FindFirstObjectByType<MAEKCFDPlayback>();
   foreach(var p in services.Data.pipes){var pts=p.points.Select(q=>MAEKPipeServices.V(q.position)).ToArray();paths[p.id]=pts;var lengths=new float[pts.Length];for(int k=1;k<pts.Length;k++)lengths[k]=lengths[k-1]+Vector3.Distance(pts[k],pts[k-1]);distances[p.id]=lengths;}
   glyphObject=new GameObject("Calculated signed pipe-flow arrows",typeof(MeshFilter),typeof(MeshRenderer));glyphObject.transform.SetParent(transform,false);
   flowMesh=new Mesh{name="Hydraulic flow vectors",indexFormat=UnityEngine.Rendering.IndexFormat.UInt32};flowMesh.MarkDynamic();glyphObject.GetComponent<MeshFilter>().sharedMesh=flowMesh;glyphObject.GetComponent<MeshRenderer>().sharedMaterial=flowMaterial;glyphObject.GetComponent<MeshRenderer>().shadowCastingMode=UnityEngine.Rendering.ShadowCastingMode.Off;
   SelectCase(0);
  }
  void Start(){Initialize();}
  public HydraulicPipe Pipe(string id){return values!=null&&values.ContainsKey(id)?values[id]:null;}
  public void SelectCase(int index){if(!initialized)Initialize();CaseIndex=Mathf.Clamp(index,0,Data.scenarios.Length-1);values=Current.pipes.ToDictionary(p=>p.id);if(values.Count!=paths.Count)throw new Exception("Missing hydraulic pipes");foreach(var id in paths.Keys)if(!values.ContainsKey(id))throw new Exception("Missing result "+id);elapsed=0;cfd.ReplaceResults(coupledClips[CaseIndex]);RenderFlowAtTime(0);}
  void Update(){if(Input.GetKeyDown(KeyCode.Y))SelectCase((CaseIndex+1)%Data.scenarios.Length);if(Input.GetKeyDown(KeyCode.V))showFlow=!showFlow;elapsed+=Time.deltaTime;RenderFlowAtTime(elapsed);}
  void Triangle(Vector3 a,Vector3 b,Vector3 c,Color color){int n=vertices.Count;vertices.Add(a);vertices.Add(b);vertices.Add(c);triangles.Add(n);triangles.Add(n+1);triangles.Add(n+2);colors.Add(color);colors.Add(color);colors.Add(color);}
  void Arrow(Vector3 p,Vector3 tangent,float size,Color color){var side=Vector3.Cross(tangent,Vector3.up);if(side.sqrMagnitude<.01f)side=Vector3.right;side.Normalize();var other=Vector3.Cross(tangent,side);foreach(var normal in new[]{side,other}){Triangle(p+tangent*size,p-tangent*size*.5f+normal*size*.45f,p-tangent*size*.5f-normal*size*.45f,color);}VisibleArrowCount++;}
  public void RenderFlowAtTime(float time){if(!initialized)return;vertices.Clear();triangles.Clear();colors.Clear();VisibleArrowCount=0;
   if(showFlow)foreach(var pipe in services.Data.pipes){var v=Pipe(pipe.id);if(v==null||v.state!="flowing"||Mathf.Abs(v.massKgS)<1e-7f||(onlySelected&&pipe.id!=services.SelectedId))continue;var pts=paths[pipe.id];var ds=distances[pipe.id];float length=ds[ds.Length-1];if(length<1e-5f)continue;int count=Mathf.Clamp(Mathf.CeilToInt(length/12),2,12);for(int k=0;k<count;k++){float s=Mathf.Repeat((k+.25f)*length/count+time*playbackScale*v.velocityMS,length);int j=1;while(j<ds.Length-1&&ds[j]<s)j++;var tangent=(pts[j]-pts[j-1]).normalized;var point=Vector3.Lerp(pts[j-1],pts[j],(s-ds[j-1])/Mathf.Max(1e-6f,ds[j]-ds[j-1]));var offset=Vector3.ProjectOnPlane(Vector3.up,tangent);if(offset.sqrMagnitude<.01f)offset=Vector3.left;point+=offset.normalized*(pipe.radius*1.15f+.035f);var color=pipe.id==services.SelectedId?Color.white:new Color(.15f,1,.75f,1);Arrow(point,tangent*Mathf.Sign(v.velocityMS),Mathf.Clamp(pipe.radius*.8f,.08f,.8f),color);}}
   flowMesh.Clear();flowMesh.SetVertices(vertices);flowMesh.SetTriangles(triangles,0);flowMesh.SetColors(colors);flowMesh.RecalculateBounds();
  }
  public void DrawControls(GUIStyle label,GUIStyle button){if(!initialized)return;GUILayout.Label("가정 압력·유량 / 현장 미보정",label);for(int i=0;i<Data.scenarios.Length;i++)if(GUILayout.Button((i==CaseIndex?"● ":"")+Data.scenarios[i].label,button))SelectCase(i);GUILayout.Label("Y: 계산 사례 전환 · V: 흐름 표시\n배관망 ↔ 3D 충전층 / 노저부 VOF는 단방향 연동",label);if(GUILayout.Button(showFlow?"흐름 화살표 숨기기":"흐름 화살표 표시",button))showFlow=!showFlow;if(GUILayout.Button(onlySelected?"전체 배관 흐름 보기":"선택한 배관 흐름만 보기",button))onlySelected=!onlySelected;GUILayout.Label("화살표 이동: 계산 유속 × "+playbackScale.ToString("F2"),label);playbackScale=GUILayout.HorizontalSlider(playbackScale,.01f,1);GUILayout.Label("실규모 고로 운전 재현 아님 · 송풍기 Δp 3.0 kPa 가정. 사전 계산 사례이며 설정 변경 시 재계산이 필요합니다.",label);}
  public void DrawPipe(string id,GUIStyle label){var p=Pipe(id);if(p==null)return;GUILayout.Label("계산 상태: "+p.state+"\n시작점 "+((p.pressureFromPa-Data.atmospherePa)/1000).ToString("F3")+" kPa(g) / "+(p.pressureFromPa/1000).ToString("F3")+" kPa(abs)\n끝점 "+((p.pressureToPa-Data.atmospherePa)/1000).ToString("F3")+" kPa(g) / "+(p.pressureToPa/1000).ToString("F3")+" kPa(abs)",label);GUILayout.Label("질량유량 "+p.massKgS.ToString("F6")+" kg/s\n유입측 실제 체적유량 "+(p.volumeM3S*3600).ToString("F3")+" m³/h\n유속 "+p.velocityMS.ToString("F4")+" m/s\n+ 시작→끝 / − 끝→시작",label);GUILayout.Label("가정 내경 "+p.insideDiameterM.ToString("F3")+" m · "+p.temperatureK.ToString("F0")+" K\nRe "+p.reynolds.ToString("G4")+" · Mach "+p.mach.ToString("F4"),label);}
  public void DisposePreview(){if(glyphObject)DestroyImmediate(glyphObject);if(flowMesh)DestroyImmediate(flowMesh);paths.Clear();distances.Clear();initialized=false;}
 }
}
