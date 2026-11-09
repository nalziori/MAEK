using System;
using System.IO;
using System.Linq;
using UnityEngine;
namespace MAEK {
 [Serializable] public class SupplementaryNode {public string id,circuit,kind;public Vector3 position;}
 [Serializable] public class SupplementaryLine {public string id,circuit,from,to;public float radius;}
 [Serializable] public class SupplementaryCircuit {public string id,label,medium,chain,followUp,workerContext,limit,source;}
 [Serializable] public class SupplementaryData {public int version;public string scope,flowBasis;public SupplementaryCircuit[] circuits;public SupplementaryNode[] nodes;public SupplementaryLine[] lines;}
 // One capture/projection/recording engine, two explicitly separate catalogues.
 [DefaultExecutionOrder(-100)]
 public sealed class MAEKSupplementaryCircuits:MonoBehaviour {
  public TextAsset definitions,inspectionRoute,originalRoute;
  public SupplementaryData Data {get;private set;}
  MAEKInspectionTour tour;GUIStyle label,button;Font font;
  public bool Selected {get;private set;}
  public static string TargetId(Collider c){var original=c.GetComponentInParent<MAEKPipeService>();return original?original.lineId:c.GetComponentInParent<MAEKSupplementaryLine>()?.lineId;}
  public void Initialize(){if(Data!=null)return;Data=JsonUtility.FromJson<SupplementaryData>(definitions.text);tour=GetComponent<MAEKInspectionTour>();Validate();
   var annex=GameObject.Find("MAEK oxygen and sinter reference annex");if(annex)foreach(var t in annex.GetComponentsInChildren<TextMesh>())t.transform.rotation=Quaternion.identity;
  }
  public void Validate(){
   if(Data==null||Data.version!=1||Data.circuits.Length!=2||Data.lines.Length!=17||Data.nodes.Select(n=>n.id).Distinct().Count()!=Data.nodes.Length||Data.lines.Select(l=>l.id).Distinct().Count()!=17)throw new Exception("Invalid supplementary catalogue");
   foreach(var l in Data.lines){var a=Data.nodes.Single(n=>n.id==l.from);var b=Data.nodes.Single(n=>n.id==l.to);if(a.circuit!=l.circuit||b.circuit!=l.circuit||l.radius<=0||Vector3.Distance(a.position,b.position)<.01f)throw new Exception("Disconnected/mixed supplementary line "+l.id);}
   foreach(var c in Data.circuits){var nodes=Data.nodes.Where(n=>n.circuit==c.id).ToArray();var sources=nodes.Where(n=>n.kind=="source").Select(n=>n.id).ToArray();var reached=new System.Collections.Generic.HashSet<string>(sources);for(int i=0;i<nodes.Length;i++)foreach(var l in Data.lines.Where(l=>l.circuit==c.id&&reached.Contains(l.from)))reached.Add(l.to);if(reached.Count!=nodes.Length||!nodes.Any(n=>n.kind=="sink"))throw new Exception("Unreachable supplementary equipment "+c.id);}
  }
  public SupplementaryLine Line(string id){Initialize();return Data.lines.FirstOrDefault(l=>l.id==id);}
  public SupplementaryCircuit Circuit(string id){var line=Line(id);return line==null?null:Data.circuits.Single(c=>c.id==line.circuit);}
  public void Select(bool supplementary,bool begin=true){Initialize();if(tour.Active)tour.End();Selected=supplementary;tour.SetRoute(supplementary?inspectionRoute:originalRoute);if(begin)tour.Begin();}
  void Start(){Initialize();}
  void Update(){if(Input.GetKeyDown(KeyCode.E))Select(true);if(Selected&&Input.GetKeyDown(KeyCode.T))Select(false,false);}
  void OnGUI(){
   if(Data==null)return;if(label==null){font=Font.CreateDynamicFontFromOSFont(new[]{"Malgun Gothic","Arial"},14);label=new GUIStyle(GUI.skin.label){font=font,fontSize=14,wordWrap=true};button=new GUIStyle(GUI.skin.button){font=font,fontSize=14};}
   if(GUI.Button(new Rect(Screen.width-320,12,308,34),Selected?"247개 원래 계통으로 돌아가기 (T)":"산소·소결 추가 17구간 검사 (E)",button)){Select(!Selected);}
   if(!Selected)return;var c=Circuit(tour.CurrentPipe);
   GUI.Box(new Rect(Screen.width-350,54,338,136),"");
   GUI.Label(new Rect(Screen.width-338,64,314,120),"공개 계통 참고 / 가상 배치\n"+(c==null?"산소 공급 → 소결 2차 집진 연속 검사":c.label+"\n"+c.chain)+"\nRGB 외관 후보만 · 작업 허가 미판정\n운전 압력·유량 및 집진 성능 미보정",label);
  }
 }
}
