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
  [Serializable] class Report {public string status,scope;public Check[] checks;public int captures,findings,frames,expectedCaptures,coveredPipes;public float distanceM;}
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
   BuildStandaloneTeam.Configure();
   checks.Clear();Directory.CreateDirectory(Output);
   var scene=EditorSceneManager.OpenScene(Root+"/Scenes/MAEKHydraulicCFD.unity");Physics.SyncTransforms();
   var services=UnityEngine.Object.FindFirstObjectByType<MAEKPipeServices>();services.Initialize();services.SetOverlay(false);
   var routes=JsonUtility.FromJson<DroneRouteSet>(AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/service_drone_routes.json").text);
   var start=new Vector3(-145,75,-135);var points=new List<TourPoint>{new TourPoint{position=start,target=new Vector3(-25,24,15),speed=12}};
   var expected=services.Data.pipes.Select(p=>p.id).OrderBy(x=>x).ToArray();
   if(expected.Length!=247||routes.routes.Select(r=>r.id).Distinct().Count()!=247||!expected.SequenceEqual(routes.routes.Select(r=>r.id).OrderBy(x=>x)))throw new Exception("Pipe catalogue and 247 drone routes differ");
   var remaining=routes.routes.OrderBy(r=>r.id).ToList();var visits=new List<PipeVisit>();var transfers=new List<PipeTransfer>();string previousPipe="OVERVIEW";
   while(remaining.Count>0) {
    var origin=points.Last().position;
    var route=remaining.OrderBy(r=>Mathf.Min(Vector3.Distance(origin,MAEKDroneInspection.V(r.waypoints[0].position)),Vector3.Distance(origin,MAEKDroneInspection.V(r.waypoints.Last().position)))).ThenBy(r=>r.id).First();
    bool reverse=Vector3.Distance(origin,MAEKDroneInspection.V(route.waypoints.Last().position))<Vector3.Distance(origin,MAEKDroneInspection.V(route.waypoints[0].position));
    var waypoints=reverse?route.waypoints.Reverse().ToArray():route.waypoints;
    var sourceIndices=Enumerable.Range(0,waypoints.Length).ToArray();
    if(!waypoints.Any(w=>Visible(MAEKDroneInspection.V(w.position),MAEKDroneInspection.V(w.target),route.id))){
     var extended=new List<DroneWaypoint>();var indices=new List<int>();
     for(int i=0;i<waypoints.Length;i++){if(i>0){var a=MAEKDroneInspection.V(waypoints[i-1].position);var b=MAEKDroneInspection.V(waypoints[i].position);var p=(a+b)*.5f;var t=(MAEKDroneInspection.V(waypoints[i-1].target)+MAEKDroneInspection.V(waypoints[i].target))*.5f;extended.Add(new DroneWaypoint{position=new[]{p.x,p.y,p.z},target=new[]{t.x,t.y,t.z}});indices.Add(-1);}extended.Add(waypoints[i]);indices.Add(i);}
     waypoints=extended.ToArray();sourceIndices=indices.ToArray();
    }
    Debug.Log("MAEK_PLAN_PIPE "+(visits.Count+1)+"/247 "+previousPipe+" -> "+route.id);
    int firstTransit=points.Count-1;
    AppendTransit(points,MAEKDroneInspection.V(waypoints[0].position),MAEKDroneInspection.V(waypoints[0].target),route.id);
    float transferLength=0;for(int i=firstTransit+1;i<points.Count;i++)transferLength+=Vector3.Distance(points[i-1].position,points[i].position);
    transfers.Add(new PipeTransfer{fromPipe=previousPipe,toPipe=route.id,firstLeg=firstTransit,lastLeg=points.Count-1,length=transferLength});
    var captures=CaptureIndices(waypoints,route.id);int firstLeg=points.Count;
    for(int i=0;i<waypoints.Length;i++)points.Add(new TourPoint{position=MAEKDroneInspection.V(waypoints[i].position),target=MAEKDroneInspection.V(waypoints[i].target),speed=3,dwell=captures.Contains(i)?.4f:0,pipeId=captures.Contains(i)?route.id:"",routePipeId=route.id,phase="inspection",sourceIndex=sourceIndices[i],sampleId=captures.Contains(i)?route.id+"/"+i.ToString("D3"):""});
    visits.Add(new PipeVisit{pipeId=route.id,firstLeg=firstLeg,lastLeg=points.Count-1,captures=captures.Count,reversed=reverse});
    remaining.Remove(route);previousPipe=route.id;
   }
   var plan=new TourPlan{basis="All 247 original pipe paths, nearest-endpoint order, swept-sphere verified transfers; sampled RGB views, not full-surface coverage or flight dynamics",points=points.ToArray(),pipeIds=expected,visits=visits.ToArray(),transfers=transfers.ToArray(),expectedCaptures=points.Count(p=>p.pipeId!="")};
   for(int i=1;i<points.Count;i++)plan.distanceM+=Vector3.Distance(points[i-1].position,points[i].position);
   for(int i=1;i<points.Count;i++)CheckThat("continuous segment "+i,Clear(points[i-1].position,points[i].position));
   foreach(var visit in visits)CheckThat("pipe route complete "+visit.pipeId,points.Skip(visit.firstLeg).Take(visit.lastLeg-visit.firstLeg+1).Count(p=>p.sourceIndex>=0)==routes.routes.First(r=>r.id==visit.pipeId).waypoints.Length&&visit.captures>0);
   foreach(var t in transfers)CheckThat("transfer "+t.fromPipe+" -> "+t.toPipe,Enumerable.Range(t.firstLeg+1,t.lastLeg-t.firstLeg).All(i=>Clear(points[i-1].position,points[i].position)));
   foreach(var point in points.Where(p=>p.pipeId!=""))CheckThat("visible target "+point.sampleId,Visible(point.position,point.target,point.pipeId));
   CheckThat("exact catalogue coverage",visits.Select(v=>v.pipeId).OrderBy(x=>x).SequenceEqual(expected));
   if(checks.Any(c=>!c.pass))throw new Exception("Route validation failed before scene save: "+string.Join(";",checks.Where(c=>!c.pass).Select(c=>c.name)));
   string source=Root+"/Source/inspection_tour.json";File.WriteAllText(source,JsonUtility.ToJson(plan,true));AssetDatabase.ImportAsset(source);
   var go=new GameObject("MAEK continuous drone inspection");var tour=go.AddComponent<MAEKInspectionTour>();go.AddComponent<MAEKTourRecorder>();
   var camera=new GameObject("MAEK continuous drone RGB").AddComponent<Camera>();camera.fieldOfView=52;camera.nearClipPlane=.03f;camera.farClipPlane=1500;camera.enabled=false;camera.transform.position=start;camera.transform.LookAt(points[0].target);
   tour.tourCamera=camera;tour.routeData=AssetDatabase.LoadAssetAtPath<TextAsset>(source);
   var process=go.AddComponent<MAEKProcessContext>();process.definitions=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/process_context.json");process.safetyDefinitions=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/worker_safety_context.json");process.Validate();
   var cfd=UnityEngine.Object.FindFirstObjectByType<MAEKCFDPlayback>();cfd.startInCFDView=false;
   // Existing service/cfd scenes remain untouched; this is a dedicated demonstration entry point.
   services.RestoreColors();EnhanceSteelworks.Apply(plan);EnhanceInteriors.Apply();BuildSupplementaryCircuits.Apply(tour);
   EditorSceneManager.SaveScene(scene,Root+"/Scenes/MAEKInspectionDemo.unity");
   EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene(Root+"/Scenes/MAEKInspectionDemo.unity",true)};AssetDatabase.SaveAssets();
   ReportTo("build_report.json",tour);Debug.Log("MAEK_TOUR_BUILD_PASS points="+points.Count+" captures="+plan.expectedCaptures+" metres="+plan.distanceM);
   AuditEnhancedColliders.Audit("after-interior");
   BuildSupplementaryCircuits.Audit();
   CaptureFactoryPhotos.CaptureScene();CaptureInteriorPhotos.CaptureScene();
  }
  static void ReportTo(string file,MAEKInspectionTour tour,int frames=0,int captures=0,int findings=0) {
   var plan=tour?.Plan??JsonUtility.FromJson<TourPlan>(File.ReadAllText(Root+"/Source/inspection_tour.json"));
   var report=new Report{status=checks.All(c=>c.pass)?"PASS":"FAIL",scope="All 247 pipes, sampled synthetic RGB inspection; not full surface/field accuracy",checks=checks.ToArray(),captures=tour?.Captures.Count??captures,findings=tour?.Findings.Count??findings,frames=frames,expectedCaptures=plan.expectedCaptures,coveredPipes=tour?.AnalysedPipes??0,distanceM=plan.distanceM};
   File.WriteAllText(Path.Combine(Output,file),JsonUtility.ToJson(report,true));if(report.status!="PASS")throw new Exception(string.Join("; ",checks.Where(c=>!c.pass).Select(c=>c.name)));
  }
  [MenuItem("MAEK/Verify continuous inspection end to end")]
  public static void Verify() {try{VerifyCore(false);if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  public static void RecordDemo() {try{VerifyCore(true);if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  static void VerifyCore(bool record) {
   checks.Clear();EditorSceneManager.OpenScene(Root+"/Scenes/MAEKInspectionDemo.unity");Physics.SyncTransforms();
   var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();tour.externalClock=true;tour.Initialize();
   var process=tour.GetComponent<MAEKProcessContext>();process.safetyDefinitions=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/worker_safety_context.json");process.Validate();CheckThat("process roles and scope",process.CountRole("primary_inspection")==138);
   string session=Path.Combine(Output,record?"recorded-session":"verified-session",DateTime.Now.ToString("yyyyMMdd-HHmmss"));tour.Begin(session);
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
      if(id=="BF1-W002"&&!checks.Any(c=>c.name=="wrong image hash rejected")) {
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
   CheckThat("247 pipes analysed",tour.AnalysedPipes==247);
   CheckThat("exact capture sequence",tour.Captures.Select(c=>c.sampleId).SequenceEqual(tour.Plan.points.Where(p=>p.pipeId!="").Select(p=>p.sampleId)));
   CheckThat("every photograph sees requested pipe",tour.Captures.All(c=>c.visibleTargetSamples>0));
   foreach(var id in tour.Plan.pipeIds)CheckThat("analysed pipe "+id,tour.Outcomes.Any(o=>o.pipeId==id&&(o.status=="candidate"||o.status=="no_candidate")));
   CheckThat("bounded continuous translation",maxMove<=12*dt+.001f,maxMove.ToString());
   CheckThat("bounded smooth rotation",maxRotation<=60*dt+.05f,maxRotation.ToString());
   CheckThat("actual image detection on inspection pipe",tour.Findings.Any(f=>f.pipeId=="BF1-W002"),"Not a fixture response; live Python RGB baseline");
   CheckThat("no inference errors",tour.AnalysisErrors.Count==0);
   foreach(var f in tour.Findings) {
    bool surface=Physics.Raycast(f.position+f.normal*.05f,-f.normal,out var hit,.12f,1<<8,QueryTriggerInteraction.Ignore)&&hit.collider.GetComponentInParent<MAEKPipeService>()?.lineId==f.pipeId;
    CheckThat("finding bound to actual pipe "+f.pipeId,surface);
   }
   // Test the actual runtime collision gate for every transfer, then inject an obstacle.
   foreach(var transfer in tour.Plan.transfers){
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
