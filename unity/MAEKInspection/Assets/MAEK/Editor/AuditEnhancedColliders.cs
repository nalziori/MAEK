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
  [Serializable] class Report {
   public string status,utc,scope,layoutSignature;
   public bool layoutFirst=true,siteFirst,accessStatisticsAvailable,legacyRouteDiagnosticsOnly;
   public float radius,bodyRadius,clearanceMargin;
   public int segments,views,detailColliders,pipeCount,requiredCaptures,scheduledCaptures;
   public int legacyBlockedSegments,legacyOccludedViews;
   public int accessibleSamples,deferredSamples,unreachableSamples,accessiblePipes,partialPipes,deferredPipes;
   public Check[] checks;
  }
  static readonly List<Check> checks=new List<Check>();
  static void CheckThat(string n,bool p,string d=""){checks.Add(new Check{name=n,pass=p,detail=d});}
  public static void Run(){try{EditorSceneManager.OpenScene("Assets/MAEK/Scenes/MAEKInspectionDemo.unity");Audit("manual-recheck");if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  public static void Rebuild(){try{BuildInspectionTour.Build();Audit("manual-recheck");if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  public static void Audit(string stage){
   checks.Clear();Physics.SyncTransforms();
   // Keep the live planner assignment; reopening a scene here can restore stale routeData.
   var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();
   if(!tour||!tour.routeData)throw new Exception("Collider audit requires the scheduled tour.routeData");
   tour.Initialize();var plan=tour.Plan;
   if(plan==null||plan.points==null)throw new Exception("Collider audit requires an initialized scheduled plan");
   CheckThat("positive flight envelope",plan.radius>0);
   if(plan.siteFirst)CheckThat("body plus clearance envelope",plan.bodyRadius>0&&plan.clearanceMargin>=0&&Mathf.Abs(plan.radius-plan.bodyRadius-plan.clearanceMargin)<.00001f);
   // Only points actually scheduled by the new planner form flight/capture obligations.
   var access=plan.access;
   bool hasAccess=access!=null;
   int accessibleSamples=hasAccess?access.Count(a=>a.accessible):0;
   int deferredSamples=hasAccess?access.Count(a=>!a.accessible):0;
   int legacyBlocked=0,legacyOccluded=0;
   for(int i=1;i<plan.points.Length;i++){
    var a=plan.points[i-1].position;var b=plan.points[i].position;var d=b-a;
    bool clear=!Physics.CheckSphere(a,plan.radius,1<<8,QueryTriggerInteraction.Ignore)&&!Physics.CheckSphere(b,plan.radius,1<<8,QueryTriggerInteraction.Ignore)&&
     (d.sqrMagnitude<1e-8f||!Physics.SphereCast(a,plan.radius,d.normalized,out _,d.magnitude,1<<8,QueryTriggerInteraction.Ignore));
    if(plan.siteFirst)CheckThat("flight "+i,clear);else if(!clear)legacyBlocked++;
   }
   int views=0;foreach(var p in plan.points.Where(p=>!string.IsNullOrEmpty(p.pipeId))){var d=p.target-p.position;
    if(plan.siteFirst)CheckThat("scheduled reachable capture "+p.sampleId,hasAccess&&access.Any(a=>a.accessible&&a.pipeId==p.pipeId&&a.sampleId==p.sampleId));
    if(d.sqrMagnitude<1e-8f){if(plan.siteFirst)CheckThat("capture "+p.sampleId,false,"zero target direction");else legacyOccluded++;views++;continue;}
    bool hit=Physics.Raycast(p.position,d.normalized,out var h,d.magnitude+2,1<<8,QueryTriggerInteraction.Ignore);
    var context=new InspectionCapture{position=p.position,rotation=Quaternion.LookRotation(d),fieldOfView=tour.tourCamera?tour.tourCamera.fieldOfView:52,aspect=(float)tour.captureWidth/Mathf.Max(1,tour.captureHeight)};
    int visible=0;for(int x=-2;x<=2;x++)for(int y=-2;y<=2;y++)
     if(Physics.Raycast(context.Ray(.5f+x*.012f,.5f+y*.012f),out var sample,250,1<<8,QueryTriggerInteraction.Ignore)&&sample.collider.GetComponentInParent<MAEKPipeService>()?.lineId==p.pipeId)visible++;
    if(plan.siteFirst)CheckThat("capture "+p.sampleId,visible>0,"visible rays="+visible+"; centre first="+(hit?h.collider.name:"no hit"));
    else if(visible==0)legacyOccluded++;
    views++;
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
   var catalogue=UnityEngine.Object.FindObjectsByType<MAEKPipeService>(FindObjectsSortMode.None);
   int pipes=catalogue.Length;CheckThat("247 process pipes",pipes==247);
   CheckThat("full catalogue retained, captures may be deferred",plan.pipeIds!=null&&plan.pipeIds.OrderBy(id=>id,StringComparer.Ordinal).SequenceEqual(catalogue.Select(p=>p.lineId).OrderBy(id=>id,StringComparer.Ordinal)));
   if(plan.siteFirst){
    CheckThat("scheduled capture count",views==plan.expectedCaptures);
    CheckThat("accessible observations exactly scheduled",hasAccess&&
     plan.points.Where(p=>!string.IsNullOrEmpty(p.pipeId)).Select(p=>p.pipeId+"/"+p.sampleId).OrderBy(id=>id,StringComparer.Ordinal)
      .SequenceEqual(access.Where(a=>a.accessible).Select(a=>a.pipeId+"/"+a.sampleId).OrderBy(id=>id,StringComparer.Ordinal)));
   }
   var report=new Report{
    status=checks.All(c=>c.pass)?(plan.siteFirst?"PASS":"LAYOUT_CHECKED"):"FAIL",utc=DateTime.UtcNow.ToString("O"),
    scope=(plan.siteFirst?"Scheduled-route verification. ":"Geometry/pedestrian gate only; legacy flight/views are diagnostics, not certification. ")+"Fixed reference layout, not as-built. Current tour.Plan only: scheduled reachable flight segments/captures, not legacy-capture coverage. Detail/process physical clearance; 0.3m-radius 1.7m-high pedestrian capsule and station checks. Intended structural joints excluded. Deferred/unreachable samples are not inspected.",
    layoutFirst=true,siteFirst=plan.siteFirst,legacyRouteDiagnosticsOnly=!plan.siteFirst,
    legacyBlockedSegments=legacyBlocked,legacyOccludedViews=legacyOccluded,layoutSignature=exterior?EnhanceSteelworks.LayoutSignature():null,
    radius=plan.radius,bodyRadius=plan.bodyRadius,clearanceMargin=plan.clearanceMargin,
    segments=Mathf.Max(0,plan.points.Length-1),views=views,detailColliders=colliderCount,pipeCount=pipes,
    requiredCaptures=plan.requiredCaptures,scheduledCaptures=plan.expectedCaptures,accessStatisticsAvailable=hasAccess,
    accessibleSamples=accessibleSamples,deferredSamples=deferredSamples,
    unreachableSamples=hasAccess?access.Count(a=>!a.accessible&&string.Equals(a.status,"unreachable",StringComparison.OrdinalIgnoreCase)):0,
    accessiblePipes=hasAccess?access.GroupBy(a=>a.pipeId).Count(g=>g.All(a=>a.accessible)):0,
    partialPipes=hasAccess?access.GroupBy(a=>a.pipeId).Count(g=>g.Any(a=>a.accessible)&&g.Any(a=>!a.accessible)):0,
    deferredPipes=hasAccess?access.GroupBy(a=>a.pipeId).Count(g=>!g.Any(a=>a.accessible)):0,
    checks=checks.ToArray()};
   string folder=Path.GetFullPath("../../visualization/interior_detail");Directory.CreateDirectory(folder);
   File.WriteAllText(Path.Combine(folder,stage+"-colliders.json"),JsonUtility.ToJson(report,true));
   Debug.Log("MAEK_COLLIDER_AUDIT "+report.status+" checks="+checks.Count+" failed="+checks.Count(c=>!c.pass));
   if(checks.Any(c=>!c.pass))throw new Exception(string.Join(";",checks.Where(c=>!c.pass).Take(12).Select(c=>c.name+": "+c.detail)));
  }
 }
}
