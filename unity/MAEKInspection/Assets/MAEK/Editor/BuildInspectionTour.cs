using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace MAEK.Editor {
 public static class BuildInspectionTour {
  const string Root="Assets/MAEK";
  public static string Output=>Path.GetFullPath(Path.Combine(Application.dataPath,"../../../visualization/inspection_demo"));
  static readonly List<Check> checks=new List<Check>();
  [Serializable] class Check {public string name,detail;public bool pass;}
  [Serializable] class Report {public string status,scope;public Check[] checks;public int captures,findings,frames,expectedCaptures,coveredPipes,cataloguePipes,scheduledPipes,requiredCaptures,deferredCaptures,deferredPipes,partialPipes;public bool siteFirst;public float distanceM;}
  [Serializable] class AccessAudit {public string status,scope,layoutBefore,layoutAfter;public bool layoutUnchanged;public int cataloguePipes,requiredCaptures,scheduledCaptures,deferredCaptures,accessiblePipes,partialPipes,deferredPipes;public float bodyRadius,clearanceMargin,queryRadius;public InspectionAccess[] rows;}
  sealed class LocalClient:WebClient {
   protected override WebRequest GetWebRequest(Uri address){var request=base.GetWebRequest(address);request.Timeout=20000;return request;}
  }
  static void CheckThat(string name,bool pass,string detail="") {checks.Add(new Check{name=name,pass=pass,detail=detail});if(!pass)Debug.LogError(name+": "+detail);}
  static bool Clear(Vector3 a,Vector3 b,float radius=.12f) {
   if(Physics.CheckSphere(a,radius,1<<8,QueryTriggerInteraction.Ignore)||Physics.CheckSphere(b,radius,1<<8,QueryTriggerInteraction.Ignore))return false;
   var d=b-a;return d.magnitude<1e-5f||!Physics.SphereCast(a,radius,d.normalized,out var hit,d.magnitude,1<<8,QueryTriggerInteraction.Ignore);
  }
  // Coarse 3D A*, then exact swept-sphere shortcuts. Each link is verified against scene colliders.
  static List<Vector3> Connect(Vector3 start,Vector3 end) {
   if(Clear(start,end))return new List<Vector3>{start,end};
   foreach(float grid in new[]{2f,1f,.5f}){var path=Search(start,end,grid);if(path!=null)return path;}
   throw new Exception("No continuous collision-free route: "+start+" -> "+end);
  }
  static List<Vector3> Search(Vector3 start,Vector3 end,float step) {
   var min=Vector3.Min(start,end)-new Vector3(24,10,24);var max=Vector3.Max(start,end)+new Vector3(24,35,24);min.y=Mathf.Max(.25f,min.y);
   Func<Vector3Int,Vector3> position=k=>new Vector3(k.x*step,k.y*step,k.z*step);
   var queue=new SortedSet<Tuple<float,int>>();int serial=0;
   var nodes=new Dictionary<int,Vector3Int>();var cost=new Dictionary<Vector3Int,float>();var previous=new Dictionary<Vector3Int,Vector3Int>();
   var first=new HashSet<Vector3Int>();var occupied=new Dictionary<Vector3Int,bool>();
   Func<Vector3Int,bool> free=k=>{if(occupied.TryGetValue(k,out var ok))return ok;var p=position(k);bool valid=p.x>=min.x&&p.y>=min.y&&p.z>=min.z&&p.x<=max.x&&p.y<=max.y&&p.z<=max.z&&!Physics.CheckSphere(p,.12f,1<<8,QueryTriggerInteraction.Ignore);occupied[k]=valid;return valid;};
   var center=Vector3Int.RoundToInt(start/step);
   for(int x=-2;x<=2;x++)for(int y=-2;y<=2;y++)for(int z=-2;z<=2;z++) {
    var k=center+new Vector3Int(x,y,z);if(!free(k)||!Clear(start,position(k)))continue;
    float c=Vector3.Distance(start,position(k));cost[k]=c;first.Add(k);nodes[serial]=k;queue.Add(Tuple.Create(c+Vector3.Distance(position(k),end),serial++));
   }
   var closed=new HashSet<Vector3Int>();Vector3Int goal=default;bool found=false;
   var directions=new[]{Vector3Int.right,Vector3Int.left,Vector3Int.up,Vector3Int.down,new Vector3Int(0,0,1),new Vector3Int(0,0,-1)};
   while(queue.Count>0&&closed.Count<80000) {
    var item=queue.Min;queue.Remove(item);var key=nodes[item.Item2];if(!closed.Add(key))continue;var p=position(key);
    if(Vector3.Distance(p,end)<10&&Clear(p,end)){goal=key;found=true;break;}
    foreach(var d in directions){var next=key+d;if(closed.Contains(next)||!free(next)||!Clear(p,position(next)))continue;
     float c=cost[key]+step;if(cost.TryGetValue(next,out var old)&&c>=old)continue;cost[next]=c;previous[next]=key;nodes[serial]=next;queue.Add(Tuple.Create(c+Vector3.Distance(position(next),end),serial++));}
   }
   if(!found)return null;
   var reverse=new List<Vector3>{end,position(goal)};while(previous.ContainsKey(goal)){goal=previous[goal];reverse.Add(position(goal));}reverse.Add(start);reverse.Reverse();
   var smooth=new List<Vector3>{start};int at=0;while(at<reverse.Count-1){int next=reverse.Count-1;while(next>at+1&&!Clear(reverse[at],reverse[next]))next--;smooth.Add(reverse[next]);at=next;}return smooth;
  }
  static bool Visible(Vector3 position,Vector3 target,string pipeId) {
   var d=target-position;return d.sqrMagnitude>.001f&&Physics.Raycast(position,d.normalized,out var hit,d.magnitude+2,1<<8,QueryTriggerInteraction.Ignore)&&hit.collider.GetComponentInParent<MAEKPipeService>()?.lineId==pipeId;
  }
  [Serializable] class VisibilityRow {public string pipe;public int originalVisible,midpointVisible;public string[] firstHits;}
  [Serializable] class VisibilityReport {public VisibilityRow[] rows;}
  public static void AuditVisibility() {
   EditorSceneManager.OpenScene(Root+"/Scenes/MAEKHydraulicCFD.unity");Physics.SyncTransforms();
   var routes=JsonUtility.FromJson<DroneRouteSet>(File.ReadAllText(Root+"/Source/service_drone_routes.json"));var rows=new List<VisibilityRow>();
   foreach(var route in routes.routes){int originals=0,mids=0;var hits=new List<string>();
    for(int i=0;i<route.waypoints.Length;i++){var a=MAEKDroneInspection.V(route.waypoints[i].position);var t=MAEKDroneInspection.V(route.waypoints[i].target);if(Visible(a,t,route.id))originals++;else if(Physics.Raycast(a,(t-a).normalized,out var hit,(t-a).magnitude+2,1<<8,QueryTriggerInteraction.Ignore))hits.Add(hit.collider.name+" / "+hit.collider.GetComponentInParent<MAEKAssetInfo>()?.assetId);
     if(i>0){var b=MAEKDroneInspection.V(route.waypoints[i-1].position);var u=MAEKDroneInspection.V(route.waypoints[i-1].target);if(Visible((a+b)*.5f,(t+u)*.5f,route.id))mids++;}}
    rows.Add(new VisibilityRow{pipe=route.id,originalVisible=originals,midpointVisible=mids,firstHits=hits.Distinct().Take(4).ToArray()});}
   File.WriteAllText(Path.Combine(Output,"visibility_audit.json"),JsonUtility.ToJson(new VisibilityReport{rows=rows.ToArray()},true));
   Debug.Log("MAEK_VISIBILITY_AUDIT originalZero="+rows.Count(r=>r.originalVisible==0)+" bothZero="+rows.Count(r=>r.originalVisible+r.midpointVisible==0));if(Application.isBatchMode)EditorApplication.Exit(0);
  }
  static void AppendTransit(List<TourPoint> points,Vector3 end,Vector3 look,string pipeId) {
   var path=Connect(points.Last().position,end);
   for(int k=1;k<path.Count;k++) {
    var a=path[k-1];var b=path[k];int pieces=Mathf.Max(1,Mathf.CeilToInt(Vector3.Distance(a,b)/8));
    for(int j=1;j<=pieces;j++)points.Add(new TourPoint{position=Vector3.Lerp(a,b,(float)j/pieces),target=look,speed=12,routePipeId=pipeId,phase="transit"});
   }
  }
  static HashSet<int> CaptureIndices(DroneWaypoint[] waypoints,string id) {
   var visible=Enumerable.Range(0,waypoints.Length).Where(i=>Visible(MAEKDroneInspection.V(waypoints[i].position),MAEKDroneInspection.V(waypoints[i].target),id)).ToArray();
   if(visible.Length==0)throw new Exception("No visible capture waypoint for "+id);
   var chosen=new HashSet<int>{visible[0],visible[visible.Length/2],visible.Last()};
   float distance=0;for(int i=1;i<waypoints.Length;i++){distance+=Vector3.Distance(MAEKDroneInspection.V(waypoints[i-1].position),MAEKDroneInspection.V(waypoints[i].position));if(distance>=12){chosen.Add(visible.OrderBy(v=>Math.Abs(v-i)).First());distance=0;}}
   // Existing illustrated corrosion area must remain in the regression tour, without supplying its label to inference.
   if(id=="BF1-W002")chosen.Add(visible.OrderBy(i=>Vector3.Distance(MAEKDroneInspection.V(waypoints[i].target),new Vector3(-72,6.5f,-12))).First());
   return chosen;
  }
  [MenuItem("MAEK/Build continuous inspection demo")]
  public static void Run() {try{Build();if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  public static void Build() {
   BuildStandaloneTeam.Configure();checks.Clear();Directory.CreateDirectory(Output);
   CheckThat("equipment placement independent of route",EnhanceSteelworks.VerifyLayoutIndependence(probe=>{
    EditorSceneManager.OpenScene(Root+"/Scenes/MAEKHydraulicCFD.unity");
    var probeServices=UnityEngine.Object.FindFirstObjectByType<MAEKPipeServices>();probeServices.Initialize();probeServices.RestoreColors();EnhanceSteelworks.Apply(probe);
   }));
   var scene=EditorSceneManager.OpenScene(Root+"/Scenes/MAEKHydraulicCFD.unity");Physics.SyncTransforms();
   var legacy=JsonUtility.FromJson<TourPlan>(File.ReadAllText(Root+"/Source/inspection_tour.json"));
   var services=UnityEngine.Object.FindFirstObjectByType<MAEKPipeServices>();services.Initialize();services.SetOverlay(false);
   CheckThat("original 247 catalogue retained",services.Data.pipes.Select(p=>p.id).OrderBy(p=>p).SequenceEqual(legacy.pipeIds.OrderBy(p=>p)));
   var go=new GameObject("MAEK layout-first drone inspection");var tour=go.AddComponent<MAEKInspectionTour>();go.AddComponent<MAEKTourRecorder>();
   var camera=new GameObject("MAEK continuous drone RGB").AddComponent<Camera>();camera.fieldOfView=52;camera.nearClipPlane=.03f;camera.farClipPlane=1500;camera.enabled=false;camera.transform.position=legacy.points[0].position;camera.transform.LookAt(legacy.points[0].target);
   tour.tourCamera=camera;tour.routeData=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/inspection_tour.json");
   var process=go.AddComponent<MAEKProcessContext>();process.definitions=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/process_context.json");process.safetyDefinitions=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/worker_safety_context.json");process.Validate();
   var cfd=UnityEngine.Object.FindFirstObjectByType<MAEKCFDPlayback>();cfd.startInCFDView=false;
   // Finish the physical site before routing. No flight or photograph corridor is reserved.
   services.RestoreColors();EnhanceSteelworks.Apply(legacy);EnhanceInteriors.Apply();BuildSupplementaryCircuits.Apply(tour);Physics.SyncTransforms();
   string fixedLayout=SiteInspectionPlanner.LayoutSignature();
   var plan=SiteInspectionPlanner.Build(legacy);string main=Root+"/Source/site_inspection_tour.json";
   File.WriteAllText(main,JsonUtility.ToJson(plan,true));AssetDatabase.ImportAsset(main);tour.SetRoute(AssetDatabase.LoadAssetAtPath<TextAsset>(main));
   var extra=go.GetComponent<MAEKSupplementaryCircuits>();extra.originalRoute=tour.routeData;
   var oldExtra=JsonUtility.FromJson<TourPlan>(extra.inspectionRoute.text);var extraPlan=SiteInspectionPlanner.Build(oldExtra);string annex=Root+"/Source/site_supplementary_tour.json";
   File.WriteAllText(annex,JsonUtility.ToJson(extraPlan,true));AssetDatabase.ImportAsset(annex);extra.inspectionRoute=AssetDatabase.LoadAssetAtPath<TextAsset>(annex);
   string afterPlanning=SiteInspectionPlanner.LayoutSignature();CheckThat("planning cannot modify fixed equipment",fixedLayout==afterPlanning);
   var audit=new AccessAudit{status=fixedLayout==afterPlanning?"PASS":"FAIL",scope="Fixed virtual equipment first; no geometry changes during route planning. Counts refer to required observation poses, not physical surface coverage or actual site authorization.",layoutBefore=fixedLayout,layoutAfter=afterPlanning,layoutUnchanged=fixedLayout==afterPlanning,cataloguePipes=plan.pipeIds.Length,requiredCaptures=plan.requiredCaptures,scheduledCaptures=plan.expectedCaptures,deferredCaptures=plan.access.Count(a=>!a.accessible),accessiblePipes=plan.visits.Count(v=>v.accessStatus=="accessible"),partialPipes=plan.visits.Count(v=>v.accessStatus=="partial"),deferredPipes=plan.visits.Count(v=>v.accessStatus=="deferred"),bodyRadius=plan.bodyRadius,clearanceMargin=plan.clearanceMargin,queryRadius=plan.radius,rows=plan.access};
   File.WriteAllText(Path.Combine(Output,"site_access_audit.json"),JsonUtility.ToJson(audit,true));
   var scenarios=go.AddComponent<MAEKInspectionScenarios>();scenarios.definitions=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/inspection_scenarios.json");
   go.AddComponent<MAEKVirtualDrone>().tour=tour;go.AddComponent<MAEKDashboardLink>();
   foreach(var row in plan.access)CheckThat("access partition "+row.sampleId,row.accessible==plan.points.Any(p=>p.pipeId==row.pipeId&&p.sampleId==row.sampleId));
   CheckThat("all required observations accounted",plan.requiredCaptures==legacy.expectedCaptures&&plan.access.Length==legacy.expectedCaptures);
   CheckThat("deferred observations retained",plan.access.Any(a=>!a.accessible));
   EditorSceneManager.SaveScene(scene,Root+"/Scenes/MAEKInspectionDemo.unity");EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene(Root+"/Scenes/MAEKInspectionDemo.unity",true)};AssetDatabase.SaveAssets();
   ReportTo("build_report.json",tour);Debug.Log("MAEK_SITE_BUILD_PASS pipes="+plan.pipeIds.Length+" scheduled="+plan.expectedCaptures+" required="+plan.requiredCaptures+" deferred="+plan.access.Count(a=>!a.accessible));
   AuditEnhancedColliders.Audit("after-interior");BuildSupplementaryCircuits.Audit();CaptureFactoryPhotos.CaptureScene();CaptureInteriorPhotos.CaptureScene();
  }
  static void ReportTo(string file,MAEKInspectionTour tour,int frames=0,int captures=0,int findings=0) {
   var plan=tour?.Plan??JsonUtility.FromJson<TourPlan>(File.ReadAllText(Root+"/Source/inspection_tour.json"));
   var report=new Report{status=checks.All(c=>c.pass)?"PASS":"FAIL",scope="Layout-first catalogue accounting; scheduled observations only, explicit inspection deferral; not full-surface/field accuracy",siteFirst=plan.siteFirst,cataloguePipes=plan.pipeIds.Length,scheduledPipes=plan.visits.Count(v=>v.captures>0),requiredCaptures=plan.siteFirst?plan.requiredCaptures:plan.expectedCaptures,deferredCaptures=plan.siteFirst?plan.access.Count(a=>!a.accessible):0,deferredPipes=plan.visits.Count(v=>v.captures==0),partialPipes=plan.visits.Count(v=>v.captures>0&&v.captures<v.requiredCaptures),checks=checks.ToArray(),captures=tour?.Captures.Count??captures,findings=tour?.Findings.Count??findings,frames=frames,expectedCaptures=plan.expectedCaptures,coveredPipes=tour?.AnalysedPipes??0,distanceM=plan.distanceM};
   File.WriteAllText(Path.Combine(Output,file),JsonUtility.ToJson(report,true));if(report.status!="PASS")throw new Exception(string.Join("; ",checks.Where(c=>!c.pass).Select(c=>c.name)));
  }
  [MenuItem("MAEK/Verify continuous inspection end to end")]
  public static void Verify() {try{VerifyCore(false);if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  public static void RecordDemo() {try{VerifyCore(true);if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  static void VerifyCore(bool record) {
   checks.Clear();EditorSceneManager.OpenScene(Root+"/Scenes/MAEKInspectionDemo.unity");Physics.SyncTransforms();
   var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();tour.externalClock=true;tour.Initialize();
   var process=tour.GetComponent<MAEKProcessContext>();process.safetyDefinitions=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/worker_safety_context.json");process.Validate();CheckThat("process roles and scope",process.CountRole("primary_inspection")==138);
   string session=Path.Combine(Output,record?"recorded-session":"verified-session",DateTime.Now.ToString("yyyyMMdd-HHmmss"));tour.Begin(session);CheckThat("no observation is not healthy",process.FollowUps().rows.All(r=>r.observationStatus=="unobserved"&&r.status=="inspection_deferred"));
   var recorder=tour.GetComponent<MAEKTourRecorder>();if(record){recorder.width=960;recorder.height=540;recorder.fps=12;recorder.StartRecording(tour,Path.Combine(session,"video"));}
   float dt=1f/12;float maxMove=0,maxRotation=0;int frames=0;
   using(var client=new LocalClient()) {
    client.Headers[HttpRequestHeader.ContentType]="application/json";
    for(int step=0;step<400000&&!tour.Complete&&!tour.Blocked;step++) {
     var before=tour.tourCamera.transform.position;var rotation=tour.tourCamera.transform.rotation;tour.Advance(dt);
     maxMove=Mathf.Max(maxMove,Vector3.Distance(before,tour.tourCamera.transform.position));maxRotation=Mathf.Max(maxRotation,Quaternion.Angle(rotation,tour.tourCamera.transform.rotation));
     if(tour.PendingPipe!="") {
      // Advance deliberately waits until the same runtime analysis path has consumed the capture.
      string id=tour.PendingPipe;var request=tour.MakeCapture(id,out var context);
      string json=client.UploadString(tour.endpoint,JsonUtility.ToJson(request));tour.ApplyResult(context,json);
      tour.ConsumePendingForVerification();
      if(!checks.Any(c=>c.name=="wrong image hash rejected")) {
       var original=tour.tourCamera.transform.position;tour.tourCamera.transform.position+=Vector3.up*7;
       bool provenanceRejected=false;try{tour.ApplyResult(context,json.Replace(context.imageSha256,new string('0',64)));}catch{provenanceRejected=true;}
       CheckThat("wrong image hash rejected",provenanceRejected);
       bool requestRejected=false;try{tour.ApplyResult(context,json.Replace(context.requestId,"another-request"));}catch{requestRejected=true;}
       CheckThat("wrong capture request rejected",requestRejected);
       var mismatched=JsonUtility.FromJson<RGBResult>(json);mismatched.width++;
       bool sizeRejected=false;try{tour.ApplyResult(context,JsonUtility.ToJson(mismatched));}catch{sizeRejected=true;}
       CheckThat("wrong image dimensions rejected",sizeRejected);
       var ray=context.Ray(.5f,.5f);CheckThat("projection uses capture pose",Vector3.Distance(ray.origin,context.position)<1e-6f&&Vector3.Distance(ray.origin,tour.tourCamera.transform.position)>6);
       tour.tourCamera.transform.position=original;
      }
     }
     if(record){recorder.CaptureFrame();frames++;}
     if(step%2400==0)Debug.Log("MAEK_TOUR_PROGRESS frame="+step+" leg="+tour.Leg+" pipes="+tour.AnalysedPipes+" captures="+tour.Captures.Count+" findings="+tour.Findings.Count);
    }
   }
   if(record)recorder.StopRecording();
   CheckThat("tour completes",tour.Complete&&!tour.Blocked);
   CheckThat("all planned captures executed",tour.Captures.Count==tour.Plan.expectedCaptures&&tour.Outcomes.Count==tour.Plan.expectedCaptures);
   CheckThat("catalogue retained including inaccessible pipes",tour.Plan.pipeIds.Length==247&&process.FollowUps().rows.Length==247);
   CheckThat("every required sample accounted",tour.Plan.access.Length==tour.Plan.requiredCaptures&&tour.Plan.access.Count(a=>a.accessible)==tour.Captures.Count);
   CheckThat("exact capture sequence",tour.Captures.Select(c=>c.sampleId).SequenceEqual(tour.Plan.points.Where(p=>p.pipeId!="").Select(p=>p.sampleId)));
   CheckThat("every photograph sees requested pipe",tour.Captures.All(c=>c.visibleTargetSamples>0));
   foreach(var visit in tour.Plan.visits){
    var follow=process.FollowUps().rows.Single(r=>r.pipeId==visit.pipeId);
    CheckThat("scheduled images executed "+visit.pipeId,tour.Outcomes.Count(o=>o.pipeId==visit.pipeId)==visit.captures);
    CheckThat("required sample count retained "+visit.pipeId,follow.plannedImages==visit.requiredCaptures);
    if(visit.captures<visit.requiredCaptures)CheckThat("inaccessible observations stay deferred "+visit.pipeId,follow.inspectionStatus!="completed"&&follow.status!="no_rgb_candidate");
    if(visit.captures==0)CheckThat("unobserved has no fabricated RGB "+visit.pipeId,follow.status=="inspection_deferred"&&follow.observationStatus=="unobserved"&&follow.evidenceRequestIds.Length==0&&!tour.Captures.Any(c=>c.pipeId==visit.pipeId));
   }
   CheckThat("bounded continuous translation",maxMove<=12*dt+.001f,maxMove.ToString());
   CheckThat("bounded smooth rotation",maxRotation<=60*dt+.05f,maxRotation.ToString());
   CheckThat("inaccessible samples exist without forced coverage",tour.Plan.access.Any(a=>!a.accessible));
   CheckThat("no inference errors",tour.AnalysisErrors.Count==0);
   foreach(var f in tour.Findings) {
    bool surface=Physics.Raycast(f.position+f.normal*.05f,-f.normal,out var hit,.12f,1<<8,QueryTriggerInteraction.Ignore)&&hit.collider.GetComponentInParent<MAEKPipeService>()?.lineId==f.pipeId;
    CheckThat("finding bound to actual pipe "+f.pipeId,surface);
   }
   // Test the actual runtime collision gate for every transfer, then inject an obstacle.
   foreach(var transfer in tour.Plan.transfers){
    if(transfer.lastLeg<=transfer.firstLeg)continue;
    int j=Enumerable.Range(transfer.firstLeg+1,transfer.lastLeg-transfer.firstLeg).OrderByDescending(i=>Vector3.Distance(tour.Plan.points[i-1].position,tour.Plan.points[i].position)).First();
    var a=tour.Plan.points[j-1].position;var b=tour.Plan.points[j].position;
    var obstacle=GameObject.CreatePrimitive(PrimitiveType.Cube);obstacle.layer=8;obstacle.transform.position=(a+b)*.5f;obstacle.transform.localScale=Vector3.one*.3f;Physics.SyncTransforms();
    CheckThat("transfer obstacle rejected "+transfer.toPipe,!tour.SegmentClear(a,b));
    UnityEngine.Object.DestroyImmediate(obstacle);Physics.SyncTransforms();
    CheckThat("transfer clear after obstacle removal "+transfer.toPipe,tour.SegmentClear(a,b));
   }
   // Whole-pipe captures can see rust-coloured fittings: do not force old single-view negatives.
   int captures=tour.Captures.Count,findings=tour.Findings.Count;
   ReportTo(record?"record_report.json":"integration_report.json",tour,frames,captures,findings);
   tour.Begin(Path.Combine(session,"obstacle-check"));var cube=GameObject.CreatePrimitive(PrimitiveType.Cube);cube.layer=8;cube.transform.position=tour.tourCamera.transform.position;cube.transform.localScale=Vector3.one;Physics.SyncTransforms();
   var position=tour.tourCamera.transform.position;tour.Advance(dt);CheckThat("new obstacle stops instead of clipping",tour.Blocked&&tour.tourCamera.transform.position==position);UnityEngine.Object.DestroyImmediate(cube);Physics.SyncTransforms();tour.End();
   var exterior=UnityEngine.Object.FindFirstObjectByType<MAEKExteriorDetail>();
   var playback=UnityEngine.Object.FindFirstObjectByType<MAEKCFDPlayback>();
   CheckThat("realism exterior controller present",exterior&&playback);
   if(exterior&&playback){
    var physical=exterior.GetComponentsInChildren<Collider>();
    playback.SetView(true);exterior.Refresh();
    CheckThat("CFD cutaway hides added exterior",exterior.IsHidden&&exterior.GetComponentsInChildren<Renderer>().All(r=>!r.enabled));
    CheckThat("CFD visibility retains collision geometry",physical.All(c=>c.enabled));
    playback.SetView(false);exterior.Refresh();
    CheckThat("inspection restores added exterior",!exterior.IsHidden&&exterior.GetComponentsInChildren<Renderer>().All(r=>r.enabled));
   }
   // Do not save editor previews/state back into the deliverable scene.
   var saved=JsonUtility.FromJson<Report>(File.ReadAllText(Path.Combine(Output,record?"record_report.json":"integration_report.json")));saved.checks=checks.ToArray();saved.status=checks.All(c=>c.pass)?"PASS":"FAIL";File.WriteAllText(Path.Combine(Output,record?"record_report.json":"integration_report.json"),JsonUtility.ToJson(saved,true));if(saved.status!="PASS")throw new Exception("Obstacle regression failed");
   File.WriteAllText(Path.Combine(Output,record?"latest_recording.txt":"latest_verification.txt"),session);
   Debug.Log("MAEK_TOUR_VERIFIED checks="+checks.Count+" session="+session);
  }
 }
}
