using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using UnityEngine;
using UnityEngine.Networking;

namespace MAEK {
 [Serializable] public class TourPoint {
  public Vector3 position, target; public float speed=8, dwell; public string pipeId="";
  public string routePipeId="",sampleId="",phase="transit";
  public int sourceIndex=-1;
 }
 [Serializable] public class PipeVisit {public string pipeId;public int firstLeg,lastLeg,captures,requiredCaptures;public string accessStatus;public string[] accessReasons;public bool reversed;}
 [Serializable] public class InspectionAccess {public string pipeId,sampleId,status,reason;public Vector3 position,target;public int sourceIndex;public bool accessible;}
 [Serializable] public class PipeInspectionProgress {
  public string pipeId,observationStatus,inspectionStatus,accessStatus;public string[] accessReasons;
  public int plannedImages,scheduledImages,deferredImages,analysedImages;
 }
 [Serializable] public class PipeTransfer {public string fromPipe,toPipe;public int firstLeg,lastLeg;public float length;}
 [Serializable] public class TourPlan {
  public int version=2; public bool siteFirst;public float bodyRadius=.24f,clearanceMargin=.10f;public InspectionAccess[] access; public float radius=.34f; public string basis; public TourPoint[] points;
  public string[] pipeIds;public PipeVisit[] visits;public PipeTransfer[] transfers;
  public int expectedCaptures,requiredCaptures;public float distanceM;
 }
 [Serializable] public class RGBRequest {public string requestId,imageBase64,sessionId,pipeId,sampleId,scenarioId,scenarioRunId;}
 [Serializable] public class RGBQuality {public bool canInfer;public string code;public float meanLuminance;}
 [Serializable] public class RGBSample {public float u,v;}
 [Serializable] public class RGBComponent {
  public string kind; public int pixelCount; public int[] bbox; public RGBSample[] samples;
 }
 [Serializable] public class RGBResult {
  public int version,width,height; public string requestId,status,model,imageSha256,scope;
  public RGBComponent[] components;
  public RGBQuality quality;
 }
 [Serializable] public class InspectionCapture {
  public string requestId,pipeId,imageSha256,sampleId; public Vector3 position; public Quaternion rotation;
  public int visibleTargetSamples;
  public float fieldOfView,aspect; public int width,height;
  public Ray Ray(float u,float v) {
   float t=Mathf.Tan(fieldOfView*Mathf.Deg2Rad*.5f);
   return new Ray(position,rotation*new Vector3((u*2-1)*t*aspect,(1-v*2)*t,1).normalized);
  }
 }
 [Serializable] public class InspectionOutcome {
  public string requestId,pipeId,sampleId,status;public int visibleTargetSamples,newFindings;
 }
 [Serializable] public class InspectionFinding {
  public string pipeId,requestId,kind,model,imageSha256; public Vector3 position,normal;
  public int pixelCount,mappedSamples; public string recommendation="UT/PEC follow-up; not crack prediction";
 }
 [Serializable] public class VideoPin {public string pipeId,label; public float u,v;}
 [Serializable] public class TourVideoFrame {
  public int frame; public float time; public Vector3 position; public string stage,pipeId,status;
  public string scope="합성 제철소 · RGB 부식 규칙 기준선 · 균열 발생 예측 아님";
  public string processContext,numericalScope,workerContext;public string workPermissionStatus="not_assessed";public VideoPin[] pins;
 }
 [DefaultExecutionOrder(150)]
 public sealed class MAEKInspectionTour:MonoBehaviour {
  public TextAsset routeData; public Camera tourCamera; public string endpoint="http://127.0.0.1:8765/analyse";
  public bool autoStart=true,externalClock; public int captureWidth=640,captureHeight=360;
  public TourPlan Plan {get;private set;} public bool Active {get;private set;}
  public bool Complete {get;private set;} public bool Blocked {get;private set;}
  public bool Waiting {get;private set;} public bool Paused {get;private set;}
  public int Leg {get;private set;} public float Elapsed {get;private set;}
  public string Status {get;private set;}="준비";
  public string CurrentPipe {get;private set;}="";
  public string PendingPipe {get;private set;}="";
  public readonly List<InspectionFinding> Findings=new List<InspectionFinding>();
  public readonly List<InspectionCapture> Captures=new List<InspectionCapture>();
  public readonly List<InspectionOutcome> Outcomes=new List<InspectionOutcome>();
  public readonly List<string> AnalysisErrors=new List<string>();
  public string SessionDirectory {get;private set;}
  public MAEKTourRecorder Recorder {get;private set;}
  // Harness fast-forward still executes every .1 s movement/collision step; never skips a leg.
  [NonSerialized] public int verificationStepsPerUpdate=1;
  public float MaxMovementStep {get;private set;}
  public float MaxRotationStep {get;private set;}
  public int CollisionSteps {get;private set;}
  public int AnalysedPipes=>Outcomes.Where(Usable).Select(o=>o.pipeId).Distinct().Count();
  public static bool Usable(InspectionOutcome o)=>o.visibleTargetSamples>0&&(o.status=="candidate"||o.status=="no_candidate");
  readonly Dictionary<string,List<string>> deferredReasons=new Dictionary<string,List<string>>();
  public int ScheduledImages(string id)=>Plan.points.Count(p=>p.pipeId==id);
  public int RequiredImages(string id) {
   var visit=Plan.visits?.FirstOrDefault(v=>v.pipeId==id);
   if(visit!=null&&visit.requiredCaptures>0)return visit.requiredCaptures;
   int canonical=Plan.access?.Count(a=>a.pipeId==id)??0;
   return canonical>0?canonical:Mathf.Max(1,visit?.captures??ScheduledImages(id));
  }
  public InspectionOutcome[] ValidObservations(string id) {
   var scheduled=new HashSet<string>(Plan.points.Where(p=>p.pipeId==id).Select(p=>p.sampleId));
   return Outcomes.Where(o=>o.pipeId==id&&Usable(o)&&scheduled.Contains(o.sampleId))
    .GroupBy(o=>string.IsNullOrEmpty(o.sampleId)?o.requestId:o.sampleId).Select(g=>g.First()).ToArray();
  }
  public PipeInspectionProgress Coverage(string id) {
   int required=RequiredImages(id),scheduled=ScheduledImages(id),valid=ValidObservations(id).Length;
   var visit=Plan.visits?.FirstOrDefault(v=>v.pipeId==id);var reasons=new List<string>(visit?.accessReasons??Array.Empty<string>());
   foreach(var a in Plan.access??Array.Empty<InspectionAccess>())if(a.pipeId==id&&!a.accessible)reasons.Add(string.IsNullOrEmpty(a.reason)?a.status??"inaccessible":a.reason);
   if(deferredReasons.TryGetValue(id,out var failures))reasons.AddRange(failures);
   foreach(var o in Outcomes.Where(o=>o.pipeId==id&&!Usable(o)))reasons.Add(o.status=="not_visible"?"occluded":o.status=="quality_recheck"?"quality":o.status);
   if(valid<required)reasons.Add(Blocked?"blocked":scheduled==0?"inaccessible":scheduled<required?"missing_access":Complete?"missing_observation":"awaiting_observation");
   return new PipeInspectionProgress{pipeId=id,plannedImages=required,scheduledImages=scheduled,deferredImages=Mathf.Max(0,required-scheduled),analysedImages=valid,
    observationStatus=valid==0?"unobserved":valid<required?"partial":"observed",inspectionStatus=valid>=required?"completed":valid>0?"partial":"deferred",
    accessStatus=scheduled==0?"deferred":scheduled<required?"partial":"accessible",accessReasons=reasons.Where(r=>!string.IsNullOrEmpty(r)).Distinct().ToArray()};
  }
  public void DeferInspection(string id,string reason) {
   if(!deferredReasons.TryGetValue(id,out var reasons))deferredReasons[id]=reasons=new List<string>();
   reasons.Add(reason);Status=id+": 검사보류 · "+reason;WriteProgress();
  }
  string CompletionStatus() {
   var rows=Plan.pipeIds.Select(Coverage).ToArray();
   return "경로 완료 · 검사 완료 "+rows.Count(r=>r.inspectionStatus=="completed")+" · 부분 "+rows.Count(r=>r.inspectionStatus=="partial")+" · 보류 "+rows.Count(r=>r.inspectionStatus=="deferred");
  }
  readonly List<GameObject> pins=new List<GameObject>();
  readonly Dictionary<Behaviour,bool> prior=new Dictionary<Behaviour,bool>();
  float dwell; bool arrived,showResults;Vector2 resultsScroll; int generation; GUIStyle text,button; Font font;
  public void Initialize() {
   if(Plan!=null)return;
   Plan=JsonUtility.FromJson<TourPlan>(routeData.text);
   if(Plan==null||Plan.points==null||Plan.points.Length<1)throw new Exception("Invalid tour route");
   if(Plan.pipeIds==null)Plan.pipeIds=(Plan.visits?.Select(v=>v.pipeId)??Plan.points.Where(p=>!string.IsNullOrEmpty(p.pipeId)).Select(p=>p.pipeId)).Distinct().ToArray();
   if(Plan.visits==null)Plan.visits=Plan.pipeIds.Select(id=>new PipeVisit{pipeId=id,captures=ScheduledImages(id)}).ToArray();
   Plan.bodyRadius=Mathf.Max(.24f,Plan.bodyRadius);Plan.clearanceMargin=Mathf.Max(.10f,Plan.clearanceMargin);
   Plan.radius=Mathf.Max(Plan.radius,Plan.bodyRadius+Plan.clearanceMargin);
   if(Plan.requiredCaptures<=0)Plan.requiredCaptures=Plan.pipeIds.Sum(RequiredImages);
   Recorder=GetComponent<MAEKTourRecorder>();
  }
  public void SetRoute(TextAsset next){if(Active)throw new InvalidOperationException("End the active tour before changing catalogue");routeData=next;Plan=null;Initialize();}
  void Start(){Initialize();if(autoStart)Begin();}
  public static string Hash(byte[] bytes) {
   using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-","").ToLowerInvariant();
  }
  public void Begin(string output=null) {
   GetComponent<MAEKInspectionScenarios>()?.BeforeTourBegin(routeData);
   Initialize();if(Active)End();generation++;StopAllCoroutines();
   var cfd=FindFirstObjectByType<MAEKCFDPlayback>();if(cfd&&cfd.ActiveView)cfd.SetView(false);
   var drone=FindFirstObjectByType<MAEKDroneInspection>();if(drone)drone.EndInspection();
   prior.Clear();
   foreach(var b in FindObjectsByType<Behaviour>(FindObjectsSortMode.None))
    if(b is Camera||b is MAEKDroneInspection||b is MAEKWalkthrough||b is MAEKPipeServices||b is MAEKCFDPlayback) {
     prior[b]=b.enabled;b.enabled=false;
    }
   var services=FindFirstObjectByType<MAEKPipeServices>();if(services){services.Initialize();services.SetOverlay(false);}
   foreach(var p in pins)if(p){DestroyImmediate(p.GetComponent<Renderer>().sharedMaterial);DestroyImmediate(p);}pins.Clear();Findings.Clear();Captures.Clear();Outcomes.Clear();AnalysisErrors.Clear();deferredReasons.Clear();
   SessionDirectory=output??Path.Combine(Application.persistentDataPath,"MAEK-recordings",DateTime.Now.ToString("yyyyMMdd-HHmmss-fff"));
   Directory.CreateDirectory(SessionDirectory);
   Leg=1;Elapsed=0;dwell=0;arrived=false;Blocked=false;Complete=false;Waiting=false;Paused=false;
   CurrentPipe="";PendingPipe="";Active=true;
   MaxMovementStep=0;MaxRotationStep=0;CollisionSteps=0;
   tourCamera.enabled=true;tourCamera.aspect=16f/9;
   tourCamera.transform.SetPositionAndRotation(Plan.points[0].position,Quaternion.LookRotation(Plan.points[0].target-Plan.points[0].position));
   Complete=Plan.points.Length==1;Status=Complete?CompletionStatus():"제철소 전경에서 검사 구역으로 접근";Cursor.lockState=CursorLockMode.None;WriteProgress();
  }
  public void End() {
   if(Recorder&&Recorder.Recording)Recorder.StopRecording();
   generation++;StopAllCoroutines();Waiting=false;Active=false;
   foreach(var p in prior)if(p.Key)p.Key.enabled=p.Value;
   prior.Clear();
  }
  public void SetPaused(bool paused){if(Active)Paused=paused;}
  public void HideResults(){showResults=false;}
  void OnDisable(){if(Active)End();}
  void Update() {
   if(externalClock)return;
   if(Input.GetKeyDown(KeyCode.T)){if(Active)End();else Begin();}
   if(!Active)return;
   Physics.SyncTransforms();
   if(Input.GetKeyDown(KeyCode.Space))Paused=!Paused;
   if(Input.GetKeyDown(KeyCode.R)){if(Recorder.Recording)Recorder.StopRecording();else Recorder.StartRecording(this);}
   int steps=Recorder&&Recorder.Recording?1:Mathf.Clamp(verificationStepsPerUpdate,1,200);
   for(int i=0;i<steps&&!Waiting&&!Complete&&!Blocked&&!Paused&&PendingPipe=="";i++)
    Advance(Recorder&&Recorder.Recording?1f/Recorder.fps:steps>1?.1f:Time.deltaTime);
   if(PendingPipe!=""&&!Waiting){string id=PendingPipe;PendingPipe="";StartCoroutine(Analyse(id));}
  }
  public bool SegmentClear(Vector3 a,Vector3 b) {
   if(Physics.CheckSphere(a,Plan.radius,1<<8,QueryTriggerInteraction.Ignore)||Physics.CheckSphere(b,Plan.radius,1<<8,QueryTriggerInteraction.Ignore))return false;
   var d=b-a;return d.magnitude<1e-5f||!Physics.SphereCast(a,Plan.radius,d.normalized,out var hit,d.magnitude,1<<8,QueryTriggerInteraction.Ignore);
  }
  public void Advance(float dt) {
   if(!Active||Complete||Blocked||Waiting||Paused||PendingPipe!="")return;
   dt=Mathf.Clamp(dt,0,.1f);Elapsed+=dt;
   var point=Plan.points[Leg];
   if(arrived){dwell+=dt;if(dwell<point.dwell)return;Leg++;arrived=false;dwell=0;
    if(Leg>=Plan.points.Length){Complete=true;Status=CompletionStatus();WriteProgress();return;}point=Plan.points[Leg];}
   var old=tourCamera.transform.position;var next=Vector3.MoveTowards(old,point.position,point.speed*dt);
   CollisionSteps++;
   if(!SegmentClear(old,next)){Blocked=true;Status="장애물 감지: 이동 중지 · 미관측 구간 검사보류";WriteProgress();return;}
   var oldRotation=tourCamera.transform.rotation;
   tourCamera.transform.position=next;var direction=point.target-next;
   if(direction.sqrMagnitude>.001f)tourCamera.transform.rotation=Quaternion.RotateTowards(tourCamera.transform.rotation,Quaternion.LookRotation(direction),60*dt);
   MaxMovementStep=Mathf.Max(MaxMovementStep,Vector3.Distance(old,next));
   MaxRotationStep=Mathf.Max(MaxRotationStep,Quaternion.Angle(oldRotation,tourCamera.transform.rotation));
   if(Vector3.Distance(next,point.position)<.001f){
    // Settle orientation smoothly before capturing; no camera teleport/cut.
    if(Quaternion.Angle(tourCamera.transform.rotation,Quaternion.LookRotation(direction))>.08f)return;
    arrived=true;dwell=0;
    if(!string.IsNullOrEmpty(point.pipeId)){CurrentPipe=point.pipeId;PendingPipe=point.pipeId;Status="배관 촬영: "+CurrentPipe;}
   }
  }
  public byte[] CapturePixels(int width,int height) {
   var scenario=GetComponent<MAEKInspectionScenarios>();if(scenario&&!scenario.CameraAvailable)throw new IOException("가상 카메라 영상 중단 · 촬영 미완료");
   var rt=RenderTexture.GetTemporary(width,height,24,RenderTextureFormat.ARGB32);
   var old=RenderTexture.active;var target=tourCamera.targetTexture;float aspect=tourCamera.aspect;
   var image=new Texture2D(width,height,TextureFormat.RGB24,false);
   // Analysis must not see its own previous orange result pins.
   foreach(var p in pins)p.SetActive(false);
   try {tourCamera.aspect=(float)width/height;tourCamera.targetTexture=rt;tourCamera.Render();RenderTexture.active=rt;
    image.ReadPixels(new Rect(0,0,width,height),0,0);image.Apply();
    if(scenario&&scenario.Exposure<1){var pixels=image.GetPixels32();for(int i=0;i<pixels.Length;i++){pixels[i].r=(byte)(pixels[i].r*scenario.Exposure);pixels[i].g=(byte)(pixels[i].g*scenario.Exposure);pixels[i].b=(byte)(pixels[i].b*scenario.Exposure);}image.SetPixels32(pixels);image.Apply();}
    return image.EncodeToPNG();
   } finally {tourCamera.targetTexture=target;tourCamera.aspect=aspect;RenderTexture.active=old;
    RenderTexture.ReleaseTemporary(rt);DestroyImmediate(image);foreach(var p in pins)p.SetActive(true);}
  }
  public RGBRequest MakeCapture(string pipeId,out InspectionCapture context) {
   var png=CapturePixels(captureWidth,captureHeight);
   context=new InspectionCapture{requestId=Guid.NewGuid().ToString("N"),pipeId=pipeId,
    imageSha256=Hash(png),position=tourCamera.transform.position,rotation=tourCamera.transform.rotation,sampleId=Plan.points[Leg].sampleId,
    fieldOfView=tourCamera.fieldOfView,aspect=(float)captureWidth/captureHeight,width=captureWidth,height=captureHeight};
   for(int y=-2;y<=2;y++)for(int x=-2;x<=2;x++)
    if(Physics.Raycast(context.Ray(.5f+x*.012f,.5f+y*.012f),out var hit,250,1<<8,QueryTriggerInteraction.Ignore)&&MAEKSupplementaryCircuits.TargetId(hit.collider)==pipeId)context.visibleTargetSamples++;
   Captures.Add(context);File.WriteAllBytes(Path.Combine(SessionDirectory,context.requestId+".png"),png);
   File.WriteAllText(Path.Combine(SessionDirectory,context.requestId+".capture.json"),JsonUtility.ToJson(context,true));
   var scenario=GetComponent<MAEKInspectionScenarios>();
   return new RGBRequest{requestId=context.requestId,imageBase64=Convert.ToBase64String(png),sessionId=Path.GetFileName(SessionDirectory),pipeId=pipeId,sampleId=context.sampleId,scenarioId=scenario?.Current?.id??"catalogue",scenarioRunId=scenario?.Current!=null?scenario.RunId:Path.GetFileName(SessionDirectory)};
  }
  IEnumerator Analyse(string pipeId) {
   Waiting=true;int token=generation;Status="RGB 분석 중: "+pipeId;
   RGBRequest request;InspectionCapture context;
   try {request=MakeCapture(pipeId,out context);}catch(Exception e){Failure(e.Message);yield break;}
   using(var web=UnityWebRequest.Post(endpoint,JsonUtility.ToJson(request),"application/json")) {
    web.timeout=20;yield return web.SendWebRequest();
    if(token!=generation)yield break;
    if(web.result!=UnityWebRequest.Result.Success)Failure("분석 서버 연결 실패: "+web.error);
    else {try{ApplyResult(context,web.downloadHandler.text);}catch(Exception e){Failure(e.Message);}}
   }
   Waiting=false;
  }
  public void Failure(string reason){Waiting=false;AnalysisErrors.Add(reason);Status="검사보류: "+reason;if(!string.IsNullOrEmpty(CurrentPipe))DeferInspection(CurrentPipe,reason);else WriteProgress();}
  public void ConsumePendingForVerification(){PendingPipe="";}
  public int ApplyResult(InspectionCapture capture,string json) {
   var result=JsonUtility.FromJson<RGBResult>(json);
   if(result==null||result.version!=1||(result.status!="ok"&&!(result.status=="low_light"&&result.quality!=null&&!result.quality.canInfer))||result.requestId!=capture.requestId||
     result.imageSha256!=capture.imageSha256||result.width!=capture.width||result.height!=capture.height||result.components==null)
    throw new Exception("Analysis response provenance/dimensions mismatch");
   if(Outcomes.Any(o=>o.requestId==capture.requestId))throw new Exception("Duplicate analysis response");
   int count=0;bool mappedCandidate=false;bool canInfer=result.quality==null||result.quality.canInfer;
   foreach(var component in canInfer&&capture.visibleTargetSamples>0?result.components:Array.Empty<RGBComponent>()) {
    if(component.samples==null)continue;
    var hits=new List<RaycastHit>();
    foreach(var s in component.samples) {
     if(!float.IsFinite(s.u)||!float.IsFinite(s.v)||s.u<0||s.u>1||s.v<0||s.v>1)continue;
     if(Physics.Raycast(capture.Ray(s.u,s.v),out var hit,250,1<<8,QueryTriggerInteraction.Ignore)) {
      if(MAEKSupplementaryCircuits.TargetId(hit.collider)==capture.pipeId)hits.Add(hit);
     }
    }
    if(hits.Count<2)continue; // Reject background/other-pipe detections and isolated mapping.
    mappedCandidate=true;
    var center=hits[hits.Count/2];
    if(Findings.Any(f=>f.pipeId==capture.pipeId&&Vector3.Distance(f.position,center.point)<.35f))continue;
    var finding=new InspectionFinding{pipeId=capture.pipeId,requestId=capture.requestId,
     imageSha256=capture.imageSha256,kind=component.kind,model=result.model,position=center.point,
     normal=center.normal,pixelCount=component.pixelCount,mappedSamples=hits.Count};
    var process=GetComponent<MAEKProcessContext>();if(process&&process.ForPipe(capture.pipeId)!=null)finding.recommendation=process.ForPipe(capture.pipeId).followUp+" · 작업 허가 미판정";
    Findings.Add(finding);count++;
    var pin=GameObject.CreatePrimitive(PrimitiveType.Sphere);pin.name="MAEK RGB evidence "+capture.pipeId;
    pin.layer=2;DestroyImmediate(pin.GetComponent<Collider>());pin.transform.position=center.point+center.normal*.035f;
    pin.transform.localScale=Vector3.one*.08f;var m=new Material(Shader.Find("Unlit/Color"));m.color=new Color(1,.35f,.05f);
    pin.GetComponent<Renderer>().sharedMaterial=m;pins.Add(pin);
   }
   File.WriteAllText(Path.Combine(SessionDirectory,capture.requestId+".analysis.json"),json);
   File.WriteAllText(Path.Combine(SessionDirectory,"findings.json"),JsonUtility.ToJson(new FindingSet{findings=Findings.ToArray()},true));
   var outcome=new InspectionOutcome{requestId=capture.requestId,pipeId=capture.pipeId,sampleId=capture.sampleId,
    visibleTargetSamples=capture.visibleTargetSamples,newFindings=count,status=capture.visibleTargetSamples==0?"not_visible":!canInfer?"quality_recheck":mappedCandidate?"candidate":"no_candidate"};
   Outcomes.Add(outcome);WriteProgress();
   Status=capture.visibleTargetSamples==0?capture.pipeId+": 대상 배관 가림 · 검사보류":!canInfer?capture.pipeId+": 영상 품질 부족 · 검사보류 · 재촬영 필요":mappedCandidate?capture.pipeId+": 부식 의심 위치 표시 · 후속 검사 적용성 검토 · 작업 허가 미판정":capture.pipeId+": RGB 후보 없음 · 건전성 보장 아님";
   return count;
  }
  [Serializable] class FindingSet {public InspectionFinding[] findings;}
  [Serializable] class Progress {public string[] plannedPipes,analysedPipes,missingPipes;public bool routeComplete;public int expectedCaptures,requiredCaptures,captures;public PipeInspectionProgress[] pipes;public string[] unobservedPipes;public InspectionAccess[] unobservedCaptures;public InspectionOutcome[] outcomes;public string[] errors;}
  InspectionAccess[] UnobservedCaptures() {
   var canonical=Plan.access??Plan.points.Where(p=>!string.IsNullOrEmpty(p.pipeId)).Select(p=>new InspectionAccess{pipeId=p.pipeId,sampleId=p.sampleId,sourceIndex=p.sourceIndex,position=p.position,target=p.target,accessible=true}).ToArray();
   var observed=Plan.pipeIds.ToDictionary(id=>id,id=>new HashSet<string>(ValidObservations(id).Select(o=>o.sampleId)));
   var coverage=Plan.pipeIds.ToDictionary(id=>id,Coverage);
   return canonical.Where(a=>!observed[a.pipeId].Contains(a.sampleId)).Select(a=>new InspectionAccess{
    pipeId=a.pipeId,sampleId=a.sampleId,sourceIndex=a.sourceIndex,position=a.position,target=a.target,accessible=a.accessible,
    status=a.accessible?"unobserved":a.status,reason=string.Join("; ",coverage[a.pipeId].accessReasons.Concat(string.IsNullOrEmpty(a.reason)?Array.Empty<string>():new[]{a.reason}).Distinct())}).ToArray();
  }
  public void WriteProgress() {
   if(string.IsNullOrEmpty(SessionDirectory)||Plan==null)return;
   var ids=Plan.pipeIds??Plan.points.Where(p=>p.pipeId!="").Select(p=>p.pipeId).Distinct().ToArray();
   var rows=ids.Select(Coverage).ToArray();
   var done=Outcomes.Where(Usable).Select(o=>o.pipeId).Distinct().OrderBy(x=>x).ToArray();
   File.WriteAllText(Path.Combine(SessionDirectory,"inspection_progress.json"),JsonUtility.ToJson(new Progress{plannedPipes=ids,analysedPipes=done,missingPipes=rows.Where(r=>r.inspectionStatus!="completed").Select(r=>r.pipeId).ToArray(),unobservedPipes=rows.Where(r=>r.observationStatus=="unobserved").Select(r=>r.pipeId).ToArray(),pipes=rows,unobservedCaptures=UnobservedCaptures(),routeComplete=Complete,requiredCaptures=Plan.requiredCaptures,expectedCaptures=Plan.expectedCaptures,captures=Captures.Count,outcomes=Outcomes.ToArray(),errors=AnalysisErrors.ToArray()},true));
   var process=GetComponent<MAEKProcessContext>();if(process)process.WriteFollowUps(SessionDirectory);
  }
  public VideoPin[] VisiblePins(Camera camera) {
   var visible=new List<VideoPin>();
   foreach(var f in Findings) {
    var p=camera.WorldToViewportPoint(f.position+f.normal*.05f);
    var d=f.position-camera.transform.position;
    bool occluded=Physics.Raycast(camera.transform.position,d.normalized,out var hit,d.magnitude-.08f,1<<8,QueryTriggerInteraction.Ignore);
    if(!occluded&&p.z>0&&p.x>0&&p.x<1&&p.y>0&&p.y<1)visible.Add(new VideoPin{pipeId=f.pipeId,label="부식 후보 · 후속 검사 검토",u=p.x,v=1-p.y});
   }
   return visible.ToArray();
  }
  public TourVideoFrame VideoFrame(int frame,float time) {
   return new TourVideoFrame{frame=frame,time=time,position=tourCamera.transform.position,
    stage=Complete?"경로 완료":CurrentPipe==""?"전경 → 검사 구역":Waiting?"분석 중":"배관 검사",pipeId=CurrentPipe,status=Status,pins=VisiblePins(tourCamera),
    processContext=GetComponent<MAEKProcessContext>()?.Caption(CurrentPipe)??"",numericalScope=GetComponent<MAEKSupplementaryCircuits>()?.Selected==true?GetComponent<MAEKSupplementaryCircuits>().Data.flowBasis:GetComponent<MAEKProcessContext>()?.Data?.numericalScope??"가정 조건 계산",workerContext="가상 배관 · 실제 사고 위치 아님 · 작업 허가 미판정"};
  }
  void OnGUI() {
   if(text==null){font=Font.CreateDynamicFontFromOSFont(new[]{"Malgun Gothic","Arial"},17);text=new GUIStyle(GUI.skin.label){font=font,fontSize=17,wordWrap=true};button=new GUIStyle(GUI.skin.button){font=font,fontSize=15};}
   if(!Active){if(GUI.Button(new Rect(12,125,270,34),"T: MAEK 연속 검사 시연 시작",button))Begin();return;}
   GUI.Box(new Rect(12,12,Mathf.Min(740,Screen.width-24),178),"");
   GUI.Label(new Rect(25,22,700,28),"MAEK | 유효 관측 배관 "+AnalysedPipes+" / "+(Plan.pipeIds?.Length??0)+" · 촬영 "+Captures.Count+" / "+Plan.requiredCaptures+" (예약 "+Plan.expectedCaptures+")",text);
   GUI.Label(new Rect(25,54,690,48),Status,text);
   GUI.Label(new Rect(25,103,690,28),"합성 장면 · RGB 부식 규칙 기준선 · 균열 발생 예측 아님",text);
   if(GUI.Button(new Rect(25,143,145,32),Paused?"재생 (Space)":"일시 정지 (Space)",button))Paused=!Paused;
   if(GUI.Button(new Rect(180,143,170,32),Recorder.Recording?"녹화 종료 (R)":"영상 프레임 녹화 (R)",button)){if(Recorder.Recording)Recorder.StopRecording();else Recorder.StartRecording(this);}
   if(GUI.Button(new Rect(360,143,125,32),"종료 (T)",button))End();
   if(GUI.Button(new Rect(495,143,140,32),"처음부터 다시",button))Begin();
   if(GUI.Button(new Rect(645,143,85,32),"결과표",button))showResults=!showResults;
   if(showResults){GUI.Box(new Rect(Screen.width-340,200,328,Screen.height-250),"");GUILayout.BeginArea(new Rect(Screen.width-330,210,308,Screen.height-270));resultsScroll=GUILayout.BeginScrollView(resultsScroll);
    var process=GetComponent<MAEKProcessContext>();if(Plan.pipeIds.Length==247&&process&&GUILayout.Button(process.CoreResultsOnly?"주요 검사 138개 / 전체 247개로 전환":"전체 247개 / 주요 검사만 보기",button))process.CoreResultsOnly=!process.CoreResultsOnly;
    foreach(var id in Plan.pipeIds){if(Plan.pipeIds.Length==247&&process&&process.CoreResultsOnly&&!process.IsCore(id))continue;
     var row=Coverage(id);bool candidate=ValidObservations(id).Any(o=>o.status=="candidate");
     string state=row.scheduledImages==0?"미관측·검사보류":row.inspectionStatus=="deferred"?"미관측·검사보류":row.inspectionStatus=="partial"?"부분 관측·검사보류":candidate?"부식 의심":"RGB 후보 없음";
     if(candidate&&row.inspectionStatus!="completed")state="부식 의심·검사보류";
     GUILayout.Label(id+"  "+row.analysedImages+"/"+row.plannedImages+" (예약 "+row.scheduledImages+")  "+state+(process?"\n"+MAEKProcessContext.RoleLabel(process.ForPipe(id)?.role):""),text);
    }GUILayout.EndScrollView();GUILayout.EndArea();}
   var display=GetComponent<MAEKVirtualDrone>()?.DisplayCamera??tourCamera;
   foreach(var p in VisiblePins(display)){float x=p.u*Screen.width,y=p.v*Screen.height;GUI.Box(new Rect(x-5,y-5,10,10),"");GUI.Label(new Rect(Mathf.Clamp(x+12,12,Screen.width-300),Mathf.Clamp(y+10,200,Screen.height-70),285,65),p.pipeId+"\n"+p.label,text);}
   if(Recorder.Recording)GUI.Label(new Rect(25,Screen.height-40,900,30),"REC · "+Recorder.FrameCount+" frames · "+Recorder.OutputDirectory,text);
  }
 }
}
