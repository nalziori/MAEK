using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
namespace MAEK.Editor {
 public static class BuildSupplementaryCircuits {
  const string Root="Assets/MAEK/";
  public static readonly string Output=Path.GetFullPath("../../visualization/supplementary_circuits");
  static Transform root;static SupplementaryData data;static Material steel,oxygen,rust,concrete;
  static SupplementaryNode Node(string id)=>data.nodes.Single(n=>n.id==id);
  static Material Mat(string name,Color color,float weather){
   string path=Root+"Generated/Realism/"+name+".mat";var m=AssetDatabase.LoadAssetAtPath<Material>(path);
   if(!m){m=new Material(Shader.Find("MAEK/WeatheredSteel"));AssetDatabase.CreateAsset(m,path);}m.color=color;m.SetFloat("_Rust",weather);m.SetFloat("_Metallic",.4f);m.SetFloat("_Glossiness",.2f);return m;
  }
  static GameObject Part(string name,PrimitiveType type,Vector3 p,Vector3 scale,Material mat,Transform parent=null,Quaternion? rotation=null){
   var g=GameObject.CreatePrimitive(type);g.name=name;g.layer=8;g.transform.SetParent(parent?parent:root);g.transform.SetPositionAndRotation(p,rotation??Quaternion.identity);g.transform.localScale=scale;g.GetComponent<Renderer>().sharedMaterial=mat;return g;
  }
  static GameObject Tube(string name,Vector3 a,Vector3 b,float radius,Material mat,Transform parent=null)=>Part(name,PrimitiveType.Cylinder,(a+b)/2,new Vector3(radius*2,Vector3.Distance(a,b)/2,radius*2),mat,parent,Quaternion.FromToRotation(Vector3.up,b-a));
  static void Label(string text,Vector3 p,float size){
   var g=new GameObject(text);g.transform.SetParent(root);g.transform.position=p;var t=g.AddComponent<TextMesh>();t.text=text;t.characterSize=size;t.fontSize=48;t.anchor=TextAnchor.MiddleCenter;t.color=Color.white;g.AddComponent<MAEKSurfaceMarking>().purpose="Virtual circuit diagram annotation, not painted equipment text";g.layer=2;
  }
  public static void Apply(MAEKInspectionTour tour){
   Directory.CreateDirectory(Output);data=JsonUtility.FromJson<SupplementaryData>(File.ReadAllText(Root+"Source/supplementary_circuits.json"));
   root=new GameObject("MAEK oxygen and sinter reference annex").transform;
   steel=Mat("Supplementary steel",new Color(.40f,.47f,.50f),.16f);oxygen=Mat("Oxygen exterior",new Color(.55f,.63f,.65f),.10f);rust=Mat("Supplementary weathered exterior",new Color(.42f,.44f,.44f),.72f);concrete=Mat("Supplementary concrete",new Color(.36f,.36f,.32f),0);
   Part("Annex yard - joins original yard at x=165",PrimitiveType.Cube,new Vector3(215,-.3f,-3),new Vector3(100,.5f,85),concrete);
   foreach(var l in data.lines){
    var g=new GameObject(l.id);g.transform.SetParent(root);g.AddComponent<MAEKSupplementaryLine>().lineId=l.id;
    var a=Node(l.from).position;var b=Node(l.to).position;var m=l.id=="O2-L007"||l.id=="SINTER-D005"?rust:l.circuit=="O2"?oxygen:steel;
    if(l.id=="SINTER-D006")Part("Bag filter casing / inlet-to-outlet internal span",PrimitiveType.Cube,(a+b)/2,new Vector3(12,8,6),steel,g.transform);
    else Tube("Connected span "+l.id,a,b,l.id=="O2-L003"?.48f:l.id=="SINTER-D008"?1.45f:l.radius,m,g.transform);
    // Supports end at the pipe underside; no support crosses the lumen.
    if(l.id=="SINTER-D006"){
     foreach(float x in new[]{218f,226f})foreach(float z in new[]{6f,10f})Part("Bag filter column",PrimitiveType.Cube,new Vector3(x,3.475f,z),new Vector3(.3f,7.05f,.3f),steel);
     foreach(float x in new[]{219f,225f}){Part("Dust hopper",PrimitiveType.Cube,new Vector3(x,5.2f,8),new Vector3(3,3.6f,3),steel);Tube("Closed dust discharge to collection bin",new Vector3(x,3.4f,8),new Vector3(x,1.5f,8),.25f,steel);Part("Dust collection bin",PrimitiveType.Cube,new Vector3(x,.725f,8),new Vector3(3,1.55f,3),steel);}
    } else if(Mathf.Abs(a.y-b.y)<.01f){var p=(a+b)/2;float radius=l.id=="O2-L003"?.48f:l.id=="SINTER-D008"?1.45f:l.radius;float top=p.y-radius;Part("Pipe pedestal "+l.id,PrimitiveType.Cube,new Vector3(p.x,(top-.05f)/2,p.z),new Vector3(.18f,top+.05f,.18f),steel);}
   }
   foreach(var n in data.nodes){
    var adjacent=data.lines.Where(l=>l.from==n.id||l.to==n.id).ToArray();
    if(n.kind=="junction"){
     // A single elbow/tee envelope closes the common port, not detached end caps.
     Part("Joint "+n.id,PrimitiveType.Sphere,n.position,Vector3.one*adjacent.Max(l=>l.radius)*2,steel);
    }
    if(n.kind=="valve"||n.kind=="meter"||n.kind=="control"){
     Part("Inline "+n.kind+" "+n.id,PrimitiveType.Sphere,n.position,Vector3.one*.54f,oxygen);
     Tube("Instrument stem "+n.id,n.position+Vector3.up*.27f,n.position+Vector3.up*.75f,.045f,steel);
     Part("Operator / meter face "+n.id,PrimitiveType.Cube,n.position+Vector3.up*.85f,new Vector3(.5f,.2f,.2f),steel);
    }
    if(n.kind=="source"&&n.circuit=="SINTER"){
     Part("Enclosed material transfer hood "+n.id,PrimitiveType.Cube,n.position+Vector3.down*.6f,new Vector3(4,1.2f,4),steel);
     Part("Material transfer enclosure "+n.id,PrimitiveType.Cube,n.position+Vector3.down*3.625f,new Vector3(3,4.85f,3),steel);
    }
   }
   Label("OXYGEN SUPPLY | REFERENCE / FICTIONAL LAYOUT",new Vector3(200,2,-30.4f),.18f);
   Label("SINTER SECONDARY DEDUSTING | NOT PRIMARY OFF-GAS",new Vector3(222,12,4.97f),.20f);
   Label("SUPPLY BOUNDARY",new Vector3(180,5,-30),.12f);Label("CONSUMER INLET BOUNDARY",new Vector3(220,5,-30),.12f);
   Label("CLEAN EXHAUST",new Vector3(252,29,8),.20f);
   var points=new List<TourPoint>{new TourPoint{position=new Vector3(170,42,-64),target=new Vector3(210,10,0),speed=12}};
   var visits=new List<PipeVisit>();var transfers=new List<PipeTransfer>();string previous="ANNEX_OVERVIEW";
   foreach(var l in data.lines){var a=Node(l.from).position;var b=Node(l.to).position;var mid=(a+b)/2;var camera=mid+(l.circuit=="O2"?new Vector3(0,3,-7):new Vector3(0,7,-(mid.z+6)));
    if(l.id=="SINTER-D003")camera=mid+new Vector3(6,.5f,0); // Side view avoids the overhead branch obscuring the riser.
    int start=points.Count-1;points.Add(new TourPoint{position=camera,target=mid,speed=8,routePipeId=l.id});
    transfers.Add(new PipeTransfer{fromPipe=previous,toPipe=l.id,firstLeg=start,lastLeg=points.Count-1,length=Vector3.Distance(points[start].position,camera)});
    int index=points.Count;points.Add(new TourPoint{position=camera,target=mid,speed=3,dwell=.4f,routePipeId=l.id,pipeId=l.id,phase="inspection",sampleId=l.id+"/000"});
    visits.Add(new PipeVisit{pipeId=l.id,firstLeg=index,lastLeg=index,captures=1});previous=l.id;
   }
   var plan=new TourPlan{basis="Separate public-reference annex: 17 connected spans including filter/fan equipment interiors; sampled RGB only. Original 247 tour retained independently.",points=points.ToArray(),pipeIds=data.lines.Select(l=>l.id).ToArray(),visits=visits.ToArray(),transfers=transfers.ToArray(),expectedCaptures=data.lines.Length};
   for(int i=1;i<points.Count;i++)plan.distanceM+=Vector3.Distance(points[i-1].position,points[i].position);
   string route=Root+"Source/supplementary_tour.json";File.WriteAllText(route,JsonUtility.ToJson(plan,true));AssetDatabase.ImportAsset(route);
   var extension=tour.gameObject.AddComponent<MAEKSupplementaryCircuits>();extension.definitions=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"Source/supplementary_circuits.json");extension.inspectionRoute=AssetDatabase.LoadAssetAtPath<TextAsset>(route);extension.originalRoute=tour.routeData;extension.Initialize();
   Physics.SyncTransforms();
  }
  [Serializable] class Check {public string name,detail;public bool pass;}
  [Serializable] class Report {public string status,scope;public int lines,joints,colliders,routeSegments,views,requiredViews,deferredViews;public bool siteFirst;public Check[] checks;}
  static bool Related(Collider a,Collider b){
   var x=a.GetComponentInParent<MAEKSupplementaryLine>();var y=b.GetComponentInParent<MAEKSupplementaryLine>();
   if(x&&y){var l=data.lines.Single(v=>v.id==x.lineId);var r=data.lines.Single(v=>v.id==y.lineId);return x==y||new[]{l.from,l.to}.Intersect(new[]{r.from,r.to}).Any();}
   foreach(var n in data.nodes){if(a.name=="Joint "+n.id||a.name=="Inline "+n.kind+" "+n.id){if(y){var l=data.lines.Single(v=>v.id==y.lineId);if(l.from==n.id||l.to==n.id)return true;}}if(b.name=="Joint "+n.id||b.name=="Inline "+n.kind+" "+n.id){if(x){var l=data.lines.Single(v=>v.id==x.lineId);if(l.from==n.id||l.to==n.id)return true;}}}
   return false;
  }
  public static void Audit(){
   Directory.CreateDirectory(Output);data=JsonUtility.FromJson<SupplementaryData>(File.ReadAllText(Root+"Source/supplementary_circuits.json"));root=GameObject.Find("MAEK oxygen and sinter reference annex").transform;Physics.SyncTransforms();
   var checks=new List<Check>();Action<string,bool,string> check=(n,p,d)=>checks.Add(new Check{name=n,pass=p,detail=d});
   var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();tour.Initialize();var ext=tour.GetComponent<MAEKSupplementaryCircuits>();ext.Initialize();ext.Validate();check("typed directed topology",true,"Oxygen isolated from dust gas; every declared node reachable from source and sink present");
   foreach(var l in data.lines){var g=root.GetComponentsInChildren<MAEKSupplementaryLine>().Single(v=>v.lineId==l.id);var r=g.GetComponentInChildren<Renderer>();var a=Node(l.from).position;var b=Node(l.to).position;
    // Bounds include equipment casings. Endpoint equality additionally checks the generated mesh axis.
    var t=r.transform;var pa=t.TransformPoint(r.GetComponent<MeshFilter>().sharedMesh.bounds.center+Vector3.up*r.GetComponent<MeshFilter>().sharedMesh.bounds.extents.y);var pb=t.TransformPoint(r.GetComponent<MeshFilter>().sharedMesh.bounds.center-Vector3.up*r.GetComponent<MeshFilter>().sharedMesh.bounds.extents.y);
    bool ends=l.id=="SINTER-D006"?Mathf.Abs(r.bounds.min.x-a.x)<.001f&&Mathf.Abs(r.bounds.max.x-b.x)<.001f:Vector3.Distance(pa,b)<.001f&&Vector3.Distance(pb,a)<.001f;
    check("ports "+l.id,ends,a+" -> "+b);
   }
   var colliders=root.GetComponentsInChildren<Collider>();var pairs=new HashSet<string>();
   foreach(var c in colliders){check("physical collider "+c.name,c.enabled&&c.gameObject.layer==8,"");foreach(var other in Physics.OverlapBox(c.bounds.center,c.bounds.extents,Quaternion.identity,1<<8)){
    if(c==other)continue;var key=Math.Min(c.GetInstanceID(),other.GetInstanceID())+"/"+Math.Max(c.GetInstanceID(),other.GetInstanceID());if(!pairs.Add(key))continue;
    bool collision=Physics.ComputePenetration(c,c.transform.position,c.transform.rotation,other,other.transform.position,other.transform.rotation,out _,out float depth)&&depth>.015f;
    check("clash "+c.name+" / "+other.name,!collision||Related(c,other),collision?"depth="+depth+"; only shared declared ports exempt":"clear");
   }}
   var plan=JsonUtility.FromJson<TourPlan>(ext.inspectionRoute.text);
   foreach(var p in plan.points.Where(p=>p.pipeId!="")){var d=p.target-p.position;check("view "+p.pipeId,SiteInspectionPlanner.VisibleSamples(p.position,p.target,p.pipeId)>0,"sampled first-hit target visibility");}
   for(int i=1;i<plan.points.Length;i++)check("supplementary flight "+i,tour.SegmentClear(plan.points[i-1].position,plan.points[i].position),"");
   check("original catalogue untouched",UnityEngine.Object.FindObjectsByType<MAEKPipeService>(FindObjectsSortMode.None).Length==247,"");
   var report=new Report{status=checks.All(c=>c.pass)?"PASS":"FAIL",scope="Saved fixed scene: exact span ports; typed reachability; physical penetration checks. Only accessible scheduled views and configured-radius routes are executed; omitted observations stay deferred. Not hydraulic or structural certification.",siteFirst=plan.siteFirst,requiredViews=plan.siteFirst?plan.requiredCaptures:plan.expectedCaptures,deferredViews=plan.siteFirst?plan.access.Count(a=>!a.accessible):0,lines=data.lines.Length,joints=data.nodes.Length,colliders=colliders.Length,routeSegments=plan.points.Length-1,views=plan.expectedCaptures,checks=checks.ToArray()};
   File.WriteAllText(Path.Combine(Output,"connections_colliders.json"),JsonUtility.ToJson(report,true));Debug.Log("MAEK_SUPPLEMENTARY_"+report.status+" checks="+checks.Count);
   if(report.status!="PASS")throw new Exception(string.Join("; ",checks.Where(c=>!c.pass).Take(16).Select(c=>c.name+": "+c.detail)));
   var camera=new GameObject("Supplementary reference camera").AddComponent<Camera>();camera.enabled=false;camera.farClipPlane=1600;camera.nearClipPlane=.03f;
   CaptureFactoryPhotos.Capture(camera,Output,"01_annex",new Vector3(160,40,-70),new Vector3(215,10,0),60);
   CaptureFactoryPhotos.Capture(camera,Output,"02_oxygen",new Vector3(198,11,-50),new Vector3(200,4,-30),65);
   CaptureFactoryPhotos.Capture(camera,Output,"03_sinter",new Vector3(194,30,-27),new Vector3(220,12,10),65);UnityEngine.Object.DestroyImmediate(camera.gameObject);
  }
 }
}
