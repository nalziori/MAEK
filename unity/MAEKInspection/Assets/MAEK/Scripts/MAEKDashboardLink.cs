using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEngine.Networking;
namespace MAEK {
 [Serializable] public class DashboardScenario {public string id,title,description,capability;}
 [Serializable] public class DashboardAccess {
  public string pipeId,status,observationStatus,inspectionStatus,accessStatus;
  public int plannedImages,scheduledImages,deferredImages,analysedImages;
  public string[] accessReasons;
 }
 [Serializable] public class DashboardCoverage {
  public int totalPipes,scheduledPipes,observedPipes,deferredPipes,partialPipes;
  public int requiredCaptures,scheduledCaptures,deferredCaptures;
 }
 [Serializable] public class DashboardTelemetry {
  public string sessionId,source="unity_virtual",scenarioId,scenarioRunId,phase,activePipe,status,droneView,guidance,frameId,imageBase64;
  public long sequence;public Vector3 position;public float yaw;public int leg,plannedPipes,analysedPipes,captures,expectedCaptures,collisionSteps;
  public bool active,paused,blocked,waiting,complete,recording,cameraAvailable;
  public DashboardScenario[] scenarios;public InspectionFinding[] mappedFindings;public InspectionOutcome[] outcomes;
  public DashboardAccess[] access;public DashboardCoverage coverage;
 }
 [Serializable] public class DashboardCommand {public string commandId,command,scenarioId;}
 [Serializable] public class DashboardCommands {public DashboardCommand[] commands;}
 [Serializable] public class DashboardAck {public string sessionId,commandId,status,message;}
 [DefaultExecutionOrder(350)]
 public sealed class MAEKDashboardLink:MonoBehaviour {
  public float previewFps=2;public bool publish=true;public string BaseUrl {get;private set;}
  public string LastError {get;private set;}="";public int PublishedFrames {get;private set;}
  public int EvaluationAcknowledged {get;private set;}public int UnsentEvaluations {get;private set;}
  public bool EvaluationPending=>evaluations.Count>0||sendingEvaluation;
  MAEKInspectionTour tour;MAEKInspectionScenarios scenarios;MAEKVirtualDrone drone;
  bool ready,publishing,polling,sendingEvaluation,showScenarios;string registeredSession="";long sequence;float nextFrame,nextPoll;Vector2 scroll;GUIStyle label,button;Font font;
  readonly Queue<ScenarioEvaluation> evaluations=new Queue<ScenarioEvaluation>();
  readonly Queue<DashboardAck> acknowledgements=new Queue<DashboardAck>();
  readonly Dictionary<string,DashboardAck> appliedCommands=new Dictionary<string,DashboardAck>();
  readonly Queue<string> appliedOrder=new Queue<string>();
  public void Initialize(){if(ready)return;Application.runInBackground=true;tour=GetComponent<MAEKInspectionTour>();scenarios=GetComponent<MAEKInspectionScenarios>();drone=GetComponent<MAEKVirtualDrone>();BaseUrl=new Uri(tour.endpoint).GetLeftPart(UriPartial.Authority);ready=true;scenarios.Initialize();}
  void Start(){Initialize();}
  public DashboardTelemetry Snapshot(bool image){
   Initialize();tour.Initialize();string session=string.IsNullOrEmpty(tour.SessionDirectory)?"":Path.GetFileName(tour.SessionDirectory);
   var data=new DashboardTelemetry{sessionId=session,sequence=++sequence,scenarioId=scenarios.Current?.id??"catalogue",scenarioRunId=scenarios.RunId,phase=scenarios.Running?"scenario_running":scenarios.Current!=null?"scenario_complete":tour.Complete?"complete":tour.Active?"inspection":"idle",activePipe=tour.CurrentPipe,status=tour.Status,position=tour.tourCamera.transform.position,yaw=tour.tourCamera.transform.eulerAngles.y,leg=tour.Leg,plannedPipes=tour.Plan.pipeIds.Length,analysedPipes=tour.AnalysedPipes,captures=tour.Captures.Count,expectedCaptures=tour.Plan.expectedCaptures,collisionSteps=tour.CollisionSteps,blocked=tour.Blocked,waiting=tour.Waiting,complete=tour.Complete||scenarios.Current!=null&&!scenarios.Running,recording=tour.Recorder&&tour.Recorder.Recording,cameraAvailable=scenarios.CameraAvailable,droneView=drone&&drone.chaseView?"chase":"fpv",guidance=scenarios.Guidance,scenarios=scenarios.Data.scenarios.Select(s=>new DashboardScenario{id=s.id,title=s.title,description=s.description,capability=s.capability}).ToArray(),mappedFindings=tour.Findings.Skip(Mathf.Max(0,tour.Findings.Count-40)).ToArray(),outcomes=tour.Outcomes.Skip(Mathf.Max(0,tour.Outcomes.Count-40)).ToArray()};
   data.active=tour.Active;data.paused=tour.Paused;data.complete=tour.Complete||scenarios.Finished;
   AddCoverage(data);
   if(UnsentEvaluations>0)data.guidance+=" · 평가 "+UnsentEvaluations+"건 서버 미전송 · 로컬 scenario_evaluation.json 보존";
   if(scenarios.Current!=null&&!scenarios.Running&&!scenarios.Finished){data.phase="scenario_stopped";data.status="검사 중지 · 미완료 항목 유지";}
   data.droneView=drone&&drone.DisplayCamera&&drone.DisplayCamera!=tour.tourCamera?"chase":"fpv";
   data.frameId=session+"-preview-"+data.sequence;if(string.IsNullOrEmpty(data.scenarioRunId))data.scenarioRunId=session;
   if(image&&data.cameraAvailable){try{data.imageBase64=Convert.ToBase64String(tour.CapturePixels(640,360));}catch(Exception e){data.cameraAvailable=false;LastError="영상 보류: "+e.Message;}}
   return data;
  }
  void AddCoverage(DashboardTelemetry data){
   var process=GetComponent<MAEKProcessContext>();
   if(!process)throw new InvalidOperationException("배관 관측 범위 자료가 없습니다");
   var rows=process.FollowUps().rows;
   if(rows==null||rows.Length>300||rows.Length!=data.plannedPipes||rows.Select(r=>r.pipeId).Distinct().Count()!=rows.Length)
    throw new InvalidOperationException("배관 관측 범위는 중복 없이 전체 계획 배관을 포함해야 합니다 (최대 300개)");
   data.access=rows.Select(r=>new DashboardAccess{pipeId=r.pipeId,plannedImages=r.plannedImages,
    scheduledImages=r.scheduledImages,deferredImages=r.deferredImages,analysedImages=r.analysedImages,
    status=r.status,observationStatus=r.observationStatus,inspectionStatus=r.inspectionStatus,
    accessStatus=r.accessStatus,accessReasons=r.accessReasons??Array.Empty<string>()}).ToArray();
   data.coverage=new DashboardCoverage{totalPipes=rows.Length,
    scheduledPipes=rows.Count(r=>r.scheduledImages>0),observedPipes=rows.Count(r=>r.observationStatus=="observed"),
    deferredPipes=rows.Count(r=>r.inspectionStatus=="deferred"),partialPipes=rows.Count(r=>r.inspectionStatus=="partial"),
    requiredCaptures=rows.Sum(r=>r.plannedImages),scheduledCaptures=rows.Sum(r=>r.scheduledImages),
    deferredCaptures=rows.Sum(r=>r.deferredImages)};
  }
  public void QueueEvaluation(ScenarioEvaluation row){if(evaluations.Count<32)evaluations.Enqueue(row);}
  void Update(){
   if(!ready||!publish||string.IsNullOrEmpty(tour.SessionDirectory))return;
   if(!publishing&&!polling&&Time.unscaledTime>=nextFrame){nextFrame=Time.unscaledTime+1/Mathf.Clamp(previewFps,.5f,5);StartCoroutine(Publish());}
   if(!polling&&Time.unscaledTime>=nextPoll){nextPoll=Time.unscaledTime+.5f;StartCoroutine(Poll());}
   if(!sendingEvaluation&&evaluations.Count>0&&(evaluations.Peek().sessionId!=Path.GetFileName(tour.SessionDirectory)||registeredSession==evaluations.Peek().sessionId))StartCoroutine(SendEvaluation());
  }
  IEnumerator Publish(){
   publishing=true;DashboardTelemetry data;
   try{data=Snapshot(true);}catch(Exception e){LastError=e.Message;publishing=false;yield break;}
   using(var web=UnityWebRequest.Post(BaseUrl+"/api/telemetry",JsonUtility.ToJson(data),"application/json")){web.timeout=3;yield return web.SendWebRequest();if(web.result==UnityWebRequest.Result.Success){registeredSession=data.sessionId;if(!string.IsNullOrEmpty(data.imageBase64))PublishedFrames++;LastError="";}else LastError="대시보드 연결 보류: "+web.error;}
   publishing=false;
  }
  IEnumerator Poll(){
   polling=true;string session=Path.GetFileName(tour.SessionDirectory);DashboardCommands commands=null;
   yield return FlushAcknowledgements();
   using(var web=UnityWebRequest.Get(BaseUrl+"/api/control?sessionId="+UnityWebRequest.EscapeURL(session))){web.timeout=3;yield return web.SendWebRequest();if(web.result==UnityWebRequest.Result.Success){try{commands=JsonUtility.FromJson<DashboardCommands>(web.downloadHandler.text);}catch(Exception e){LastError=e.Message;}}}
   if(commands?.commands!=null)foreach(var c in commands.commands){
    while(publishing)yield return null;
    var ack=ApplyCommand(c,session);if(!acknowledgements.Contains(ack))acknowledgements.Enqueue(ack);
    yield return FlushAcknowledgements();
   }
   polling=false;
  }
  public DashboardAck ApplyCommand(DashboardCommand command,string session){
   string key=session+"/"+command.commandId;if(appliedCommands.TryGetValue(key,out var prior))return prior;
   var ack=new DashboardAck{sessionId=session,commandId=command.commandId,status="applied",message="가상 환경에 적용됨"};
   try{if(session!=Path.GetFileName(tour.SessionDirectory))throw new InvalidOperationException("검사 세션 변경으로 이전 명령 취소");Execute(command);}
   catch(Exception e){ack.status="error";ack.message=e.Message;LastError=e.Message;}
   appliedCommands[key]=ack;appliedOrder.Enqueue(key);while(appliedOrder.Count>256)appliedCommands.Remove(appliedOrder.Dequeue());return ack;
  }
  IEnumerator FlushAcknowledgements(){
   while(acknowledgements.Count>0){var ack=acknowledgements.Peek();
    using(var web=UnityWebRequest.Post(BaseUrl+"/api/ack",JsonUtility.ToJson(ack),"application/json")){web.timeout=3;yield return web.SendWebRequest();
     if(web.result==UnityWebRequest.Result.Success)acknowledgements.Dequeue();
     else{LastError="제어 응답 보류: "+web.error;if(web.responseCode==400||web.responseCode==409){Debug.LogWarning(LastError+" · "+ack.commandId);acknowledgements.Dequeue();}else yield break;}
    }
   }
  }
  public void Execute(DashboardCommand command){
   var safety=GetComponent<MAEKSafetyDemo>();
   if(safety && (command.command=="scenario"||command.command=="run_all"||command.command=="start_original"||command.command=="start_extra"))
    throw new InvalidOperationException("안전 시연에서는 원래 계통을 유지합니다. 일반 시나리오는 기존 데모 장면에서 실행하세요.");
   if(safety && ((command.command=="resume" && !safety.CanInspect) ||
    ((command.command=="scenario"||command.command=="run_all"||command.command=="start_original"||command.command=="start_extra")&&!safety.CanStart)))
    throw new InvalidOperationException("안전 차단 · Unity에서 지상 확인 및 재승인 필요");
   Initialize();switch(command.command){
    case "scenario":scenarios.StartCase(command.scenarioId);break;
    case "run_all":scenarios.StartSuite();break;
    case "start_original":scenarios.Cancel();GetComponent<MAEKSupplementaryCircuits>().Select(false);break;
    case "start_extra":scenarios.Cancel();GetComponent<MAEKSupplementaryCircuits>().Select(true);break;
    case "pause":if(!tour.Active)throw new InvalidOperationException("활성 검사 없음");tour.SetPaused(true);break;case "resume":if(!tour.Active)throw new InvalidOperationException("활성 검사 없음");tour.SetPaused(false);break;
    case "stop":scenarios.Stop();if(tour.Active)tour.End();break;
    case "record_toggle":if(!tour.Active)throw new InvalidOperationException("검사를 먼저 시작하세요");if(tour.Recorder.Recording)tour.Recorder.StopRecording();else tour.Recorder.StartRecording(tour);break;
    case "view_toggle":if(!tour.Active)throw new InvalidOperationException("활성 검사 없음");drone.ToggleView();break;
    default:throw new ArgumentException("Unknown virtual drone command");
   }
  }
  IEnumerator SendEvaluation(){
   sendingEvaluation=true;var row=evaluations.Peek();
   using(var web=UnityWebRequest.Post(BaseUrl+"/api/evaluation",JsonUtility.ToJson(row),"application/json")){web.timeout=3;yield return web.SendWebRequest();if(web.result==UnityWebRequest.Result.Success){evaluations.Dequeue();EvaluationAcknowledged++;}else{LastError="평가 전송 보류: "+web.error;if(web.responseCode==400||web.responseCode==409){UnsentEvaluations++;Debug.LogWarning(LastError+" · 로컬 scenario_evaluation.json 보존");evaluations.Dequeue();}else yield return new WaitForSecondsRealtime(1);}}
   sendingEvaluation=false;
  }
  void OnGUI(){
   if(GetComponent<MAEKSafetyDemo>())return;
   if(!ready)return;if(label==null){font=Font.CreateDynamicFontFromOSFont(new[]{"Malgun Gothic","Arial"},14);label=new GUIStyle(GUI.skin.label){font=font,fontSize=14,wordWrap=true};button=new GUIStyle(GUI.skin.button){font=font,fontSize=14};}
   float x=Mathf.Max(12,Screen.width-320);
   if(GUI.Button(new Rect(x,Screen.height-130,148,32),"검사 시나리오",button)){showScenarios=!showScenarios;if(showScenarios)tour.HideResults();}
   if(GUI.Button(new Rect(x+158,Screen.height-130,150,32),"드론 보기 (V)",button))drone.ToggleView();
   if(GUI.Button(new Rect(x,Screen.height-90,308,32),"영상·결과 대시보드 열기",button))Application.OpenURL(BaseUrl+"/dashboard");
   if(!showScenarios)return;float y=196,height=Mathf.Max(100,Screen.height-y-145);GUI.Box(new Rect(x,y,308,height),"");GUILayout.BeginArea(new Rect(x+8,y+8,292,height-16));scroll=GUILayout.BeginScrollView(scroll);
   if(GUILayout.Button("모든 시나리오 순서대로 시험",button)){scenarios.StartSuite();showScenarios=false;}
   foreach(var s in scenarios.Data.scenarios){if(GUILayout.Button(s.id+" · "+s.title,button)){scenarios.StartCase(s.id);showScenarios=false;}GUILayout.Label(s.capability,label);}
   GUILayout.Label("합성 조건 · 색상 오탐은 FP로 기록 · 작업 허가 미판정",label);GUILayout.EndScrollView();GUILayout.EndArea();
  }
 }
}
