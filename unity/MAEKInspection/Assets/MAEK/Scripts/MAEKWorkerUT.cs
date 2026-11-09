using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Networking;
namespace MAEK {
 [DefaultExecutionOrder(450)]
 public sealed class MAEKWorkerUT : MonoBehaviour {
  public enum Stage { Waiting, ReferenceCheck, Walking, SurfacePreparation, Couplant, Contact, Analysing, Complete, Deferred, Interrupted }
  [Serializable] public class Request {public string requestId,pipeId;public int sample;}
  [Serializable] public class Result {
   public string requestId,pipeId,sampleId,source,sourceSha256,model,workPermissionStatus;
   public int sample,nAvg;public bool synthetic,pitAlarm,wallValid;
   public float pitScore,threshold,mainWallMm,nominalWallMm,observedTempC;public float[] wave;
  }
  public Stage State {get;private set;}=Stage.Waiting;
  public string Status {get;private set;}="검사 준비 중";
  public string PipeId=>"BF1-Q005";
  public bool Ready {get;private set;}
  public Result Measurement {get;private set;}
  public bool ExternalClock;
  public string Endpoint="http://127.0.0.1:8766/ut";
  public string LogPath {get;private set;}
  public Vector3 ContactPoint=>contact;
  public MAEKMaintenanceInspector Actor {get;private set;}
  public bool SimulatePoorContact;
  public int Sample;
  public GameObject devicePrefab;
  MAEKSafetyDemo safety;MAEKInspectorVisual visual;CapsuleCollider body;Collider surface;
  Vector3 waiting,station,contact,normal;MAEKUTEquipment kit;
  public bool ReferenceChecked {get;private set;}
  public bool SurfacePrepared {get;private set;}
  public bool CouplantApplied {get;private set;}
  public bool SimulateReferenceFailure;
  public float StageProgress=>Mathf.Clamp01(dwell/StageDuration);
  float StageDuration=>State==Stage.ReferenceCheck?3:State==Stage.SurfacePreparation?2.5f:State==Stage.Couplant?2:2.5f;
  Camera view;bool showView,initialized;int generation;float dwell,speed;
  readonly List<Vector3> walkRoute=new List<Vector3>();int walkIndex;string pending="";Vector2 scroll;Font font;GUIStyle label,button;readonly List<Material> materials=new List<Material>();
  public int Generation=>generation;public string PendingRequestId=>pending;
  void Start(){Initialize();}
  public bool Busy=>State==Stage.ReferenceCheck||State==Stage.Walking||State==Stage.SurfacePreparation||State==Stage.Couplant||State==Stage.Contact||State==Stage.Analysing;
  public void Initialize() {
   if(initialized)return;initialized=true;safety=GetComponent<MAEKSafetyDemo>();safety.Initialize();
   LogPath=Path.Combine(Application.persistentDataPath,"MAEK-worker-ut",DateTime.Now.ToString("yyyyMMdd-HHmmss-fff"),"events.jsonl");Directory.CreateDirectory(Path.GetDirectoryName(LogPath));
   Endpoint=Environment.GetEnvironmentVariable("MAEK_UT_ENDPOINT")??Endpoint;
   var args=Environment.GetCommandLineArgs();int arg=Array.IndexOf(args,"-maek-ut-endpoint");if(arg>=0&&arg+1<args.Length)Endpoint=args[arg+1];
   Actor=MAEKMaintenanceInspector.TrySpawn(safety.Tour);
   if(!Actor){State=Stage.Deferred;Status="작업자 배치 불가 · 검사 보류";return;}
   Actor.enabled=false;visual=Actor.GetComponent<MAEKInspectorVisual>();visual.Initialize();body=Actor.GetComponent<CapsuleCollider>();waiting=Actor.transform.position;
   Ready=FindStation();if(!Ready){State=Stage.Deferred;Status="기존 배관까지 작업자 접근/접촉 경로 미확보 · 보류";Record("DEFERRED");return;}
   kit=new MAEKUTEquipment();
   var camera=new GameObject("UT worker presentation camera");view=camera.AddComponent<Camera>();view.depth=50;view.enabled=false;view.fieldOfView=45;view.nearClipPlane=.05f;
   Status="검사 준비 · 기준 블록 확인부터 시작합니다";Record("READY");UpdateVisual(0);
  }
  bool FindStation() {
   int rayHits=0,groundHits=0,routeHits=0;body.enabled=false;try {
    var colliders=FindObjectsByType<Collider>(FindObjectsSortMode.None).Where(c=>c.enabled&&c.gameObject.layer==8&&c.GetComponentInParent<MAEKPipeService>()?.lineId==PipeId).OrderBy(c=>Vector3.Distance(c.bounds.center,waiting));
    Debug.Log("UT_GEOMETRY "+string.Join(" | ",colliders.Select(c=>c.name+" "+c.bounds.ToString())));
    foreach(var target in colliders)for(int i=0;i<16;i++) {
     var direction=Quaternion.Euler(0,i*22.5f,0)*Vector3.forward;
     var origin=target.bounds.center+direction*(target.bounds.extents.magnitude+1);origin.y=Mathf.Clamp(target.bounds.center.y,waiting.y+.8f,waiting.y+1.2f);
     if(!Physics.Raycast(origin,-direction,out var hit,10,1<<8,QueryTriggerInteraction.Ignore)||hit.collider!=target)continue;
     rayHits++;if(rayHits<4)Debug.Log("UT_HIT "+hit.point+" n="+hit.normal);if(Mathf.Abs(hit.normal.y)>.5f)continue;
     var candidate=hit.point+hit.normal*.72f;
     if(!Physics.Raycast(new Vector3(candidate.x,waiting.y+.4f,candidate.z),Vector3.down,out var ground,.8f,1<<8,QueryTriggerInteraction.Ignore)||ground.normal.y<.95f)continue;
     groundHits++;candidate.y=ground.point.y+.035f;
     if(Vector3.Distance(candidate,waiting)>12 || Mathf.Abs(hit.point.y-(candidate.y+1.05f))>.25f)continue;
     if(!FindWalkRoute(waiting,candidate))continue;routeHits++;
     if(!Physics.Raycast(candidate+Vector3.up*1.05f,hit.point-(candidate+Vector3.up*1.05f),out var front,1.2f,1<<8,QueryTriggerInteraction.Ignore)||front.collider!=target)continue;
     station=candidate;contact=front.point;normal=front.normal;surface=target;return true;
    }
   }finally{body.enabled=true;Physics.SyncTransforms();Debug.Log("UT_SEARCH ray="+rayHits+" ground="+groundHits+" route="+routeHits);}return false;
  }
  bool WalkClear(Vector3 from,Vector3 to) {
   bool enabled=body.enabled;body.enabled=false;Physics.SyncTransforms();try {
    var delta=to-from;int count=Mathf.Max(1,Mathf.CeilToInt(delta.magnitude/.2f));
    for(int i=0;i<=count;i++){var p=Vector3.Lerp(from,to,(float)i/count);
     if(!Physics.Raycast(p+Vector3.up*.4f,Vector3.down,out var floor,.8f,1<<8,QueryTriggerInteraction.Ignore)||floor.normal.y<.95f||Mathf.Abs(floor.point.y-(p.y-.035f))>.15f)return false;
     if(Physics.CheckCapsule(p+Vector3.up*.51f,p+Vector3.up*1.29f,.5f,1<<8,QueryTriggerInteraction.Ignore))return false;
    }
    return !Physics.CapsuleCast(from+Vector3.up*.51f,from+Vector3.up*1.29f,.5f,delta.normalized,delta.magnitude,1<<8,QueryTriggerInteraction.Ignore);
   }finally{body.enabled=enabled;Physics.SyncTransforms();}
  }
  bool FindWalkRoute(Vector3 start,Vector3 goal) {
   walkRoute.Clear();if(WalkClear(start,goal)){walkRoute.Add(goal);return true;}
   bool enabled=body.enabled;body.enabled=false;Physics.SyncTransforms();
   try {
    const float step=.75f;var zero=Vector2Int.zero;var queue=new Queue<Vector2Int>();var parents=new Dictionary<Vector2Int,Vector2Int>();parents[zero]=zero;queue.Enqueue(zero);int budget=0;
    Func<Vector2Int,Vector3> pos=k=>start+new Vector3(k.x*step,0,k.y*step);
    while(queue.Count>0&&budget++<1800) {
     var key=queue.Dequeue();var p=pos(key);
     if(Vector3.Distance(p,goal)<1.3f&&WalkClear(p,goal)) {
      var reverse=new List<Vector3>{goal};while(key!=zero){reverse.Add(pos(key));key=parents[key];}reverse.Reverse();walkRoute.AddRange(reverse);return true;
     }
     foreach(var d in new[]{Vector2Int.right,Vector2Int.left,Vector2Int.up,Vector2Int.down}) {
      var next=key+d;if(parents.ContainsKey(next)||Mathf.Abs(next.x)>20||Mathf.Abs(next.y)>20||!WalkClear(p,pos(next)))continue;
      parents[next]=key;queue.Enqueue(next);
     }
    }
   }finally{body.enabled=enabled;Physics.SyncTransforms();}return false;
  }
  public void Begin() {
   Initialize();if(!Ready||Busy||safety.AccidentActive||!safety.Grounded||safety.Gate.Latched){Status="검사 차단 · 지상 시연 승인/접근 경로 확인 필요";Record("START_DENIED");return;}
   if(!FindWalkRoute(Actor.transform.position,station)){Status="작업자 이동 경로 차단 · 검사 보류";State=Stage.Deferred;return;}
   walkIndex=0;generation++;Measurement=null;pending="";ReferenceChecked=SurfacePrepared=CouplantApplied=false;showView=true;
   Enter(Stage.ReferenceCheck,"기준 블록에 탐촉자 접촉 · 절차 모의 확인 (실제 교정 아님)","REFERENCE_START");
  }
  public void Cancel() {generation++;StopAllCoroutines();pending="";Measurement=null;State=Stage.Interrupted;Status="UT 중단 · 결과 확정 차단 · 현장 확인 필요";Record("CANCEL");}
  public void Tick(float dt) {
   Initialize();if(!Ready)return;dt=Mathf.Clamp(dt,0,.1f);speed=0;
   if(Busy&&(safety.AccidentActive||!safety.Grounded||safety.Gate.Latched)){Cancel();}
   if(State==Stage.ReferenceCheck){
    dwell+=dt;
    if(dwell>=StageDuration){
     if(SimulateReferenceFailure){Enter(Stage.Deferred,"기준 확인 불량 시연 · 검사 진행 차단","REFERENCE_FAILED");}
     else {ReferenceChecked=true;Enter(Stage.Walking,"기준 확인 절차 완료 · 검사 지점으로 이동","WALK");}
    }
   }
   if(State==Stage.Walking) {
    var old=Actor.transform.position;var next=Vector3.MoveTowards(old,walkRoute[walkIndex],1.2f*dt);
    if(!WalkClear(old,next)){Cancel();Status="새 장애물로 이동 차단 · 검사 보류";return;}
    Actor.transform.position=next;speed=1.2f;if((walkRoute[walkIndex]-next).sqrMagnitude<.0001f&&walkIndex<walkRoute.Count-1)walkIndex++;if((station-next).sqrMagnitude<.0001f){Actor.transform.rotation=Quaternion.LookRotation(Vector3.ProjectOnPlane(-normal,Vector3.up),Vector3.up);Enter(Stage.SurfacePreparation,"접촉 부위 닦기 · 표면 준비 절차 시연","SURFACE_PREPARATION");}
    else if((next-old).sqrMagnitude>.000001f)Actor.transform.rotation=Quaternion.LookRotation(next-old,Vector3.up);
   }
   if(State==Stage.SurfacePreparation||State==Stage.Couplant){
    if(!AtContact()){Enter(Stage.Deferred,"작업 위치 이탈 · 검사 보류","CONTACT_LOST");UpdateVisual(dt);return;}
    dwell+=dt;
    if(dwell>=StageDuration){
     if(State==Stage.SurfacePreparation){SurfacePrepared=true;Enter(Stage.Couplant,"접촉매질 젤 도포 · 초음파 전달을 위한 준비 시연","COUPLANT");}
     else {CouplantApplied=true;Enter(Stage.Contact,"탐촉자 수직 접촉 · 신호 안정 확인 시연","CONTACT");}
    }
   }
   if(State==Stage.Contact) {
    if(!ReferenceChecked||!SurfacePrepared||!CouplantApplied||!AtContact()){Enter(Stage.Deferred,"절차/접촉 조건 미충족 · 측정 보류","CONTACT_LOST");UpdateVisual(dt);return;}
    dwell+=dt;
    if(SimulatePoorContact){Status="접촉 불량 · 측정값 생성 안 함";if(dwell>2){State=Stage.Deferred;Record("POOR_CONTACT");} }
    else if(dwell>=StageDuration){pending=Guid.NewGuid().ToString("N");State=Stage.Analysing;Status="신호 확인 절차 완료 · 팀 합성 파형 분석·기록 중";Record("ANALYSE");if(Application.isPlaying)StartCoroutine(Measure(generation));}
   }
   UpdateVisual(dt);
  }
  void Enter(Stage stage,string status,string kind){State=stage;Status=status;dwell=0;Record(kind);}
  bool AtContact(){
   var from=Actor.transform.position+Vector3.up*1.05f;var toward=contact-from;
   return Vector3.Distance(Actor.transform.position,station)<=.04f&&Physics.Raycast(from,toward,out var touch,toward.magnitude+.04f,1<<8,QueryTriggerInteraction.Ignore)&&touch.collider==surface&&Vector3.Distance(touch.point,contact)<=.04f;
  }
  IEnumerator Measure(int token) {
   var id=pending;var payload=JsonUtility.ToJson(new Request{requestId=id,pipeId=PipeId,sample=Sample});
   using(var req=new UnityWebRequest(Endpoint,"POST")){req.uploadHandler=new UploadHandlerRaw(System.Text.Encoding.UTF8.GetBytes(payload));req.downloadHandler=new DownloadHandlerBuffer();req.SetRequestHeader("Content-Type","application/json");req.timeout=20;yield return req.SendWebRequest();
    if(token!=generation||State!=Stage.Analysing)yield break;
    if(req.result!=UnityWebRequest.Result.Success){State=Stage.Deferred;Status="UT 분석 서버 오류 · 미측정/보류: "+req.error;Record("SERVER_ERROR");yield break;}
    Accept(req.downloadHandler.text,id,token);
   }
  }
  public bool Accept(string json,string requestId,int token) {
   if(requestId!=pending||token!=generation||State!=Stage.Analysing||safety.AccidentActive||!safety.Grounded||safety.Gate.Latched)return false;
   Result r;try{r=JsonUtility.FromJson<Result>(json);}catch{Status="잘못된 UT 응답 · 판정 보류";State=Stage.Deferred;return false;}
   if(r==null||r.requestId!=requestId||r.pipeId!=PipeId||r.sample!=Sample||!r.synthetic||r.workPermissionStatus!="not_assessed"||r.sourceSha256!="be4be1f82633378c803ff3112d43738ad89b928778c1ba69033c738a624d1e6d"||r.wave==null||r.wave.Length!=4096||r.wave.Any(v=>float.IsNaN(v)||float.IsInfinity(v))||float.IsNaN(r.pitScore)||r.pitScore<0||r.pitScore>1||r.threshold<0||r.threshold>1||float.IsNaN(r.threshold)||(r.wallValid&&((float.IsNaN(r.mainWallMm)||float.IsInfinity(r.mainWallMm))||r.mainWallMm<=0))) {
    State=Stage.Deferred;Status="UT 응답 정합성 불일치 · 판정 보류";Record("INVALID_RESULT");return false;
   }
   Measurement=r;State=Stage.Complete;Status=r.pitAlarm?"피팅 의심 · 후속 확인 필요":"이번 합성 예제에서 피팅 경보 없음 · 건전성 보장 아님";Record("RESULT");File.WriteAllText(Path.Combine(Path.GetDirectoryName(LogPath),requestId+".json"),json);return true;
  }
  void Update(){if(!ExternalClock)Tick(Time.deltaTime);}
  void UpdateVisual(float dt) {
   if(!visual||kit==null)return;visual.Advance(dt,speed,true,0,false);
   visual.Pda.gameObject.SetActive(false);
   var actor=Actor.transform;bool prep=State==Stage.SurfacePreparation,gel=State==Stage.Couplant;
   bool inspecting=State==Stage.Contact||State==Stage.Analysing;
   bool reference=State==Stage.ReferenceCheck;
   var instrument=actor.TransformPoint(new Vector3(.14f,1.0f,.26f));
   kit.Instrument.SetPositionAndRotation(instrument,actor.rotation*Quaternion.Euler(-18,0,-8));
   kit.Reference.SetPositionAndRotation(kit.Instrument.TransformPoint(new Vector3(0,.17f,0)),kit.Instrument.rotation);
   kit.Reference.gameObject.SetActive(reference);
   Vector3 probeNormal=reference?kit.Reference.up:prep||gel?actor.up:normal;
   var probePosition=reference?kit.Reference.position+probeNormal*.05f:inspecting?contact+normal*.007f:prep||gel?kit.Instrument.TransformPoint(new Vector3(-.13f,0,0)):actor.TransformPoint(new Vector3(-.20f,.89f,.32f));
   kit.Probe.SetPositionAndRotation(probePosition,Quaternion.FromToRotation(Vector3.up,probeNormal));
   var tangent=Vector3.Cross(normal,Vector3.up).normalized;
   var wiping=contact+normal*.04f+tangent*(Mathf.Sin(dwell*9)*.045f);
   kit.Cloth.gameObject.SetActive(prep);kit.Cloth.SetPositionAndRotation(wiping,Quaternion.FromToRotation(Vector3.up,normal));
   kit.Bottle.gameObject.SetActive(gel);kit.Bottle.SetPositionAndRotation(contact+normal*.13f,Quaternion.FromToRotation(Vector3.up,-normal));
   kit.Gel.gameObject.SetActive((CouplantApplied||gel)&&State!=Stage.Interrupted&&State!=Stage.Deferred);
   kit.Gel.SetPositionAndRotation(contact+normal*.004f,Quaternion.FromToRotation(Vector3.up,normal));
   var leftGrip=prep?wiping+normal*.05f:gel?contact+normal*.17f:probePosition+probeNormal*.09f;
   visual.HoldUTAt(kit.Instrument.TransformPoint(new Vector3(.13f,0,0)),leftGrip);
   kit.UpdateCable();
   kit.SetDisplay(State==Stage.Complete&&Measurement!=null?(Measurement.wallValid?Measurement.mainWallMm.ToString("F2")+" mm":"NO WALL")+"\nEXAMPLE":reference?"REF\nDEMO":inspecting?"CONTACT\nCHECK":State==Stage.Analysing?"ANALYSE":"UT\nREADY");
   if(view){view.enabled=false;if(showView){bool enabled=body.enabled;body.enabled=false;Physics.SyncTransforms();try{
    var focus=Actor.transform.position+Vector3.up*1.05f;
    for(int i=0;i<28;i++){float angle=i==0?-55:i==1?55:i==2?-75:i==3?75:(i-4)*15;var direction=Quaternion.Euler(0,angle,0)*Vector3.ProjectOnPlane(normal,Vector3.up).normalized;var position=Actor.transform.position+direction*3+Vector3.up*2.1f;var delta=focus-position;
     if(Physics.CheckSphere(position,.12f,1<<8,QueryTriggerInteraction.Ignore)||Physics.SphereCast(position,.08f,delta.normalized,out _,delta.magnitude,1<<8,QueryTriggerInteraction.Ignore))continue;
     view.transform.position=position;view.transform.LookAt(focus);view.enabled=true;break;
    }
   }finally{body.enabled=enabled;Physics.SyncTransforms();}}}
  }
  [Serializable] class Event {public string utc,stage,status,kind,pipeId;public Vector3 worker;public string workPermissionStatus="not_assessed";public string scope="synthetic example replay, not a measurement of the Unity pipe";}
  void Record(string kind){if(string.IsNullOrEmpty(LogPath))return;File.AppendAllText(LogPath,JsonUtility.ToJson(new Event{utc=DateTime.UtcNow.ToString("o"),stage=State.ToString(),kind=kind,status=Status,pipeId=PipeId,worker=Actor?Actor.transform.position:Vector3.zero})+Environment.NewLine);}
  void OnGUI(){
   if(GetComponent<MAEKThermalDemo>()?.Displaying==true)return;
   if(!initialized)return;if(label==null){font=Font.CreateDynamicFontFromOSFont(new[]{"Malgun Gothic","Arial"},15);label=new GUIStyle(GUI.skin.label){font=font,fontSize=15,wordWrap=true};button=new GUIStyle(GUI.skin.button){font=font,fontSize=15};}
   GUI.depth=-110;var box=new Rect(12,140,Mathf.Min(480,Screen.width*.43f),Mathf.Max(180,Screen.height-400));var color=GUI.color;GUI.color=new Color(.04f,.08f,.12f,1);GUI.DrawTexture(box,Texture2D.whiteTexture);GUI.color=color;GUILayout.BeginArea(new Rect(box.x+10,box.y+8,box.width-20,box.height-16));scroll=GUILayout.BeginScrollView(scroll);
   GUILayout.Label("작업자 수직 UT · 피팅 MLP 예제 재생",label);GUILayout.Label(PipeId+" 위치에서 팀 합성 예제 시연 · 현장 측정 아님",label);GUILayout.Label(Status,label);
   if(GUILayout.Button(showView?"작업자 시점 끄기":"작업자 검사 시점 보기",button))showView=!showView;
   GUI.enabled=!Busy;if(GUILayout.Button("기준 확인 → 표면 준비 → 젤 → UT 검사",button))Begin();
   GUILayout.BeginHorizontal();if(GUILayout.Button("이전 예제",button))Sample=(Sample+31)%32;GUILayout.Label("예제 "+Sample,label);if(GUILayout.Button("다음 예제",button))Sample=(Sample+1)%32;GUILayout.EndHorizontal();
   SimulateReferenceFailure=GUILayout.Toggle(SimulateReferenceFailure,"기준 확인 불량 시험");
   SimulatePoorContact=GUILayout.Toggle(SimulatePoorContact,"접촉 불량 시험");GUI.enabled=true;if(GUILayout.Button("UT 중단",button))Cancel();
   GUILayout.Label("절차: "+(ReferenceChecked?"✓":"○")+" 기준 확인  → "+(SurfacePrepared?"✓":"○")+" 표면 준비  → "+(CouplantApplied?"✓":"○")+" 젤 도포",label);
   if(Busy&&State!=Stage.Walking&&State!=Stage.Analysing){var progress=GUILayoutUtility.GetRect(300,12);GUI.Box(progress,"");GUI.DrawTexture(new Rect(progress.x,progress.y,progress.width*StageProgress,progress.height),Texture2D.whiteTexture);}
   GUILayout.Label("기준 확인·신호 안정은 절차 모의 동작입니다. 실제 교정/접촉 신호 측정이 아니며, 단계 시간은 시연용입니다.",label);
   if(Measurement!=null){GUILayout.Label("모델 점수 "+Measurement.pitScore.ToString("F3")+" / 문턱 "+Measurement.threshold.ToString("F3"),label);GUILayout.Label(Measurement.wallValid?"추정 주벽 두께 "+Measurement.mainWallMm.ToString("F2")+" mm (피팅 바닥 최소 두께 아님)":"두께 추정 불가",label);GUILayout.Label("출처: "+Measurement.source+" / "+Measurement.sampleId,label);
    var rect=GUILayoutUtility.GetRect(300,85);GUI.Box(rect,"A-scan (팀 합성 파형)");float peak=Mathf.Max(.00001f,Measurement.wave.Max(v=>Mathf.Abs(v)));for(int i=0;i<256;i++){float v=Measurement.wave[i*16]/peak;GUI.DrawTexture(new Rect(rect.x+i*rect.width/256,rect.y+43-Mathf.Max(v,0)*30,1,Mathf.Max(1,Mathf.Abs(v)*30)),Texture2D.whiteTexture);}
   }
   GUILayout.EndScrollView();GUILayout.EndArea();
  }
  void OnDestroy(){kit?.Dispose();if(view)DestroyImmediate(view.gameObject);foreach(var m in materials)if(m)DestroyImmediate(m);if(font)DestroyImmediate(font);}
 }
}
