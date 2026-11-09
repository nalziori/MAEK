using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using UnityEditor;
using UnityEngine;

namespace MAEK.Editor {
 // Reference layout first; the authoritative process graph and legacy route remain immutable.
 public static class EnhanceSteelworks {
  const string Assets="Assets/MAEK/Generated/Realism";
  const string Source="Assets/MAEK/Source/";
  static readonly string Output=Path.GetFullPath("../../visualization/realism");
  static Transform root;
  static AuditEnhancedColliders.Room[] accessRooms;
  static Material steel,clad,roof,concrete,glass,pipe;
  static int accepted,rejected,repainted,loops;
  static readonly List<string> omissions=new List<string>();
  [Serializable] class Audit {
   public string status,basis,routeSha256,layoutSignature;
   public int addedColliders,omittedParts,weatheredRenderers,auxiliaryLoops,processPipes,checkedSegments,checkedViews,blockedSegments,occludedViews;
   public bool layoutFirst=true,legacyRouteDiagnosticsOnly=true;
   public bool originalCollidersPreserved,originalMeshesPreserved,originalProcessSourcesPreserved;
   public string[] omissions;
  }
  static string Hash(string path){using(var s=SHA256.Create())return BitConverter.ToString(s.ComputeHash(File.ReadAllBytes(path))).Replace("-","").ToLowerInvariant();}
  static void Require(bool ok,string message){if(!ok)throw new Exception("REALISM: "+message);}
  public static bool Protected(Bounds b){
   if(accessRooms==null)accessRooms=JsonUtility.FromJson<AuditEnhancedColliders.Rooms>(File.ReadAllText(Source+"interior_rooms.json")).rooms;
   foreach(var room in accessRooms){
    var corridor=new Bounds(new Vector3(room.x,1.3f,room.y),new Vector3(4,2.3f,room.depth+8));
    if(corridor.Intersects(b))return true;
   }
   return false;
  }
  static Material Mat(string name,Color color,float rust,float ribs=0,float metal=.35f){
   var m=new Material(Shader.Find("MAEK/WeatheredSteel")){name=name};m.color=color;
   m.SetFloat("_Rust",rust);m.SetFloat("_Ribs",ribs);m.SetFloat("_Metallic",metal);m.SetFloat("_Glossiness",.2f);
   string path=Assets+"/"+name+".mat";var saved=AssetDatabase.LoadAssetAtPath<Material>(path);
   if(saved){EditorUtility.CopySerialized(m,saved);UnityEngine.Object.DestroyImmediate(m);return saved;}
   AssetDatabase.CreateAsset(m,path);return m;
  }
  static bool Accept(GameObject go){
   var r=go.GetComponent<Renderer>();var c=go.GetComponent<Collider>();Physics.SyncTransforms();
   bool blocked=Protected(r.bounds);
   // Existing process pipes cannot be penetrated by added cladding or support members.
   if(!blocked)foreach(var other in Physics.OverlapBox(r.bounds.center,r.bounds.extents,Quaternion.identity,1<<8)){
    if(other==c||!other.GetComponentInParent<MAEKPipeService>())continue;
    if(Physics.ComputePenetration(c,c.transform.position,c.transform.rotation,other,other.transform.position,other.transform.rotation,out _,out float distance)&&distance>.015f){blocked=true;break;}
   }
   if(blocked){rejected++;omissions.Add(go.name);UnityEngine.Object.DestroyImmediate(go);return false;}
   accepted++;return true;
  }
  static GameObject Part(string name,PrimitiveType type,Vector3 p,Vector3 scale,Material m,Quaternion rotation){
   var go=GameObject.CreatePrimitive(type);go.name=name;go.layer=8;go.transform.SetParent(root);go.transform.SetPositionAndRotation(p,rotation);go.transform.localScale=scale;go.GetComponent<Renderer>().sharedMaterial=m;
   return go;
  }
  static void Box(string n,Vector3 p,Vector3 size,Material m){Accept(Part(n,PrimitiveType.Cube,p,size,m,Quaternion.identity));}
  static void Beam(string n,Vector3 a,Vector3 b,float width,Material m){Accept(Part(n,PrimitiveType.Cube,(a+b)/2,new Vector3(width,(b-a).magnitude,width),m,Quaternion.FromToRotation(Vector3.up,b-a)));}
  static void Pipe(string n,Vector3 a,Vector3 b,float radius,Material m){Accept(Part(n,PrimitiveType.Cylinder,(a+b)/2,new Vector3(radius*2,(b-a).magnitude/2,radius*2),m,Quaternion.FromToRotation(Vector3.up,b-a)));}
  static void Tower(float x,int index){
   // Heavy external columns, framed corrugated bays, open service floors, and crown.
   foreach(float dx in new[]{-9.4f,9.4f})foreach(float dz in new[]{-9.4f,9.4f}){
    Box("BF"+index+" foundation",new Vector3(x+dx,1,18+dz),new Vector3(2.4f,2,2.4f),concrete);
    for(int y=2;y<50;y+=6)Box("BF"+index+" external column",new Vector3(x+dx,y+3,18+dz),new Vector3(.65f,6,.65f),steel);
    Box("BF"+index+" column cap",new Vector3(x+dx,52,18+dz),new Vector3(.65f,4,.65f),steel);
   }
   for(int level=0;level<7;level++){
    float y=14+level*6;
    for(int side=0;side<4;side++){
     bool along=side<2;float fixedAxis=(side%2==0?-9.4f:9.4f);
     Vector3 A(float v,float h)=>along?new Vector3(x+v,h,18+fixedAxis):new Vector3(x+fixedAxis,h,18+v);
     Beam("BF"+index+" floor girder",A(-9.4f,y),A(9.4f,y),.58f,steel);
     if(level<6){
      for(int bay=0;bay<3;bay++){
       float u=-6.1f+bay*6.1f;
       // Broken facade rhythm leaves real open machinery bays; no billboard surfaces.
       if((level+side+bay)%4!=0)Box("BF"+index+" corrugated bay",A(u,y+2.8f),along?new Vector3(5.5f,4.35f,.16f):new Vector3(.16f,4.35f,5.5f),clad);
       Beam("BF"+index+" bay mullion",A(u-2.85f,y+.3f),A(u-2.85f,y+5.6f),.17f,steel);
      }
      Beam("BF"+index+" diagonal brace",A(-9.1f,y+.4f),A(9.1f,y+5.6f),.28f,steel);
     }
     // Walkways are narrow perimeter strips; process-pipe and pedestrian exclusions apply.
     Box("BF"+index+" service floor",A(0,y-.25f),along?new Vector3(20,.22f,1.3f):new Vector3(1.3f,.22f,20),steel);
     Beam("BF"+index+" guardrail",A(-9.4f,y+1.05f),A(9.4f,y+1.05f),.065f,steel);
     for(int k=-9;k<=9;k+=3)Beam("BF"+index+" railing upright",A(k,y),A(k,y+1.05f),.055f,steel);
    }
   }
   bool complete=false;
   foreach(float centerZ in new[]{18f,24f,12f})if(Crown(x,index,centerZ)){complete=true;break;}
   Require(complete,"No complete supported crown fits physical/access exclusions for BF"+index);
  }
  static bool Crown(float x,int index,float centerZ){
   int before=accepted,omitted=rejected;var parent=root;
   var assembly=new GameObject("BF"+index+" complete crown assembly");assembly.transform.SetParent(parent);root=assembly.transform;
   // All four feet stand on transverse girders tied into the perimeter frame.
   foreach(float dx in new[]{-9.4f,9.4f})Beam("Crown perimeter support",new Vector3(x+dx,54,8.6f),new Vector3(x+dx,54,27.4f),.6f,steel);
   foreach(float z in new[]{centerZ-2.5f,centerZ+2.5f}){
    Beam("Crown transverse foundation girder",new Vector3(x-9.4f,54,z),new Vector3(x+9.4f,54,z),.6f,steel);
    for(int side=-1;side<=1;side+=2){
     Beam("BF"+index+" crown mast",new Vector3(x+side*3,54,z),new Vector3(x+side*3,64,z),.48f,steel);
     for(int y=54;y<62;y+=4)Beam("BF"+index+" crown brace",new Vector3(x+side*3,y,z),new Vector3(x-side*3,y+4,z),.2f,steel);
    }
    Beam("BF"+index+" crown beam",new Vector3(x-3.5f,64,z),new Vector3(x+3.5f,64,z),.5f,steel);
   }
   foreach(float dx in new[]{-3f,3f})foreach(float y in new[]{54f,58f,62f,64f})Beam("Crown side tie",new Vector3(x+dx,y,centerZ-2.5f),new Vector3(x+dx,y,centerZ+2.5f),.25f,steel);
   Box("BF"+index+" crown machinery deck",new Vector3(x,58,centerZ),new Vector3(6.7f,.35f,5.8f),steel);
   Box("BF"+index+" crown winch housing",new Vector3(x,59,centerZ),new Vector3(2.5f,1.5f,2.2f),clad);
   root=parent;
   if(rejected!=omitted){rejected+=accepted-before;accepted=before;omissions.Add(assembly.name+" rejected as a complete assembly at z="+centerZ);UnityEngine.Object.DestroyImmediate(assembly);return false;}
   Require(assembly.GetComponentsInChildren<Collider>().Length==28,"Incomplete crown assembly");return true;
  }
  static void Building(string n,Vector3 center,Vector3 size,bool createShell){
   float x=center.x,z=center.z,baseY=center.y-size.y/2,top=center.y+size.y/2;
   if(createShell)Box(n+" shell",center,size,clad);
   for(int side=-1;side<=1;side+=2){
    float front=z+side*(size.z/2+.15f);
    for(float dx=-size.x/2+2;dx<size.x/2;dx+=4){
     Box(n+" facade pier",new Vector3(x+dx,(baseY+top)/2,front),new Vector3(.19f,size.y,.2f),steel);
     Box(n+" clerestory",new Vector3(x+dx,top-2.3f,front+.12f*side),new Vector3(3.4f,1.15f,.08f),glass);
     Box(n+" window sill",new Vector3(x+dx,top-2.95f,front+.2f*side),new Vector3(3.6f,.12f,.35f),steel);
    }
    Box(n+" eave",new Vector3(x,top,front),new Vector3(size.x+.8f,.35f,.6f),steel);
   }
   if(createShell)Box(n+" metal roof",new Vector3(x,top+.2f,z),new Vector3(size.x+1.2f,.3f,size.z+1.2f),roof);
   for(float dx=-size.x/2+4;dx<size.x/2;dx+=10){
    Box(n+" roof exhaust curb",new Vector3(x+dx,top+1.1f,z),new Vector3(2.5f,1.8f,3.2f),clad);
    Box(n+" roof exhaust cap",new Vector3(x+dx,top+2.1f,z),new Vector3(3,.2f,3.8f),steel);
   }
  }
  static void AuxiliaryLoop(string name,float xmin,float xmax,float z,float y,float radius){
   // A complete rounded, closed return loop with equipment at the two ends.
   // Commit all pieces together: a rejected elbow must never leave an open pipe.
   var group=new GameObject(name);group.transform.SetParent(root);var saved=root;root=group.transform;
   var corners=new[]{new Vector3(xmin,y,z),new Vector3(xmax,y,z),new Vector3(xmax,y,z+2),new Vector3(xmin,y,z+2)};
   var vertices=new List<Vector3>();float bend=.7f;
   for(int i=0;i<4;i++){
    var c=corners[i];var prev=corners[(i+3)%4];var next=corners[(i+1)%4];
    var a=c+(prev-c).normalized*bend;var b=c+(next-c).normalized*bend;
    for(int j=0;j<=6;j++){float t=j/6f;vertices.Add((1-t)*(1-t)*a+2*(1-t)*t*c+t*t*b);}
   }
   var objects=new List<GameObject>();
   for(int i=0;i<vertices.Count;i++){
    var a=vertices[i];var b=vertices[(i+1)%vertices.Count];
    objects.Add(Part("Auxiliary closed-loop tube",PrimitiveType.Cylinder,(a+b)/2,new Vector3(radius*2,(b-a).magnitude/2+.025f,radius*2),pipe,Quaternion.FromToRotation(Vector3.up,b-a)));
   }
   // Coupled skids touch each loop at its return bends, with columns carrying the racks.
   foreach(float x in new[]{xmin,xmax})objects.Add(Part("Auxiliary exchanger",PrimitiveType.Cube,new Vector3(x,y,z+1),new Vector3(.9f,.9f,1.25f),steel,Quaternion.identity));
   bool safe=objects.All(g=>!Protected(g.GetComponent<Renderer>().bounds));
   Physics.SyncTransforms();
   if(safe)foreach(var g in objects){var c=g.GetComponent<Collider>();var b=g.GetComponent<Renderer>().bounds;
    foreach(var o in Physics.OverlapBox(b.center,b.extents,Quaternion.identity,1<<8))if(o.GetComponentInParent<MAEKPipeService>()&&Physics.ComputePenetration(c,c.transform.position,c.transform.rotation,o,o.transform.position,o.transform.rotation,out _,out float depth)&&depth>.015f){safe=false;break;}
    if(!safe)break;
   }
   root=saved;
   if(!safe){rejected+=objects.Count;omissions.Add(name+" (whole connected assembly)");UnityEngine.Object.DestroyImmediate(group);return;}
   accepted+=objects.Count;loops++;
  }
  // The callback must reload the same undecorated base and apply exterior/interior layout.
  // Only an explicit parent test invokes rebuilds; ordinary Apply never changes the route.
  public static bool VerifyLayoutIndependence(Action<TourPlan> rebuildFromSameBase){
   if(rebuildFromSameBase==null)throw new ArgumentNullException(nameof(rebuildFromSameBase));
   var first=new TourPlan{radius=.01f,points=new[]{
    new TourPoint{position=new Vector3(-86,10,-25),target=new Vector3(-72,6.5f,-12)},
    new TourPoint{position=new Vector3(-72,6.5f,-12),target=Vector3.zero,pipeId="layout-probe",sampleId="near"}}};
   var second=new TourPlan{radius=8f,points=new[]{
    new TourPoint{position=new Vector3(900,500,900),target=Vector3.zero},
    new TourPoint{position=new Vector3(-900,500,-900),target=new Vector3(62,58,18),pipeId="layout-probe",sampleId="far"}}};
   rebuildFromSameBase(first);string before=LayoutSignature();
   rebuildFromSameBase(second);string after=LayoutSignature();
   Require(before==after,"Layout geometry depends on route/camera input: "+before+" != "+after);
   return true;
  }
  // Parent test hook: rebuild the same base scene with different fake Apply plans and compare.
  public static string LayoutSignature(){
   var layout=UnityEngine.Object.FindFirstObjectByType<MAEKExteriorDetail>();
   Require(layout,"Layout signature requires exterior geometry");
   var records=new List<string>();var meshes=new Dictionary<Mesh,string>();
   foreach(var t in layout.GetComponentsInChildren<Transform>(true)){
    var filter=t.GetComponent<MeshFilter>();var collider=t.GetComponent<Collider>();
    var text=t.GetComponent<TextMesh>();
    if(!filter&&!collider&&!text)continue;
    using(var bytes=new MemoryStream())using(var writer=new BinaryWriter(bytes)){
     var names=new List<string>();for(var ancestor=t;ancestor;ancestor=ancestor.parent){names.Add(ancestor.name);if(ancestor==layout.transform)break;}
     names.Reverse();writer.Write(string.Join("/",names));writer.Write(t.gameObject.layer);
     writer.Write(t.gameObject.activeSelf);
     var matrix=t.localToWorldMatrix;for(int i=0;i<16;i++)writer.Write(matrix[i]);
     writer.Write(filter&&filter.sharedMesh);
     if(filter&&filter.sharedMesh){
      var mesh=filter.sharedMesh;
      if(!meshes.TryGetValue(mesh,out var signature)){
       using(var data=new MemoryStream())using(var geometry=new BinaryWriter(data)){
        geometry.Write(mesh.vertexCount);
        foreach(var v in mesh.vertices){geometry.Write(v.x);geometry.Write(v.y);geometry.Write(v.z);}
        geometry.Write(mesh.subMeshCount);
        for(int sub=0;sub<mesh.subMeshCount;sub++){
         geometry.Write((int)mesh.GetTopology(sub));var indices=mesh.GetIndices(sub);
         geometry.Write(indices.Length);foreach(int index in indices)geometry.Write(index);
        }
        geometry.Flush();signature=HashBytes(data.ToArray());
       }
       meshes.Add(mesh,signature);
      }
      writer.Write(signature);
     }
     writer.Write((bool)collider);
     if(collider){
      writer.Write(collider.GetType().FullName);writer.Write(collider.enabled);writer.Write(collider.isTrigger);
      var b=collider.bounds;
      foreach(float value in new[]{b.center.x,b.center.y,b.center.z,b.size.x,b.size.y,b.size.z})writer.Write(value);
     }
     writer.Write(text?text.text:"");writer.Flush();records.Add(HashBytes(bytes.ToArray()));
    }
   }
   records.Sort(StringComparer.Ordinal);
   return HashBytes(System.Text.Encoding.UTF8.GetBytes(string.Join("\n",records)));
  }
  static string HashBytes(byte[] bytes){using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();}
  public static void Apply(TourPlan frozenPlan){
   accepted=rejected=repainted=loops=0;omissions.Clear();
   accessRooms=JsonUtility.FromJson<AuditEnhancedColliders.Rooms>(File.ReadAllText(Source+"interior_rooms.json")).rooms;
   Directory.CreateDirectory(Output);Directory.CreateDirectory(Assets);AssetDatabase.Refresh();
   string baseline=Path.Combine(Output,"baseline/inspection_tour.json");
   Require(File.Exists(baseline),"Frozen baseline is required");
   string[] fixedSources={"inspection_tour.json","pipe_services.json","service_drone_routes.json","maek_manifest.json","collision_network.json"};
   foreach(var f in fixedSources)Require(Hash(Source+f)==Hash(Path.Combine(Output,"baseline",f)),"Process source changed: "+f);
   var originalColliders=UnityEngine.Object.FindObjectsByType<Collider>(FindObjectsSortMode.None);
   var originalPos=originalColliders.Select(c=>c.transform.localToWorldMatrix).ToArray();
   var originalMeshes=UnityEngine.Object.FindObjectsByType<MeshFilter>(FindObjectsSortMode.None);
   var meshes=originalMeshes.Select(m=>m.sharedMesh).ToArray();
   root=new GameObject("POSCO reference enrichment - auxiliary visual assets",typeof(MAEKExteriorDetail)).transform;
   RenderSettings.fog=true;RenderSettings.fogMode=FogMode.Exponential;
   RenderSettings.fogDensity=.0008f;RenderSettings.fogColor=new Color(.64f,.70f,.73f);
   QualitySettings.shadowDistance=280;QualitySettings.shadowCascades=4;
   steel=Mat("weathered structural steel",new Color(.19f,.23f,.24f),.48f);
   clad=Mat("ribbed galvanized cladding",new Color(.46f,.47f,.44f),.38f,1,.35f);
   roof=Mat("weathered oxide roof",new Color(.38f,.17f,.1f),.3f,1);
   concrete=Mat("dusty foundations",new Color(.36f,.35f,.32f),.07f,0,0);
   glass=Mat("dark clerestory glazing",new Color(.12f,.18f,.19f),0,0,.25f);
   pipe=Mat("aged auxiliary pipe",new Color(.44f,.45f,.42f),.3f,0,.5f);
   var replacements=new Dictionary<Material,Material>();
   foreach(var renderer in UnityEngine.Object.FindObjectsByType<Renderer>(FindObjectsSortMode.None)){
    if(renderer.transform.IsChildOf(root))continue;
    var mats=renderer.sharedMaterials;bool changed=false;
    for(int i=0;i<mats.Length;i++){
     var old=mats[i];if(!old||old.shader.name!="Standard")continue;
     string n=old.name.ToLowerInvariant();
     if(n.Contains("letter")||n.Contains("yellow")||n.Contains("orange")||n.Contains("display")||n.Contains("rubber"))continue;
     if(!replacements.TryGetValue(old,out var replacement)){
      float rust=n.Contains("corrosion")?.9f:n.Contains("casing")?.6f:n.Contains("concrete")||n.Contains("road")?.04f:.26f;
      replacement=Mat("original "+old.name.Replace("/","_"),old.color,rust,n.Contains("cladding")||n.Contains("roof")?1:0,old.GetFloat("_Metallic")*.75f);replacements.Add(old,replacement);
     }
     mats[i]=replacement;changed=true;
    }
    if(changed){renderer.sharedMaterials=mats;repainted++;}
   }
   Tower(-62,1);Tower(62,2);
   foreach(float x in new[]{-62f,62f}){
    Building("Cast house",new Vector3(x,6.5f,53),new Vector3(24.2f,13,25),false);
    Building("Stock house",new Vector3(x,7.5f,73),new Vector3(16,15,13),false);
   }
   Building("North rolling mill",new Vector3(0,14,163),new Vector3(290,28,48),true);
   Building("West utilities",new Vector3(-155,10,52),new Vector3(18,20,68),true);
   Building("East utilities",new Vector3(155,12,53),new Vector3(18,24,70),true);
   foreach(float x in new[]{-97f,0f,99f})Building("Service hall",new Vector3(x,8,112),new Vector3(x==0?80:70,16,30),false);
   // Dense auxiliary racks at two elevations. These are visual closed circuits,
   // not extra MAEK process IDs or claimed hydraulic results.
   for(int bay=0;bay<2;bay++)for(int level=0;level<3;level++)for(int lane=0;lane<3;lane++){
    AuxiliaryLoop("Rear auxiliary rack "+bay+"-"+level+"-"+lane,-142+bay*145,-8+bay*145,83+lane*3,9+level*2,.14f+lane*.045f);
    AuxiliaryLoop("Front auxiliary rack "+bay+"-"+level+"-"+lane,-132+bay*145,-20+bay*145,-32+lane*3,9+level*2,.12f+lane*.045f);
   }
   foreach(float z in new[]{-28f,87f})for(int x=-132;x<=130;x+=16){
    foreach(float dz in new[]{-5f,5f})Beam("Auxiliary rack column",new Vector3(x,0,z+dz),new Vector3(x,14,z+dz),.32f,steel);
    for(int y=8;y<=12;y+=2)Beam("Auxiliary rack crossbeam",new Vector3(x,y,z-5),new Vector3(x,y,z+5),.3f,steel);
   }
   // Furnace stove jacketing and stiffening bands remain outside the active nozzles.
   foreach(float x in new[]{-40f,-28f,-16f,84f,96f,108f})for(int y=15;y<=27;y+=4){
    for(int k=0;k<16;k++){float a=k*Mathf.PI/8,b=(k+1)*Mathf.PI/8;
     Beam("Hot-blast stove shell band",new Vector3(x+3.12f*Mathf.Cos(a),y,25+3.12f*Mathf.Sin(a)),new Vector3(x+3.12f*Mathf.Cos(b),y,25+3.12f*Mathf.Sin(b)),.12f,steel);}
   }
   Physics.SyncTransforms();
   // Route blockage is an outcome of the fixed layout, never a reason to remove an asset.
   int segments=0,views=0,blocked=0,occluded=0;
   if(frozenPlan!=null&&frozenPlan.points!=null){
    for(int i=1;i<frozenPlan.points.Length;i++){
     var a=frozenPlan.points[i-1].position;var b=frozenPlan.points[i].position;var d=b-a;
     bool clear=!Physics.CheckSphere(a,frozenPlan.radius,1<<8,QueryTriggerInteraction.Ignore)&&
      !Physics.CheckSphere(b,frozenPlan.radius,1<<8,QueryTriggerInteraction.Ignore)&&
      (d.sqrMagnitude<1e-8f||!Physics.SphereCast(a,frozenPlan.radius,d.normalized,out _,d.magnitude,1<<8,QueryTriggerInteraction.Ignore));
     segments++;if(!clear)blocked++;
    }
    foreach(var p in frozenPlan.points.Where(p=>!string.IsNullOrEmpty(p.pipeId))){
     var d=p.target-p.position;
     bool visible=d.sqrMagnitude>1e-8f&&Physics.Raycast(p.position,d.normalized,out var hit,d.magnitude+2,1<<8,QueryTriggerInteraction.Ignore)&&hit.collider.GetComponentInParent<MAEKPipeService>()?.lineId==p.pipeId;
     views++;if(!visible)occluded++;
    }
   }
   bool colliders=originalColliders.Select((c,i)=>c&&c.enabled&&c.transform.localToWorldMatrix==originalPos[i]).All(v=>v);
   bool sameMeshes=originalMeshes.Select((m,i)=>m&&m.sharedMesh==meshes[i]).All(v=>v);
   Require(colliders&&sameMeshes,"Existing geometry changed");
   Require(UnityEngine.Object.FindObjectsByType<MAEKPipeService>(FindObjectsSortMode.None).Length==247,"Process catalogue changed");
   foreach(var f in fixedSources)Require(Hash(Source+f)==Hash(Path.Combine(Output,"baseline",f)),"Process source changed during layout: "+f);
   var audit=new Audit{status="LAYOUT_CHECKED",layoutFirst=true,layoutSignature=LayoutSignature(),basis="User POSCO photographs: fixed architectural reference, fictional layout, not as-built; legacy-route checks are diagnostics only, not flight certification; auxiliary loops are not simulated process circuits",routeSha256=Hash(baseline),addedColliders=accepted,omittedParts=rejected,weatheredRenderers=repainted,auxiliaryLoops=loops,processPipes=247,checkedSegments=segments,checkedViews=views,blockedSegments=blocked,occludedViews=occluded,originalCollidersPreserved=colliders,originalMeshesPreserved=sameMeshes,originalProcessSourcesPreserved=true,omissions=omissions.ToArray()};
   File.WriteAllText(Path.Combine(Output,"geometry_audit.json"),JsonUtility.ToJson(audit,true));
   AssetDatabase.SaveAssets();Debug.Log("MAEK_LAYOUT_CHECKED colliders="+accepted+" auxiliaryLoops="+loops+" omitted="+rejected+" legacyBlocked="+blocked+" legacyOccluded="+occluded);
  }
 }
}
