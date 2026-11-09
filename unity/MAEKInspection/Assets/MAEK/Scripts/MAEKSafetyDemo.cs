using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace MAEK {
 [DefaultExecutionOrder(-500)]
 public sealed class MAEKSafetyDemo : MonoBehaviour {
  public enum FlightPhase { Preflight, Ready, Launching, Inspecting, Returning, Landing, AwaitingApproval, EmergencyHold, ControlLost }
  public FlightPhase Phase {get;private set;}=FlightPhase.Preflight;
  public SafetyInputs Inputs {get;private set;}=new SafetyInputs();
  public SafetyGate Gate {get;private set;}=new SafetyGate();
  public bool Grounded {get;private set;}=true;
  public string Message {get;private set;}="모의 안전 조건을 확인하세요";
  public string LogPath {get;private set;}
  public bool ExternalClock;
  public MAEKInspectionTour Tour {get;private set;}
  public bool CanStart=>!accidentActive && controlAvailable && landingValid && Grounded && Gate.Evaluate(Inputs,false).Allowed;
  public bool CanInspect=>!accidentActive && controlAvailable && Phase==FlightPhase.Inspecting && Gate.Evaluate(Inputs,!Grounded).Allowed;
  readonly List<Vector3> trail=new List<Vector3>();
  readonly List<GameObject> visuals=new List<GameObject>();
  readonly List<Material> materials=new List<Material>();
  readonly Queue<string> history=new Queue<string>();
  public SafetyResponse Response {get;private set;}
  public string SelectedPad {get;private set;}="A";
  public bool AlternatePadsOccupied;
  public bool AccidentActive=>accidentActive;
  public bool ControlAvailable=>controlAvailable;
  public Vector3 AccidentPosition=>accidentPosition;
  public string AccidentPipeId=>accidentPipeId;
  public int PadCount=>pads.Count;
  public Vector3 PadPosition(int index)=>pads[index];
  public bool PadOccupied(int index)=>occupiedPads.Contains(index);
  readonly HashSet<int> occupiedPads=new HashSet<int>();
  bool accidentActive,controlAvailable=true,accidentReady;
  Vector3 accidentPosition;string accidentPipeId="";
  GameObject accidentEffect;ParticleSystem jet;
  public string PadDecisions {get;private set;}="사고 대기";
  public Vector3 BaseLanding=>pads.Count>0?pads[0]:landing;
  readonly List<Vector3> pads=new List<Vector3>();
  readonly List<Vector3> emergencyRoute=new List<Vector3>();
  bool personnelExcluded; int emergencyIndex;
  Vector3 home,landing,hazard; int returnIndex; bool ready,landingValid,hazardActive,hazardExited,expanded=true;
  GUIStyle label,button,title; Font font; Vector2 scroll;
  const float HazardRadius=3f;
  static readonly string[] Labels={"가스 경보","산소 경보","압력 경보","작업허가","공정 승인","장비 적합성","인원 통제","통신","정보 유효성","비상절차"};

  void Awake(){Initialize();}
  public void Initialize() {
   if(ready)return;ready=true;Tour=GetComponent<MAEKInspectionTour>();Tour.autoStart=false;Tour.Initialize();
   foreach(var walk in FindObjectsByType<MAEKWalkthrough>(FindObjectsSortMode.None))walk.enabled=false;
   foreach(var legacy in FindObjectsByType<MAEKDroneInspection>(FindObjectsSortMode.None))legacy.enabled=false;
   foreach(var services in FindObjectsByType<MAEKPipeServices>(FindObjectsSortMode.None))services.showInterface=false;
   home=Tour.Plan.points[0].position;Physics.SyncTransforms();
   landingValid=Physics.Raycast(home,Vector3.down,out var hit,1000,1<<8,QueryTriggerInteraction.Ignore)&&hit.normal.y>.95f;
   if(landingValid){landing=hit.point+Vector3.up*(Tour.Plan.radius+.08f);landingValid=Tour.SegmentClear(home,landing);}
   LogPath=Path.Combine(Application.persistentDataPath,"MAEK-safety",DateTime.Now.ToString("yyyyMMdd-HHmmss-fff"),"events.jsonl");
   Directory.CreateDirectory(Path.GetDirectoryName(LogPath));
   if(landingValid) {
    pads.Add(landing);
    foreach(var offset in new[]{new Vector3(-18,0,0),new Vector3(18,0,0),new Vector3(0,0,-18)}) {
     var top=home+offset;
     if(Physics.Raycast(top,Vector3.down,out var floor,1000,1<<8,QueryTriggerInteraction.Ignore)&&floor.normal.y>.95f) {
      var pad=floor.point+Vector3.up*(Tour.Plan.radius+.08f);
      if(Tour.SegmentClear(top,pad))pads.Add(pad);
     }
    }
   }
   var accidentPoint=(Tour.Plan.access??Array.Empty<InspectionAccess>()).Where(p=>!string.IsNullOrEmpty(p.pipeId)).OrderBy(p=>Vector3.Distance(p.target,home)).FirstOrDefault();
   if(accidentPoint!=null){accidentReady=true;accidentPosition=accidentPoint.target;accidentPipeId=accidentPoint.pipeId;}
   Gate.Evaluate(Inputs,false);Log("INITIAL", "합성 안전 시연 · 실제 작업허가 미판정");
   if(Application.isPlaying)for(int i=0;i<pads.Count;i++)Ring("모의 착륙 구역 "+(char)('A'+i),pads[i]-Vector3.up*Tour.Plan.radius,3,i==0?new Color(.15f,.85f,.75f):new Color(.2f,.5f,1));
  }
  public void SetNormal() {Inputs=SafetyInputs.Normal();Message="모의 입력 정상 · 경보 해제만으로 재개되지 않습니다";Log("INPUT_NORMAL",Message);}
  public void SetInput(int index,bool? value) {
   Inputs.Values[index]=value;if(index==6 && value==false)personnelExcluded=true;Log("INPUT",SafetyInputs.Names[index]+"="+(value.HasValue?value.ToString():"unknown"));Evaluate();
   if(!Grounded && (Phase==FlightPhase.Returning || Phase==FlightPhase.Landing) && MAEKSafetyResponse.Select(Inputs)!=SafetyResponse.None)PlanResponse();
  }
  public bool Approve() {
   if(accidentActive || !controlAvailable){Message="사고 종료 확인 전 재승인 불가";Log("RESET_DENIED",Message);return false;}
   var decision=Gate.Evaluate(Inputs,!Grounded,true);
   if(!Grounded || !decision.Allowed){Message="재승인 거부: 지상 상태와 모든 안전 조건 필요";Log("RESET_DENIED",Message);return false;}
   Phase=FlightPhase.Ready;Message="재승인 완료 · 시작 버튼을 별도로 누르세요";hazardActive=false;personnelExcluded=false;Response=SafetyResponse.None;
   foreach(var v in visuals)if(v && v.name.Contains("위험"))v.SetActive(false);
   Log("MANUAL_APPROVAL",Message);return true;
  }
  public void RequestStart() {
   Initialize();if(!CanStart){Message="시작 차단 · 모의 정상 조건과 지상 재승인 필요";Log("START_DENIED",Message);return;}
   if(!landingValid || !Tour.SegmentClear(landing,home)){Message="착륙 구역까지 충돌 없는 경로 미확보 · 시작 차단";Log("NO_LANDING_ROUTE",Message);return;}
   Tour.Begin();
  }
  public void OnTourStarted() {
   home=Tour.Plan.points[0].position;
   // The safety scene keeps its catalogue fixed while airborne.
   Tour.tourCamera.transform.position=landing;Grounded=false;trail.Clear();trail.Add(landing);
   Phase=FlightPhase.Launching;Message="모의 이륙 · 충돌 검사 후 점검 시작";Log("LAUNCH",Message);
  }
  public void TriggerRupture(bool retainControl=true) {
   Initialize();if(!accidentReady || accidentActive){Message="사고 위치 미확보 또는 사고 진행 중";return;}
   accidentActive=true;controlAvailable=retainControl;hazard=accidentPosition;hazardActive=true;
   Inputs.Values[9]=false;Gate.Evaluate(Inputs,!Grounded);
   occupiedPads.Add(1); // Staged worker at B; A is separately closed by the accident response cordon.
   Tour.SuspendForSafety("배관 파열 사고 · 검사 중단");
   if(Application.isPlaying)CreateRuptureVisual();
   Log("RUPTURE_SCENARIO",accidentPipeId+" · 버튼으로 발생시킨 사고, 감지 기능 아님");
   if(Grounded){Message="지상: 사고 발생으로 이륙 차단";Phase=FlightPhase.AwaitingApproval;return;}
   if(!controlAvailable){Phase=FlightPhase.ControlLost;Message="기체 제어 불가 · 추락 위험 · 현장 비상 대응 필요 (물리 추락 미계산)";Log("CONTROL_LOST",Message);return;}
   PlanResponse();
  }
  public void SetPadOccupied(int index,bool occupied) {
   if(index<0||index>=pads.Count)return;
   if(occupied)occupiedPads.Add(index);else occupiedPads.Remove(index);
   Log("PAD_OCCUPANCY",((char)('A'+index))+"="+occupied);
   if(!Grounded && (Phase==FlightPhase.Returning||Phase==FlightPhase.Landing))PlanResponse();
  }
  public void EndAccident() {
   if(!Grounded || !controlAvailable){Message="공중/제어 불가 상태에서 사고 종료 및 복구 불가";return;}
   accidentActive=false;hazardActive=false;occupiedPads.Clear();if(accidentEffect)accidentEffect.SetActive(false);
   SetNormal();Message="사고 종료 확인 · 재승인과 시작은 별도";Log("ACCIDENT_CLOSED",Message);
  }
  void CreateRuptureVisual() {
   Ring("위험: 배관 파열 3m (가상)",accidentPosition,HazardRadius,Color.red);
   accidentEffect=new GameObject("배관 파열 분출 연출 - 센서/물리 해석 아님");accidentEffect.layer=11;visuals.Add(accidentEffect);accidentEffect.transform.position=accidentPosition;
   accidentEffect.transform.rotation=Quaternion.LookRotation(Vector3.up);jet=accidentEffect.AddComponent<ParticleSystem>();jet.Stop(true,ParticleSystemStopBehavior.StopEmittingAndClear);
   var main=jet.main;main.loop=true;main.startLifetime=1.3f;main.startSpeed=7;main.startSize=.7f;main.startColor=new Color(.8f,.85f,.9f,.7f);main.maxParticles=100;main.simulationSpace=ParticleSystemSimulationSpace.World;
   var emission=jet.emission;emission.rateOverTime=30;var shape=jet.shape;shape.shapeType=ParticleSystemShapeType.Cone;shape.angle=12;shape.radius=.15f;
   var mat=new Material(Shader.Find("Unlit/Color")){color=new Color(.8f,.85f,.9f,.7f)};materials.Add(mat);jet.GetComponent<ParticleSystemRenderer>().sharedMaterial=mat;jet.Play();
  }
  public void RequestStop() {SetInput(9,false);}
  public void Evaluate() {
   var decision=Gate.Evaluate(Inputs,!Grounded);
   if(!decision.Allowed && !Grounded && (Phase==FlightPhase.Inspecting || Phase==FlightPhase.Launching)) {
    Message="검사 중단 · "+string.Join(", ",decision.Reasons);Tour.SuspendForSafety(Message);
    PlanResponse();
    Log("TRIP",Message);
   } else if(!decision.Allowed && Grounded && Phase==FlightPhase.Ready)Phase=FlightPhase.AwaitingApproval;
  }
  string ResponseLabel()=>accidentActive?"배관 파열: 사고 구역·점유 지점 제외":Response==SafetyResponse.GasDiversion?"가스: 위험 지점에서 먼 착륙장":
   Response==SafetyResponse.PressureDiversion?"압력: 위험 구역 밖 가까운 착륙장":
   Response==SafetyResponse.PersonnelDiversion?"인원: A 제외 · 대체 착륙장":
   Response==SafetyResponse.LostLinkReturn?"통신: 기체 사전 경로 복귀":
   Response==SafetyResponse.HoldUnknown?"정보 누락: 이동 보류 · 현장 확인":"허가: 검사 중단 · 복귀";
  void Hold(string reason) {Phase=FlightPhase.EmergencyHold;Message=reason;Log("RESPONSE_HOLD",reason);}
  static float DistanceToSegment(Vector3 p,Vector3 a,Vector3 b) {
   var d=b-a;return Vector3.Distance(p,a+d*Mathf.Clamp01(Vector3.Dot(p-a,d)/Mathf.Max(d.sqrMagnitude,.000001f)));
  }
  bool SafeSegment(Vector3 a,Vector3 b) {
   if(!Tour.SegmentClear(a,b))return false;
   if(hazardActive) {
    float start=Vector3.Distance(a,hazard),end=Vector3.Distance(b,hazard);
    if(start<HazardRadius) {if(end<start-.001f || Vector3.Dot(b-a,a-hazard)<-.001f)return false;}
    else if(DistanceToSegment(hazard,a,b)<HazardRadius)return false;
   }
   if(personnelExcluded && pads.Count>0) {
    var center=pads[0];a.y=center.y;b.y=center.y;
    float start=Vector3.Distance(a,center),end=Vector3.Distance(b,center);
    // The entire vertical column over occupied A is excluded. Only departure from it is allowed.
    if(start<5) {if(end<start-.001f || Vector3.Dot(b-a,a-center)<-.001f)return false;}
    else if(DistanceToSegment(center,a,b)<5)return false;
   }
   for(int i=0;i<pads.Count;i++)if(occupiedPads.Contains(i)||(accidentActive&&i==0)) {
    var center=pads[i];var flatA=new Vector3(a.x,center.y,a.z);var flatB=new Vector3(b.x,center.y,b.z);
    float start=Vector3.Distance(flatA,center),end=Vector3.Distance(flatB,center);
    if(start<5){if(end<start-.001f||Vector3.Dot(flatB-flatA,flatA-center)<-.001f)return false;}
    else if(DistanceToSegment(center,flatA,flatB)<5)return false;
   }
   return true;
  }
  bool RouteClear(List<Vector3> route) {
   var previous=Tour.tourCamera.transform.position;
   foreach(var point in route){if(!SafeSegment(previous,point))return false;previous=point;}
   return true;
  }
  void PlanResponse() {
   if(!controlAvailable){Phase=FlightPhase.ControlLost;return;}
   Response=MAEKSafetyResponse.Select(Inputs);
   if(Response==SafetyResponse.HoldUnknown){Hold("안전 정보 미확인 · 자동 이동 중지 · 현장 판단 필요");return;}
   if(Inputs.Values[6]==false)personnelExcluded=true;
   if(!hazardActive && (Inputs.Values[0]==true||Inputs.Values[1]==true||Inputs.Values[2]==true)) {
    hazard=Tour.tourCamera.transform.position;hazardActive=true;
    if(Application.isPlaying)Ring("위험 구역 (가상 3m)",hazard,HazardRadius,new Color(1,.23f,.18f));
   }
   var current=Tour.tourCamera.transform.position;
   PadDecisions="";
   for(int i=0;i<pads.Count;i++)PadDecisions+=((char)('A'+i))+": "+(accidentActive&&i==0?"사고 대응 폐쇄":occupiedPads.Contains(i)||AlternatePadsOccupied&&i>0?"작업자 점유":personnelExcluded&&i==0?"인원 진입":"경로 확인 대상")+"  ";
   var candidates=Enumerable.Range(0,pads.Count).Where(i=>!(personnelExcluded&&i==0)&&!(AlternatePadsOccupied&&i>0)&&!occupiedPads.Contains(i)&&!(accidentActive&&i==0));
   if(Response==SafetyResponse.GasDiversion)candidates=candidates.OrderByDescending(i=>Vector3.Distance(pads[i],hazard));
   else if(Response==SafetyResponse.PressureDiversion || Response==SafetyResponse.PersonnelDiversion)candidates=candidates.OrderBy(i=>Vector3.Distance(pads[i],current));
   foreach(int index in candidates) {
    var pad=pads[index];if(hazardActive&&Vector3.Distance(pad,hazard)<HazardRadius)continue;
    var approach=new Vector3(pad.x,Mathf.Max(current.y,pad.y+4),pad.z);
    var direct=new List<Vector3>{approach,pad};
    // Lost-link uses only the previously recorded flight corridor to A.
    var reverse=new List<Vector3>();for(int i=trail.Count-1;i>=0;i--)reverse.Add(trail[i]);
    if(index!=0)reverse.Clear();
    if(reverse.Count>0)reverse.Add(pad);
    List<Vector3> chosen=null;
    if(Response==SafetyResponse.LostLinkReturn && index==0 && reverse.Count>0&&RouteClear(reverse))chosen=reverse;
    else if(Response!=SafetyResponse.LostLinkReturn && RouteClear(direct))chosen=direct;
    else if(Response!=SafetyResponse.LostLinkReturn && reverse.Count>0&&RouteClear(reverse))chosen=reverse;
    if(chosen==null){PadDecisions+="\n"+(char)('A'+index)+": 경로 미확보";continue;}
    emergencyRoute.Clear();emergencyRoute.AddRange(chosen);emergencyIndex=0;SelectedPad=((char)('A'+index)).ToString();
    Phase=FlightPhase.Returning;Message=ResponseLabel()+" → "+SelectedPad+" (모의 확인 구역)";Log("RESPONSE_PLANNED",Message);return;
   }
   Hold("이용 가능한 착륙장/충돌 없는 경로 없음 · 이동 중지 · 현장 비상절차 필요");
  }
  void Update(){if(!ExternalClock)Tick(Time.deltaTime);}
  public void Tick(float dt) {
   Initialize();Evaluate();dt=Mathf.Clamp(dt,0,.1f);
   if(Phase==FlightPhase.Inspecting) {
    var p=Tour.tourCamera.transform.position;if(trail.Count==0||Vector3.Distance(trail[trail.Count-1],p)>.25f)trail.Add(p);
    return;
   }
   if(Phase!=FlightPhase.Launching && Phase!=FlightPhase.Returning && Phase!=FlightPhase.Landing)return;
   var old=Tour.tourCamera.transform.position;
   Vector3 target=Phase==FlightPhase.Launching?home:emergencyRoute[emergencyIndex];
   var next=Vector3.MoveTowards(old,target,6*dt);Physics.SyncTransforms();
   bool safe=Phase==FlightPhase.Launching?Tour.SegmentClear(old,next):SafeSegment(old,next);
   if(!safe) {
    Phase=FlightPhase.EmergencyHold;Message="비상 경로 차단 · 이동 정지 · 현장 비상절차 필요";Log("EGRESS_BLOCKED",Message);return;
   }
   Tour.tourCamera.transform.position=next;
   if(hazardActive && Vector3.Distance(next,hazard)>=HazardRadius)hazardExited=true;
   if(Phase==FlightPhase.Launching && Vector3.Distance(trail[trail.Count-1],next)>.25f)trail.Add(next);
   if(Vector3.Distance(next,target)>.001f)return;
   if(Phase==FlightPhase.Launching){Phase=FlightPhase.Inspecting;Message="정상 점검 · 가상 안전 입력";Log("INSPECTION",Message);}
   else if(emergencyIndex<emergencyRoute.Count-1) {
    emergencyIndex++;if(emergencyIndex==emergencyRoute.Count-1){Phase=FlightPhase.Landing;Message=SelectedPad+" 착륙장으로 하강 · 검사 차단 유지";Log("LANDING",Message);}
   } else {landing=target;Grounded=true;Phase=FlightPhase.AwaitingApproval;Message=SelectedPad+" 착륙 완료 · 경보 해제 후 지상 재승인 필요";Log("GROUNDED",Message);}

  }
  [Serializable] class EventRow {
   public string utc,eventName,phase,detail,response,landingPad,accidentPipe;public bool accident,controllable;public Vector3 accidentPoint;public bool grounded,latched,inspectionAllowed;
   public string[] inputs;public Vector3 position;
   public string scope="synthetic safety procedure; no physical accident prevention validation";
   public string workPermissionStatus="not_assessed";
  }
  void Log(string name,string detail) {
   string line=DateTime.Now.ToString("HH:mm:ss")+" "+name+" · "+detail;history.Enqueue(line);while(history.Count>8)history.Dequeue();
   if(string.IsNullOrEmpty(LogPath))return;
   var row=new EventRow{utc=DateTime.UtcNow.ToString("o"),eventName=name,phase=Phase.ToString(),detail=detail,accident=accidentActive,controllable=controlAvailable,accidentPipe=accidentPipeId,accidentPoint=accidentPosition,response=Response.ToString(),landingPad=SelectedPad,grounded=Grounded,
    latched=Gate.Latched,inspectionAllowed=CanInspect,position=Tour.tourCamera.transform.position,
    inputs=Inputs.Values.Select(v=>v.HasValue?v.Value.ToString():"unknown").ToArray()};
   try{File.AppendAllText(LogPath,JsonUtility.ToJson(row)+Environment.NewLine);}catch(IOException e){Debug.LogWarning("Safety log write failed: "+e.Message);}
  }
  void Ring(string name,Vector3 center,float radius,Color color) {
   var go=new GameObject(name);go.layer=11;visuals.Add(go);var line=go.AddComponent<LineRenderer>();
   var material=new Material(Shader.Find("Unlit/Color")){color=color};materials.Add(material);line.sharedMaterial=material;
   line.positionCount=65;line.startWidth=line.endWidth=.06f;line.useWorldSpace=true;
   for(int i=0;i<65;i++){float a=i*Mathf.PI*2/64;line.SetPosition(i,center+new Vector3(Mathf.Cos(a)*radius,.04f,Mathf.Sin(a)*radius));}
   // Presentation on layer 11: excluded from unannotated RGB and environment collision.
  }
  string PhaseLabel()=>Phase==FlightPhase.Preflight?"검사 전 확인":Phase==FlightPhase.Ready?"시작 승인됨":
   Phase==FlightPhase.Launching?"모의 이륙":Phase==FlightPhase.Inspecting?"정상 점검":Phase==FlightPhase.Returning?"대피 중":
   Phase==FlightPhase.ControlLost?"제어 불가 · 추락 위험":Phase==FlightPhase.Landing?"착륙 중":Phase==FlightPhase.EmergencyHold?"비상 경로 차단":"재승인 대기";
  void SolidPanel(Rect rect){var color=GUI.color;GUI.color=new Color(.055f,.075f,.10f,1);GUI.DrawTexture(rect,Texture2D.whiteTexture);GUI.color=color;}
  void DrawResponseMap() {
   if(pads.Count==0)return;
   var box=new Rect(12,Screen.height-248,390,228);SolidPanel(box);GUI.Box(box,"사고 대응 평면도 · 위치/점유는 시연 설정");
   var points=new List<Vector3>(pads){accidentPosition,Tour.tourCamera.transform.position};
   float minX=points.Min(p=>p.x)-8,maxX=points.Max(p=>p.x)+8,minZ=points.Min(p=>p.z)-8,maxZ=points.Max(p=>p.z)+8;
   Func<Vector3,Vector2> map=p=>new Vector2(box.x+30+(p.x-minX)/(maxX-minX)*(box.width-90),box.y+40+(maxZ-p.z)/(maxZ-minZ)*(box.height-80));
   if(accidentActive && controlAvailable && (Phase==FlightPhase.Returning||Phase==FlightPhase.Landing)) {
    var from=map(Tour.tourCamera.transform.position);
    for(int i=emergencyIndex;i<emergencyRoute.Count;i++){var to=map(emergencyRoute[i]);var d=to-from;var old=GUI.matrix;GUIUtility.RotateAroundPivot(Mathf.Atan2(d.y,d.x)*Mathf.Rad2Deg,from);var c=GUI.color;GUI.color=Color.cyan;GUI.DrawTexture(new Rect(from.x,from.y,d.magnitude,2),Texture2D.whiteTexture);GUI.color=c;GUI.matrix=old;from=to;}
   }
   for(int i=0;i<pads.Count;i++) {
    var pt=map(pads[i]);string status=accidentActive&&i==0?"폐쇄":occupiedPads.Contains(i)||AlternatePadsOccupied&&i>0?"인원":"후보";
    GUI.Label(new Rect(pt.x-12,pt.y-12,95,40),((char)('A'+i))+" "+status,label);
   }
   var source=map(accidentPosition);GUI.Label(new Rect(source.x-15,source.y-25,110,45),accidentActive?"● 파열 위치":"○ 사고 지정점",label);
   var drone=map(Tour.tourCamera.transform.position);GUI.Label(new Rect(drone.x-12,drone.y,110,40),controlAvailable?"◆ 드론":"◆ 제어 불가",label);
   GUI.Label(new Rect(box.x+10,box.y+box.height-30,box.width-20,25),"고도 "+Tour.tourCamera.transform.position.y.ToString("F1")+"m | 목표 "+SelectedPad,label);
  }
  void OnGUI() {
   if(!ready)return;
   if(label==null){font=Font.CreateDynamicFontFromOSFont(new[]{"Malgun Gothic","Arial"},15);label=new GUIStyle(GUI.skin.label){font=font,fontSize=15,wordWrap=true};button=new GUIStyle(GUI.skin.button){font=font,fontSize=14};title=new GUIStyle(label){fontSize=19,fontStyle=FontStyle.Bold};}
   GUI.depth=-100;DrawResponseMap();float width=Mathf.Min(410,Screen.width-24),x=Screen.width-width-12;
   if(GUI.Button(new Rect(x,12,width,34),"사고 발생 후 대응 | "+PhaseLabel()+ (expanded?"  ▾":"  ▸"),button))expanded=!expanded;
   if(!expanded)return;
   var area=new Rect(x,50,width,Mathf.Max(120,Screen.height-65));SolidPanel(area);GUI.Box(area,"");
   GUILayout.BeginArea(new Rect(area.x+10,area.y+8,area.width-20,area.height-16));scroll=GUILayout.BeginScrollView(scroll);
   GUILayout.Label("배관 사고 대응 · 센서 감지 기능 없음",title);
   GUILayout.Space(6);
   if(GUILayout.Button("① 시연 준비 / 일반 경보 해제",button,GUILayout.Height(30)))SetNormal();
   if(GUILayout.Button("② 지상 확인 후 수동 재승인",button,GUILayout.Height(30)))Approve();
   if(GUILayout.Button("③ 검사 시작 (재승인과 별도)",button,GUILayout.Height(30)))RequestStart();
   GUILayout.Label("사고 배관: "+accidentPipeId+" | 지정 위치 고정",label);
   if(GUILayout.Button("배관 파열 발생 · 제어 가능",button,GUILayout.Height(32)))TriggerRupture(true);
   if(GUILayout.Button("배관 파열 발생 · 기체 제어 불가",button,GUILayout.Height(32)))TriggerRupture(false);
   GUILayout.Label("사고 버튼: A 폐쇄 + B 작업자 진입을 함께 설정",label);
   if(GUILayout.Button("사고 종료 확인 (착륙 후)",button))EndAccident();
   GUILayout.Label(PadDecisions,label);
   GUILayout.BeginHorizontal();for(int p=1;p<pads.Count;p++){int pad=p;if(GUILayout.Button(((char)('A'+p))+" "+(occupiedPads.Contains(p)?"퇴장":"인원 진입"),button))SetPadOccupied(pad,!occupiedPads.Contains(pad));}GUILayout.EndHorizontal();
   GUILayout.Label(Message,label);
   GUILayout.Label("검사: "+(CanInspect?"허용":"차단")+" | "+(Grounded?"지상":"비행 중")+" | "+(Gate.Latched?"중단 잠금 유지":"잠금 해제"),label);
   GUILayout.Label("대응: "+ResponseLabel()+" | 착륙장 "+SelectedPad,label);
   GUILayout.Space(8);GUILayout.Label("기존 경계 조건 시험 (선택)",title);
   GUILayout.BeginHorizontal();if(GUILayout.Button("압력 이상",button))SetInput(2,true);if(GUILayout.Button("가스 경보",button))SetInput(0,true);if(GUILayout.Button("통신 두절",button))SetInput(7,false);GUILayout.EndHorizontal();
   GUILayout.BeginHorizontal();if(GUILayout.Button("허가 미충족",button))SetInput(3,false);if(GUILayout.Button("인원 진입",button))SetInput(6,false);if(GUILayout.Button("정보 누락",button))SetInput(8,null);GUILayout.EndHorizontal();
   if(GUILayout.Button("대체 착륙장 모두 점유: "+(AlternatePadsOccupied?"예":"아니오"),button)){AlternatePadsOccupied=!AlternatePadsOccupied;if(!Grounded && Phase!=FlightPhase.EmergencyHold && Phase!=FlightPhase.Inspecting && Phase!=FlightPhase.Launching)PlanResponse();}
   for(int i=0;i<10;i++){var v=Inputs.Values[i];GUILayout.Label(Labels[i]+": "+(!v.HasValue?"미확인":v.Value==(i>=3)?"정상":"이상"),label);}
   GUILayout.Space(6);GUILayout.Label("2차 사고 예방 절차",title);
   GUILayout.Label("작업자: 착륙 구역 출입 통제\n설비: 매 이동 구간 충돌 검사 · 막히면 정지\n가스: 위험 구역 이탈 후 재진입 차단\n통신 두절: 기체에 사전 설정된 동작의 모사",label);
   GUILayout.Label("A는 기본, B·C·D는 모의 확인된 대체 지점. 인원 진입은 A 점유를 뜻합니다. 정보 누락 시 이동 보류. 경로 미확보는 안전 판정이 아닙니다. 가상 위험 반경 3m는 현장 안전거리가 아닙니다. 폭발·추락·점화 방지 성능 미검증.",label);
   foreach(var item in history)GUILayout.Label(item,label);
   if(GUILayout.Button("검증 로그 폴더 열기",button))Application.OpenURL(Path.GetDirectoryName(LogPath));
   GUILayout.EndScrollView();GUILayout.EndArea();
  }
  void OnDestroy(){foreach(var go in visuals)if(go)Destroy(go);foreach(var m in materials)if(m)Destroy(m);if(font)Destroy(font);}
 }
}
