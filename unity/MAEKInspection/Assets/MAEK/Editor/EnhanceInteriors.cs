using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEngine;
using UnityEngine.Rendering;

namespace MAEK.Editor {
 public static class EnhanceInteriors {
  const string Folder="Assets/MAEK/Generated/Interiors";
  static Transform root,group;
  static Material steel,paint,yellow,blue,silver,black,screen,white,labelMaterial;
  static int fixtures,stations,spools,omitted;
  static readonly List<string> notes=new List<string>();
  [Serializable] class Report {public string status,scope,layoutSignature;public bool layoutFirst=true;public int rooms,stations,closedSpools,physicalFixtures,omittedAssemblies;public string[] omissions;}
  static Material Mat(string name,Color c,bool glow=false){
   string path=Folder+"/"+name+".mat";var m=AssetDatabase.LoadAssetAtPath<Material>(path);
   if(!m){m=new Material(Shader.Find("Standard"));AssetDatabase.CreateAsset(m,path);}
   m.color=c;m.SetFloat("_Metallic",name.Contains("metal")?.5f:.08f);m.SetFloat("_Glossiness",.25f);
   if(glow){m.EnableKeyword("_EMISSION");m.SetColor("_EmissionColor",c*.8f);}
   return m;
  }
  static GameObject Primitive(string name,PrimitiveType type,Vector3 p,Vector3 size,Material mat,Quaternion q){
   var g=GameObject.CreatePrimitive(type);g.name=name;g.layer=8;g.transform.SetParent(group);g.transform.SetPositionAndRotation(p,q);g.transform.localScale=size;g.GetComponent<Renderer>().sharedMaterial=mat;return g;
  }
  static void Box(string n,Vector3 p,Vector3 s,Material m){Primitive(n,PrimitiveType.Cube,p,s,m,Quaternion.identity);}
  static void Tube(string n,Vector3 a,Vector3 b,float r,Material m){Primitive(n,PrimitiveType.Cylinder,(a+b)/2,new Vector3(r*2,(b-a).magnitude/2,r*2),m,Quaternion.FromToRotation(Vector3.up,b-a));}
  static void Text(string text,Vector3 p,float size,Color color){
   var g=new GameObject("Printed "+text,typeof(TextMesh),typeof(MAEKSurfaceMarking));g.transform.SetParent(group);g.transform.position=p;
   var t=g.GetComponent<TextMesh>();t.text=text;t.fontSize=64;t.characterSize=.1f;t.anchor=TextAnchor.MiddleCenter;t.alignment=TextAlignment.Center;t.color=color;
   var renderer=g.GetComponent<Renderer>();renderer.sharedMaterial=labelMaterial;g.AddComponent<MAEKPrintedLabel>().Bind(true);
   var bounds=renderer.bounds.size;if(bounds.y<=0)throw new Exception("Unmeasured printed label: "+text);
   float width=text.Contains("AISLE")?3.7f:text=="UT / DEMO"?.45f:2.6f;
   g.transform.localScale=Vector3.one*Mathf.Min(size/bounds.y,width/Mathf.Max(.001f,bounds.x));
   g.GetComponent<MAEKSurfaceMarking>().purpose="Printed equipment label; supporting object has a collider";
  }
  static void Paint(string name,Vector3 p,Vector2 size,Material mat){
   var g=GameObject.CreatePrimitive(PrimitiveType.Quad);g.name=name;g.transform.SetParent(root);g.transform.position=p;g.transform.rotation=Quaternion.Euler(90,0,0);g.transform.localScale=new Vector3(size.x,size.y,1);
   UnityEngine.Object.DestroyImmediate(g.GetComponent<Collider>());g.AddComponent<MAEKSurfaceMarking>().purpose="Floor paint on existing collision floor";
   var r=g.GetComponent<Renderer>();r.sharedMaterial=mat;r.shadowCastingMode=ShadowCastingMode.Off;
  }
  static void StartGroup(string name){group=new GameObject(name).transform;group.SetParent(root);}
  static bool FinishGroup(){
   Physics.SyncTransforms();var cols=group.GetComponentsInChildren<Collider>();string reason="";
   foreach(var c in cols){
    if(EnhanceSteelworks.Protected(c.bounds)){reason="reserved pedestrian access space";break;}
    foreach(var other in Physics.OverlapBox(c.bounds.center,c.bounds.extents,Quaternion.identity,1<<8)){
     if(other.transform.IsChildOf(group))continue;
     if(Physics.ComputePenetration(c,c.transform.position,c.transform.rotation,other,other.transform.position,other.transform.rotation,out _,out float depth)&&depth>.015f){reason="overlap "+other.name;break;}
    }
    if(reason!="")break;
   }
   var station=group.GetComponent<MAEKInteriorStation>();
   if(reason==""&&station&&!AccessClear(station.aislePoint,station.approachPoint))reason="workstation approach blocked";
   if(reason!=""){omitted++;notes.Add(group.name+": "+reason);UnityEngine.Object.DestroyImmediate(group.gameObject);return false;}
   fixtures+=cols.Length;return true;
  }
  public static bool AccessClear(Vector3 a,Vector3 b){
   var bottom=a+Vector3.up*.55f;var top=a+Vector3.up*1.65f;var d=b-a;
   return !Physics.CheckCapsule(bottom,top,.3f,1<<8)&&!Physics.CheckCapsule(bottom+d,top+d,.3f,1<<8)&&
    (d.sqrMagnitude<1e-8f||!Physics.CapsuleCast(bottom,top,.3f,d.normalized,out _,d.magnitude,1<<8));
  }
  static bool Station(AuditEnhancedColliders.Room room,float x,float z,bool spool){
   StartGroup(room.id+" / "+(spool?"closed inspection spool":"process inspection workbench"));
   var station=group.gameObject.AddComponent<MAEKInteriorStation>();station.roomId=room.id;station.role=spool?"Cold mock spool; visual training fixture, not part of 247 process IDs":"UT / PEC preparation for existing process inspection loop";
   station.aislePoint=new Vector3(room.x,0,z-1.6f);station.approachPoint=new Vector3(x,0,z-1.6f);
   Box("Bench top",new Vector3(x,.97f,z),new Vector3(3.2f,.16f,1.3f),steel);
   Box("Printed bench apron",new Vector3(x,.74f,z-.62f),new Vector3(2.9f,.3f,.06f),steel);
   foreach(float dx in new[]{-1.35f,1.35f})foreach(float dz in new[]{-.48f,.48f}){
    Box("Bench leg",new Vector3(x+dx,.52f,z+dz),new Vector3(.12f,.74f,.12f),steel);
    Box("Anchored bench foot",new Vector3(x+dx,.2f,z+dz),new Vector3(.28f,.1f,.28f),black);
   }
   Box("Bench lower shelf",new Vector3(x,.4f,z),new Vector3(2.9f,.1f,1.08f),steel);
   Box("UT instrument case",new Vector3(x+1.05f,1.23f,z-.22f),new Vector3(.65f,.35f,.45f),paint);
   Box("UT instrument display",new Vector3(x+1.05f,1.25f,z-.451f),new Vector3(.45f,.2f,.012f),screen);
   Text("UT / DEMO",new Vector3(x+1.05f,1.25f,z-.46f),.055f,Color.white);
   Box("PEC probe case",new Vector3(x-.9f,1.18f,z-.25f),new Vector3(.5f,.22f,.42f),black);
   Tube("Probe cable",new Vector3(x-.65f,1.19f,z-.25f),new Vector3(x+.6f,1.19f,z-.25f),.015f,black);
   Text(spool?"COLD TRAINING SPOOL":"MAEK  /  UT + PEC",new Vector3(x,.72f,z-.66f),.10f,Color.white);
   if(spool){
    float rz=z+.35f;var corners=new[]{new Vector3(x-1.05f,1.48f,rz),new Vector3(x+1.05f,1.48f,rz),new Vector3(x+1.05f,2.65f,rz),new Vector3(x-1.05f,2.65f,rz)};
    var vertices=new List<Vector3>();
    for(int i=0;i<4;i++){var c=corners[i];var a=c+(corners[(i+3)%4]-c).normalized*.18f;var b=c+(corners[(i+1)%4]-c).normalized*.18f;
     for(int j=0;j<=5;j++){float t=j/5f;vertices.Add((1-t)*(1-t)*a+2*(1-t)*t*c+t*t*b);}}
    for(int i=0;i<vertices.Count;i++)Tube("Closed spool tube "+i,vertices[i],vertices[(i+1)%vertices.Count],.055f,silver);
    station.closedSpoolSegments=vertices.Count;
    foreach(float dx in new[]{-.6f,.6f})Box("Spool support saddle",new Vector3(x+dx,1.2375f,rz),new Vector3(.18f,.375f,.16f),steel);
    Box("Closed loop pump body",new Vector3(x-.7f,1.48f,rz),new Vector3(.38f,.28f,.3f),blue);
    Box("Pump mounting foot",new Vector3(x-.7f,1.195f,rz),new Vector3(.38f,.29f,.3f),steel);
    foreach(float dx in new[]{-.45f,.45f})Tube("Spool bolted flange",new Vector3(x+dx-.025f,2.65f,rz),new Vector3(x+dx+.025f,2.65f,rz),.095f,steel);
    Tube("Gauge pressure stem",new Vector3(x,2.65f,rz),new Vector3(x,2.88f,rz),.025f,steel);
    Tube("Sealed pressure gauge",new Vector3(x,3.0f,rz+.04f),new Vector3(x,3.0f,rz-.04f),.14f,black);
    Tube("Gauge face",new Vector3(x,3.0f,rz-.041f),new Vector3(x,3.0f,rz-.048f),.118f,white);
    Tube("Gauge needle",new Vector3(x,3.0f,rz-.051f),new Vector3(x+.07f,3.05f,rz-.051f),.007f,black);
   }
   if(!FinishGroup())return false;
   stations++;if(spool)spools++;
   Paint("Work zone paint",new Vector3(x,.156f,z),new Vector2(3.8f,3.2f),blue);
   return true;
  }
  static void Cabinet(AuditEnhancedColliders.Room room,float x,float z){
   StartGroup(room.id+" tool store");
   Box("Tool cabinet feet",new Vector3(x,.24f,z),new Vector3(2.2f,.18f,1),black);
   Box("Tool cabinet",new Vector3(x,1.45f,z),new Vector3(2.2f,2.24f,1),blue);
   foreach(float dx in new[]{-.55f,.55f}){
    Box("Cabinet door",new Vector3(x+dx,1.45f,z-.51f),new Vector3(1.04f,2.05f,.04f),steel);
    Box("Door handle",new Vector3(x+dx+.25f,1.5f,z-.56f),new Vector3(.045f,.32f,.06f),silver);
    for(int row=0;row<4;row++)Box("Vent grille",new Vector3(x+dx,2.05f+row*.08f,z-.54f),new Vector3(.75f,.025f,.015f),black);
   }
   Text("TOOLS / PPE",new Vector3(x,2.35f,z-.55f),.13f,Color.white);FinishGroup();
  }
  static void Room(AuditEnhancedColliders.Room room){
   float front=room.y-room.depth/2;
   foreach(float dx in new[]{-2.2f,2.2f})Paint("Aisle boundary",new Vector3(room.x+dx,.159f,room.y),new Vector2(.11f,room.depth-.6f),yellow);
   for(float z=front+3;z<room.y+room.depth/2-1;z+=4)Paint("Aisle direction dash",new Vector3(room.x,.159f,z),new Vector2(.12f,1.2f),white);
   StartGroup(room.id+" entry signage");
   Box("Entry sign backing",new Vector3(room.x,4.45f,front+.4f),new Vector3(4,.65f,.05f),blue);
   Text(room.kind=="CASTHOUSE"?"CAST HOUSE  /  INSPECTION AISLE":"MAINTENANCE  /  INSPECTION AISLE",new Vector3(room.x,4.45f,front+.36f),.15f,Color.white);FinishGroup();
   if(room.kind=="CASTHOUSE"){
    int start=stations;
    foreach(float z in new[]{front+3.1f,room.y+room.depth/2-2.5f})Station(room,room.x-8,z,false);
    if(stations==start)throw new Exception("No accessible cast-house workstation: "+room.id);
    Cabinet(room,room.x+9,front+3.3f);
    // Low guards demarcate the existing demonstration trough, keeping the aisle open.
    foreach(float z in new[]{room.y-5,room.y+5}){
     StartGroup(room.id+" trough guard");
     foreach(float dz in new[]{-1f,1f})Tube("Guard post",new Vector3(room.x+4.2f,.15f,z+dz),new Vector3(room.x+4.2f,1.25f,z+dz),.045f,yellow);
     Tube("Guard rail",new Vector3(room.x+4.2f,1.25f,z-1),new Vector3(room.x+4.2f,1.25f,z+1),.045f,yellow);FinishGroup();
    }
   }else{
    int start=stations;
    foreach(float dx in new[]{-7.5f,7.5f})foreach(float dz in new[]{-7f,7f})Station(room,room.x+dx,room.y+dz,true);
    if(stations-start<2)throw new Exception("Insufficient accessible maintenance fixtures: "+room.id);
    foreach(float dx in new[]{-11.5f,11.5f})foreach(float dz in new[]{-7f,7f})Cabinet(room,room.x+dx,room.y+dz);
   }
   foreach(float dx in new[]{-4f,4f})foreach(float dz in new[]{-5f,5f}){
    StartGroup(room.id+" suspended task light");float y=room.height-2;
    Box("Luminaire housing",new Vector3(room.x+dx,y,room.y+dz),new Vector3(1.5f,.18f,.45f),steel);
    Box("Diffuser",new Vector3(room.x+dx,y-.1f,room.y+dz),new Vector3(1.35f,.03f,.36f),white);
    bool anchored=true;bool backfaces=Physics.queriesHitBackfaces;Physics.queriesHitBackfaces=true;
    try{foreach(float ox in new[]{-.5f,.5f}){
     var from=new Vector3(room.x+dx+ox,y+.12f,room.y+dz);
     if(!Physics.Raycast(from,Vector3.up,out var ceiling,room.height,1<<8)){anchored=false;break;}
     Tube("Light hanger",from-Vector3.up*.03f,ceiling.point-Vector3.up*.005f,.018f,steel);
    }}finally{Physics.queriesHitBackfaces=backfaces;}
    if(!anchored){omitted++;notes.Add(group.name+": no ceiling anchor");UnityEngine.Object.DestroyImmediate(group.gameObject);continue;}
    if(FinishGroup()){
     var light=new GameObject("Work area fill light").AddComponent<Light>();light.transform.SetParent(group);light.transform.position=new Vector3(room.x+dx,Mathf.Min(y-.25f,6),room.y+dz);
     light.type=LightType.Point;light.color=new Color(1,.94f,.82f);light.intensity=.25f;light.range=10;light.shadows=LightShadows.None;
    }
   }
  }
  public static void Apply(){
   Directory.CreateDirectory(Folder);AssetDatabase.Refresh();fixtures=stations=spools=omitted=0;notes.Clear();
   var parent=UnityEngine.Object.FindFirstObjectByType<MAEKExteriorDetail>();
   root=new GameObject("MAEK interior work areas").transform;root.SetParent(parent.transform);
   steel=Mat("painted structural metal",new Color(.19f,.24f,.26f));paint=Mat("instrument orange",new Color(.65f,.25f,.055f));yellow=Mat("safety paint",new Color(.85f,.61f,.1f));blue=Mat("work zone blue",new Color(.13f,.26f,.28f));silver=Mat("galvanized metal",new Color(.56f,.6f,.59f));black=Mat("rubber and gaskets",new Color(.035f,.045f,.048f));screen=Mat("instrument screen",new Color(.035f,.22f,.18f),true);white=Mat("fixture white",new Color(.82f,.85f,.8f),true);
   var rooms=JsonUtility.FromJson<AuditEnhancedColliders.Rooms>(File.ReadAllText("Assets/MAEK/Source/interior_rooms.json")).rooms.Where(r=>r.kind=="CASTHOUSE"||r.kind=="SERVICE_HALL").ToArray();
   string labelPath=Folder+"/printed labels.mat";labelMaterial=AssetDatabase.LoadAssetAtPath<Material>(labelPath);
   if(!labelMaterial){labelMaterial=new Material(Shader.Find("MAEK/PrintedLabel"));AssetDatabase.CreateAsset(labelMaterial,labelPath);}
   foreach(var room in rooms)foreach(var light in UnityEngine.Object.FindObjectsByType<Light>(FindObjectsSortMode.None))
    if(light.name==room.id+" interior light"){light.intensity=.45f;light.range=Mathf.Min(24,room.depth*.75f);}
   foreach(var room in rooms)Room(room);
   Physics.SyncTransforms();
   foreach(var station in root.GetComponentsInChildren<MAEKInteriorStation>())if(!AccessClear(station.aislePoint,station.approachPoint))throw new Exception("Blocked interior station "+station.name);
   var report=new Report{status="LAYOUT_CHECKED",layoutFirst=true,layoutSignature=EnhanceSteelworks.LayoutSignature(),scope="Fixed reference layout, not as-built; pedestrian and physical checks only, no flight/capture certification. Five existing rooms; unchanged 247 process IDs. Added cold mock spools are visual training fixtures, not hydraulic/MAEK-analysis circuits.",rooms=rooms.Length,stations=stations,closedSpools=spools,physicalFixtures=fixtures,omittedAssemblies=omitted,omissions=notes.ToArray()};
   string output=Path.GetFullPath("../../visualization/interior_detail");Directory.CreateDirectory(output);File.WriteAllText(Path.Combine(output,"build_report.json"),JsonUtility.ToJson(report,true));AssetDatabase.SaveAssets();Debug.Log("MAEK_INTERIOR_LAYOUT_CHECKED stations="+stations+" closedSpools="+spools+" colliders="+fixtures);
  }
 }
}
