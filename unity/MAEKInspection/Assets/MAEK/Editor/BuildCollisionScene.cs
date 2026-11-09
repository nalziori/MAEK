using System;
using System.IO;
using System.Text;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEditor;
using UnityEditor.SceneManagement;
using MAEK;
namespace MAEK.Editor {
 [Serializable] public class MaterialData {public string name;public float[] color;public float metallic,smoothness;}
 [Serializable] public class AssetData {public string id,collider;public float[] position,size;public int vertices,triangles;public string[] objects;}
 [Serializable] public class Manifest {public string format,units;public MaterialData[] materials;public AssetData[] assets;public int pipe_count;}
 [Serializable] public class InteriorRoom {public string id,kind;public float x,y,width,depth,height;}
 [Serializable] public class InteriorRooms {public InteriorRoom[] rooms;}
 [Serializable] public class Check {public string name,detail;public bool pass;}
 [Serializable] public class Report {public string status,unityVersion;public int assets,colliders,meshColliders,boxColliders,pipeAssets;public List<Check> checks=new List<Check>();}
 public static class BuildCollisionScene {
  const string Base="Assets/MAEK";
  static Vector3 V(float[] f)=>new Vector3(f[0],f[1],f[2]);
  static string Safe(string s)=>string.Concat(s.Select(c=>char.IsLetterOrDigit(c)||c=='-'||c=='_'||c=='.'?c:'_'));
  static void EnsureFolder(string path){if(AssetDatabase.IsValidFolder(path))return;var p=Path.GetDirectoryName(path).Replace('\\','/');EnsureFolder(p);AssetDatabase.CreateFolder(p,Path.GetFileName(path));}
  static int Layer(string name,int slot){
   var manager=new SerializedObject(AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/TagManager.asset")[0]);
   var array=manager.FindProperty("layers");
   for(int i=8;i<32;i++)if(array.GetArrayElementAtIndex(i).stringValue==name)return i;
   if(!string.IsNullOrEmpty(array.GetArrayElementAtIndex(slot).stringValue))throw new Exception("Layer slot occupied: "+slot);
   array.GetArrayElementAtIndex(slot).stringValue=name;manager.ApplyModifiedProperties();return slot;
  }
  [MenuItem("MAEK/Build and verify collision environment")]
  public static void Run(){
   try{Build();}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}
  }
  public static void Build(){
   string project=Directory.GetParent(Application.dataPath).FullName;
   string reportDir=Path.GetFullPath(Path.Combine(project,"../../visualization"));
   Directory.CreateDirectory(reportDir);
   var manifest=JsonUtility.FromJson<Manifest>(File.ReadAllText(Base+"/Source/maek_manifest.json"));
   if(manifest.units!="metres"||manifest.format!="MAEKCOL1")throw new Exception("Unexpected source format");
   EnsureFolder(Base+"/Generated/Meshes");EnsureFolder(Base+"/Generated/Materials");EnsureFolder(Base+"/Scenes");
   var scene=EditorSceneManager.NewScene(NewSceneSetup.EmptyScene,NewSceneMode.Single);
   int env=Layer("MAEKEnvironment",8),playerLayer=Layer("MAEKPlayer",9),equipmentLayer=Layer("MAEKEquipment",10);
   Physics.IgnoreLayerCollision(env,playerLayer,false);Physics.IgnoreLayerCollision(env,equipmentLayer,false);Physics.IgnoreLayerCollision(playerLayer,equipmentLayer,false);
   var materials=new Material[manifest.materials.Length];
   for(int i=0;i<materials.Length;i++){
    var d=manifest.materials[i];var shader=Shader.Find("Standard");if(shader==null)throw new Exception("Standard shader is unavailable");
    string path=Base+"/Generated/Materials/M"+i+"_"+Safe(d.name)+".mat";
    var mat=AssetDatabase.LoadAssetAtPath<Material>(path);
    if(mat==null){mat=new Material(shader);AssetDatabase.CreateAsset(mat,path);}
    mat.color=new Color(d.color[0],d.color[1],d.color[2],d.color[3]);mat.SetFloat("_Metallic",d.metallic);mat.SetFloat("_Glossiness",d.smoothness);materials[i]=mat;
   }
   var root=new GameObject("MAEK Environment — static colliders");var assetObjects=new Dictionary<string,GameObject>();
   AssetDatabase.StartAssetEditing();
   try {
   using(var reader=new BinaryReader(File.OpenRead(Base+"/Source/maek_geometry.bytes"),Encoding.UTF8)){
    if(Encoding.ASCII.GetString(reader.ReadBytes(8))!="MAEKCOL1")throw new Exception("Invalid mesh binary");
    int count=reader.ReadInt32();if(count!=manifest.assets.Length)throw new Exception("Manifest/binary asset count differs");
    for(int ai=0;ai<count;ai++){
     string id=Encoding.UTF8.GetString(reader.ReadBytes(reader.ReadInt32()));
     var d=manifest.assets[ai];if(id!=d.id)throw new Exception("Asset order mismatch");
     int vc=reader.ReadInt32(),sc=reader.ReadInt32();var vs=new Vector3[vc];var ns=new Vector3[vc];
     for(int j=0;j<vc;j++){vs[j]=new Vector3(reader.ReadSingle(),reader.ReadSingle(),reader.ReadSingle());ns[j]=new Vector3(reader.ReadSingle(),reader.ReadSingle(),reader.ReadSingle());}
     var mesh=new Mesh{name=id,indexFormat=IndexFormat.UInt32};mesh.vertices=vs;mesh.normals=ns;mesh.subMeshCount=sc;var sm=new Material[sc];
     for(int s=0;s<sc;s++){int mi=reader.ReadInt32(),ic=reader.ReadInt32();var indices=new int[ic];for(int j=0;j<ic;j++)indices[j]=reader.ReadInt32();mesh.SetTriangles(indices,s,false);sm[s]=materials[mi];}
     mesh.RecalculateBounds();
     string meshPath=Base+"/Generated/Meshes/"+Safe(id)+".asset";
     var existing=AssetDatabase.LoadAssetAtPath<Mesh>(meshPath);
     if(existing!=null){EditorUtility.CopySerialized(mesh,existing);UnityEngine.Object.DestroyImmediate(mesh);mesh=existing;}else AssetDatabase.CreateAsset(mesh,meshPath);
     var go=new GameObject(id);go.transform.SetParent(root.transform,false);go.transform.position=V(d.position);
     go.AddComponent<MeshFilter>().sharedMesh=mesh;go.AddComponent<MeshRenderer>().sharedMaterials=sm;
     var info=go.AddComponent<MAEKAssetInfo>();info.assetId=id;info.sourceObjects=d.objects;info.colliderPolicy=d.collider;
     if(d.collider=="box"){var c=go.AddComponent<BoxCollider>();c.center=Vector3.zero;c.size=V(d.size);c.isTrigger=false;}
     else if(d.collider=="mesh"){var c=go.AddComponent<MeshCollider>();c.sharedMesh=mesh;c.convex=false;c.isTrigger=false;c.cookingOptions=MeshColliderCookingOptions.CookForFasterSimulation|MeshColliderCookingOptions.EnableMeshCleaning|MeshColliderCookingOptions.WeldColocatedVertices|MeshColliderCookingOptions.UseFastMidphase;}
     go.layer=env;go.isStatic=true;assetObjects.Add(id,go);
    }
    if(reader.BaseStream.Position!=reader.BaseStream.Length)throw new Exception("Unread binary payload");
   }
   } finally { AssetDatabase.StopAssetEditing(); }
   var indoor=JsonUtility.FromJson<InteriorRooms>(File.ReadAllText(Base+"/Source/interior_rooms.json"));
   foreach(var room in indoor.rooms)foreach(float offset in new[]{-.3f,0f,.3f}) {var lamp=new GameObject(room.id+" interior light").AddComponent<Light>();lamp.type=LightType.Point;lamp.intensity=3;lamp.range=Mathf.Max(room.width,room.height)*1.25f;lamp.color=new Color(1,.94f,.84f);lamp.transform.position=new Vector3(room.x,room.height-1.3f,room.y+room.depth*offset);}
   var sun=new GameObject("Daylight").AddComponent<Light>();sun.type=LightType.Directional;sun.intensity=1.5f;sun.shadows=LightShadows.Soft;sun.transform.rotation=Quaternion.Euler(38,-30,0);
   RenderSettings.ambientMode=AmbientMode.Flat;RenderSettings.ambientLight=new Color(.6f,.65f,.7f);RenderSettings.fog=false;
   QualitySettings.shadowDistance=130;
   var person=new GameObject("MAEK Inspector");person.layer=playerLayer;person.transform.position=new Vector3(-62,.08f,36);
   var cc=person.AddComponent<CharacterController>();cc.height=1.8f;cc.radius=.3f;cc.center=new Vector3(0,.9f,0);cc.stepOffset=.28f;cc.slopeLimit=45;cc.skinWidth=.03f;cc.minMoveDistance=0;
   var cam=new GameObject("Inspector Camera").AddComponent<Camera>();cam.tag="MainCamera";cam.transform.SetParent(person.transform,false);cam.transform.localPosition=new Vector3(0,1.65f,0);cam.nearClipPlane=.05f;cam.farClipPlane=1200;cam.backgroundColor=new Color(.58f,.68f,.75f);cam.clearFlags=CameraClearFlags.SolidColor;cam.gameObject.AddComponent<AudioListener>();
   var walk=person.AddComponent<MAEKWalkthrough>();walk.viewCamera=cam;
   var overview=new GameObject("Overview Camera").AddComponent<Camera>();overview.transform.position=new Vector3(160,135,-245);overview.transform.LookAt(new Vector3(0,18,22));overview.enabled=false;overview.farClipPlane=1500;
   Physics.SyncTransforms();
   var report=new Report{unityVersion=Application.unityVersion,assets=manifest.assets.Length,pipeAssets=manifest.pipe_count};
   var colliders=root.GetComponentsInChildren<Collider>();report.colliders=colliders.Length;report.meshColliders=colliders.OfType<MeshCollider>().Count();report.boxColliders=colliders.OfType<BoxCollider>().Count();
   void Check(string name,bool pass,string detail){report.checks.Add(new Check{name=name,pass=pass,detail=detail});}
   Check("asset collider coverage",colliders.Length==manifest.assets.Count(a=>a.collider!="none"),report.colliders+" blocking assets");
   Check("static collider policy",!root.GetComponentsInChildren<Rigidbody>().Any()&&colliders.All(c=>!c.isTrigger)&&colliders.OfType<MeshCollider>().All(c=>!c.convex),"Static concave geometry; no dynamic nonconvex rigidbodies or invisible envelope boxes");
   int mask=1<<env;RaycastHit hit;
   Check("metre scale",Mathf.Abs(assetObjects["Process yard"].GetComponent<BoxCollider>().size.x-330)<.01f,"Ground width must be 330 metres");
   bool ground=Physics.Raycast(new Vector3(-80,4,-35),Vector3.down,out hit,10,mask,QueryTriggerInteraction.Ignore);
   Check("ground raycast",ground&&Mathf.Abs(hit.point.y+.05f)<.02f,ground?hit.collider.name+" y="+hit.point.y:"miss");
   bool pipe=Physics.SphereCast(new Vector3(-62,8,-9),.18f,Vector3.forward,out hit,6,mask,QueryTriggerInteraction.Ignore);
   Check("pipe blocks moving equipment",pipe&&hit.collider.name=="BF1-G100",pipe?hit.collider.name:"miss");
   bool clear=true;
   for(float z=-10;z<=-2;z+=.5f)if(Physics.CheckCapsule(new Vector3(-62,.4f,z),new Vector3(-62,1.5f,z),.3f,mask,QueryTriggerInteraction.Ignore))clear=false;
   Check("walkway under overhead pipe remains open",clear,"1.8 metre inspector capsule along ground passage");
   Check("tower opening remains open",!Physics.CheckSphere(new Vector3(-55.4f,32,18),.25f,mask,QueryTriggerInteraction.Ignore),"No convex hull filling the furnace tower opening");
   foreach(var room in indoor.rooms){
    bool open=true;
    for(float zz=room.y-room.depth/2-1;zz<room.y+room.depth/2-.8f;zz+=.4f)
     if(Physics.CheckCapsule(new Vector3(room.x,.5f,zz),new Vector3(room.x,1.7f,zz),.3f,mask,QueryTriggerInteraction.Ignore))open=false;
    Check("walkable interior "+room.id,open,"Door and central aisle capsule clearance");
   }
   var saved=person.transform.position;
   cc.enabled=false;person.transform.position=new Vector3(-62,.2f,39);cc.enabled=true;Physics.SyncTransforms();
   for(int i=0;i<160;i++){cc.Move(new Vector3(0,-.06f,.075f));Physics.SyncTransforms();}
   Check("character enters cast house",person.transform.position.z>50&&person.transform.position.y<.3f,"Entry end "+person.transform.position.ToString("F3"));
   cc.enabled=false;person.transform.position=saved;cc.enabled=true;
   
   cc.enabled=false;person.transform.position=new Vector3(-75.75f,.1f,-28.5f);cc.enabled=true;Physics.SyncTransforms();
   for(int i=0;i<180;i++){cc.Move(new Vector3(0,-.06f,.075f));Physics.SyncTransforms();}
   var end=person.transform.position;
   Check("inspector can climb stairs to inspection platform",end.y>4.4f&&end.z> -16.65f,"Controller end position "+end.ToString("F3"));
   cc.enabled=false;person.transform.position=saved;cc.enabled=true;
   var ball=new GameObject("MAEK Portable UT");ball.layer=equipmentLayer;ball.transform.position=new Vector3(-80,3,-35);
   var caseVisual=GameObject.CreatePrimitive(PrimitiveType.Cube);caseVisual.name="UT casing";caseVisual.transform.SetParent(ball.transform,false);caseVisual.transform.localScale=new Vector3(.55f,.3f,.35f);UnityEngine.Object.DestroyImmediate(caseVisual.GetComponent<BoxCollider>());caseVisual.layer=equipmentLayer;
   int orangeIndex=Array.FindIndex(manifest.materials,m=>m.name.Contains("inspection orange"));if(orangeIndex>=0)caseVisual.GetComponent<MeshRenderer>().sharedMaterial=materials[orangeIndex];
   var deviceCollider=ball.AddComponent<BoxCollider>();deviceCollider.size=new Vector3(.55f,.3f,.35f);
   var rb=ball.AddComponent<Rigidbody>();rb.mass=1.5f;rb.collisionDetectionMode=CollisionDetectionMode.ContinuousDynamic;rb.interpolation=RigidbodyInterpolation.Interpolate;
   ball.AddComponent<MAEKAssetInfo>().assetId="MAEK.PortableUT";
   var devicePosition=ball.transform.position;ball.transform.position=Vector3.zero;
   PrefabUtility.SaveAsPrefabAsset(ball,Base+"/Generated/MAEKPortableUT.prefab");ball.transform.position=devicePosition;
   Check("movable inspection device uses CCD and box collider",!deviceCollider.isTrigger&&!rb.isKinematic&&rb.collisionDetectionMode==CollisionDetectionMode.ContinuousDynamic,"MAEKPortableUT.prefab");

   var oldMode=Physics.simulationMode;
   try{Physics.simulationMode=SimulationMode.Script;Physics.SyncTransforms();for(int i=0;i<180;i++)Physics.Simulate(1f/60);
    Check("dynamic equipment rests on ground",ball.transform.position.y>.03f&&ball.transform.position.y<.25f,"UT case centre y="+ball.transform.position.y.ToString("F4"));
   }finally{Physics.simulationMode=oldMode;UnityEngine.Object.DestroyImmediate(ball);}
   report.status=report.checks.All(c=>c.pass)?"PASS":"FAIL";
   File.WriteAllText(Path.Combine(reportDir,"unity_interior_report.json"),JsonUtility.ToJson(report,true));
   Physics.SyncTransforms();
   PrefabUtility.SaveAsPrefabAsset(root,Base+"/Generated/MAEKInteriorEnvironment.prefab");
   EditorSceneManager.SaveScene(scene,Base+"/Scenes/MAEKInterior.unity");
   EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene(Base+"/Scenes/MAEKInterior.unity",true)};
   AssetDatabase.SaveAssets();
   if(report.status!="PASS")throw new Exception("Collision checks failed. Read unity_interior_report.json");
   AssetDatabase.ExportPackage(Base,Path.Combine(reportDir,"MAEK_Interior_Ready.unitypackage"),ExportPackageOptions.Recurse);
   Debug.Log("MAEK_COLLIDERS_VERIFIED "+JsonUtility.ToJson(report));
   if(Application.isBatchMode)EditorApplication.Exit(0);
  }
 }
}


