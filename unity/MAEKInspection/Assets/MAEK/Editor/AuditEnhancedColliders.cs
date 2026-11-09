using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace MAEK.Editor {
 public static class AuditEnhancedColliders {
  [Serializable] public class Room {public string id,kind;public float x,y,width,depth,height;}
  [Serializable] public class Rooms {public Room[] rooms;}
  [Serializable] class Check {public string name,detail;public bool pass;}
  [Serializable] class Report {public string status,utc,scope;public int segments,views,detailColliders,pipeCount;public Check[] checks;}
  static readonly List<Check> checks=new List<Check>();
  static void CheckThat(string n,bool p,string d=""){checks.Add(new Check{name=n,pass=p,detail=d});}
  public static void Run(){try{Audit("manual-recheck");if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  public static void Rebuild(){try{BuildInspectionTour.Build();Audit("manual-recheck");if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  public static void Audit(string stage){
   checks.Clear();EditorSceneManager.OpenScene("Assets/MAEK/Scenes/MAEKInspectionDemo.unity");Physics.SyncTransforms();
   var plan=JsonUtility.FromJson<TourPlan>(File.ReadAllText("Assets/MAEK/Source/inspection_tour.json"));
   for(int i=1;i<plan.points.Length;i++){
    var a=plan.points[i-1].position;var b=plan.points[i].position;var d=b-a;
    CheckThat("flight "+i,!Physics.CheckSphere(a,plan.radius,1<<8)&&!Physics.CheckSphere(b,plan.radius,1<<8)&&
     (d.sqrMagnitude<1e-8f||!Physics.SphereCast(a,plan.radius,d.normalized,out _,d.magnitude,1<<8)));
   }
   int views=0;foreach(var p in plan.points.Where(p=>!string.IsNullOrEmpty(p.pipeId))){var d=p.target-p.position;
    bool hit=Physics.Raycast(p.position,d.normalized,out var h,d.magnitude+2,1<<8);
    var context=new InspectionCapture{position=p.position,rotation=Quaternion.LookRotation(d),fieldOfView=52,aspect=16f/9};
    int visible=0;for(int x=-2;x<=2;x++)for(int y=-2;y<=2;y++)
     if(Physics.Raycast(context.Ray(.5f+x*.012f,.5f+y*.012f),out var sample,250,1<<8,QueryTriggerInteraction.Ignore)&&sample.collider.GetComponentInParent<MAEKPipeService>()?.lineId==p.pipeId)visible++;
    CheckThat("capture "+p.sampleId,visible>0,"visible rays="+visible+"; centre first="+(hit?h.collider.name:"no hit"));views++;
   }
   var exterior=UnityEngine.Object.FindFirstObjectByType<MAEKExteriorDetail>();CheckThat("exterior exists",exterior);
   int colliderCount=0;
   if(exterior){
    foreach(var r in exterior.GetComponentsInChildren<Renderer>()){
     if(r.GetComponent<MAEKSurfaceMarking>()){
      var size=r.bounds.size;CheckThat("paint/printed face "+r.name,!r.GetComponent<Collider>()&&Mathf.Min(size.x,Mathf.Min(size.y,size.z))<.025f);continue;
     }
     CheckThat("physical detail "+r.name,r.GetComponent<Collider>()&&r.GetComponent<Collider>().enabled&&r.gameObject.layer==8);
    }
    foreach(var c in exterior.GetComponentsInChildren<Collider>()){
     colliderCount++;var overlaps=new List<string>();
     foreach(var o in Physics.OverlapBox(c.bounds.center,c.bounds.extents,Quaternion.identity,1<<8)){
      var pipe=o.GetComponentInParent<MAEKPipeService>();if(!pipe)continue;
      if(Physics.ComputePenetration(c,c.transform.position,c.transform.rotation,o,o.transform.position,o.transform.rotation,out _,out float depth)&&depth>.015f)overlaps.Add(pipe.lineId+" depth="+depth);
     }
     CheckThat("detail/process clearance "+c.name,overlaps.Count==0,string.Join(";",overlaps));
    }
   }
   var rooms=JsonUtility.FromJson<Rooms>(File.ReadAllText("Assets/MAEK/Source/interior_rooms.json"));
   foreach(var room in rooms.rooms)foreach(float offset in new[]{-1.2f,0f,1.2f}){
    int blocked=0;string first="";
    for(float z=room.y-room.depth/2-3;z<=room.y+room.depth/2-1;z+=.25f){
     var a=new Vector3(room.x+offset,.55f,z);var b=new Vector3(room.x+offset,1.65f,z);
     var hit=Physics.OverlapCapsule(a,b,.3f,1<<8);if(hit.Length>0){blocked++;if(first=="")first=hit[0].name+" at "+a;}
    }
    CheckThat("interior access "+room.id+" offset="+offset,blocked==0,first);
    CheckThat("continuous interior access "+room.id+" offset="+offset,EnhanceInteriors.AccessClear(new Vector3(room.x+offset,0,room.y-room.depth/2-3),new Vector3(room.x+offset,0,room.y+room.depth/2-1)));
   }
   var interior=GameObject.Find("MAEK interior work areas");
   if(interior){
    foreach(var c in interior.GetComponentsInChildren<Collider>()){
     string overlap="";
     foreach(var other in Physics.OverlapBox(c.bounds.center,c.bounds.extents,Quaternion.identity,1<<8)){
      if(other.transform.IsChildOf(c.transform.parent))continue;
      if(Physics.ComputePenetration(c,c.transform.position,c.transform.rotation,other,other.transform.position,other.transform.rotation,out _,out float depth)&&depth>.015f){overlap=other.name+" depth="+depth;break;}
     }
     CheckThat("interior assembly clearance "+c.name,overlap=="",overlap);
    }
    foreach(var station in interior.GetComponentsInChildren<MAEKInteriorStation>()){
     CheckThat("workstation access "+station.name,EnhanceInteriors.AccessClear(station.aislePoint,station.approachPoint));
     if(station.closedSpoolSegments==0)continue;
     var tubes=station.GetComponentsInChildren<Collider>().Where(c=>c.name.StartsWith("Closed spool tube ")).OrderBy(c=>int.Parse(c.name.Split(' ').Last())).ToArray();
     CheckThat("closed spool parts "+station.name,tubes.Length==24&&tubes.Length==station.closedSpoolSegments);
     for(int j=0;j<tubes.Length;j++)CheckThat("closed spool joint "+station.name+" / "+j,Vector3.Distance(tubes[j].transform.TransformPoint(Vector3.up),tubes[(j+1)%tubes.Length].transform.TransformPoint(Vector3.down))<.0005f);
    }
   }
   int pipes=UnityEngine.Object.FindObjectsByType<MAEKPipeService>(FindObjectsSortMode.None).Length;CheckThat("247 process pipes",pipes==247);
   var report=new Report{status=checks.All(c=>c.pass)?"PASS":"FAIL",utc=DateTime.UtcNow.ToString("O"),scope="Saved scene: 0.12m drone sweep, capture sightlines, detail colliders vs original process pipes; 0.3m-radius 1.7m-high interior access capsule. Intended structural joints excluded.",segments=plan.points.Length-1,views=views,detailColliders=colliderCount,pipeCount=pipes,checks=checks.ToArray()};
   string folder=Path.GetFullPath("../../visualization/interior_detail");Directory.CreateDirectory(folder);
   File.WriteAllText(Path.Combine(folder,stage+"-colliders.json"),JsonUtility.ToJson(report,true));
   Debug.Log("MAEK_COLLIDER_AUDIT "+report.status+" checks="+checks.Count+" failed="+checks.Count(c=>!c.pass));
   if(report.status!="PASS")throw new Exception(string.Join(";",checks.Where(c=>!c.pass).Take(12).Select(c=>c.name+": "+c.detail)));
  }
 }
}
