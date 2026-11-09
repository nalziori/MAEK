using System;
using System.Collections;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using UnityEngine;
using UnityEngine.Networking;

namespace MAEK {
 [Serializable] public class ThermalCaptureRequest {
  public string requestId,sessionId,runId,assetId,startedAt,capturedAt,condition;
  public int sequence,width=320,height=256;
  public string geometryBase64,geometrySha256,rgbBase64,rgbSha256;
  public Vector3 position;public Quaternion rotation;public float fieldOfView;
 }
 [Serializable] public class ThermalFinding {public string kind;public int[] bbox;public int pixelCount;}
 [Serializable] public class ThermalQuality {public bool canInfer;public string code,message;public float emissivity;}
 [Serializable] public class ThermalObservation {
  public string requestId,sessionId,runId,assetId,status,rgbSha256,geometrySha256,thermalSha256,temperatureSha256,thermalPngBase64,workPermissionStatus;
  public int width,height,roiPixels;public bool synthetic;public float minC,maxC,meanC,referenceC,deltaC,paletteMinC,paletteMaxC;
  public ThermalQuality quality;public ThermalFinding[] findings;
 }
 [DefaultExecutionOrder(475)] public sealed class MAEKThermalDemo:MonoBehaviour {
  public enum Stage {Waiting,Launching,Approaching,Settling,Analysing,Complete,Deferred,Interrupted}
  public Transform fixture;public Collider surface;public Camera observer;
  public Vector3 hover,aim,axisOrigin,axis=Vector3.right;public float axisScale=1;
  public string AssetId="BF1-Q005";string inputAsset="BF1-Q005";
  readonly System.Collections.Generic.List<Vector3> path=new System.Collections.Generic.List<Vector3>();int pathIndex,captureLeg;
  public bool ExternalClock;
  public Stage State {get;private set;}=Stage.Waiting;
  public bool Displaying {get;private set;}
  public ThermalObservation Observation {get;private set;}
  public string Status {get;private set;}="기존 배관 · 열화상 준비";
  public string Condition="normal",Endpoint="http://127.0.0.1:8894";
  public string RequestId {get;private set;}="";
  [NonSerialized] public string SessionId=Guid.NewGuid().ToString("N");
  public int Generation {get;private set;}
  public ThermalCaptureRequest LastCapture {get;private set;}
  MAEKSafetyDemo safety;MAEKInspectionTour tour;Texture2D thermalImage,rgbImage;float dwell;int seq;string started;bool initialized,thermalView=true,routeReady,eventSending;
  Font font;GUIStyle label,button;Vector2 scroll;
  public bool Busy=>State==Stage.Launching||State==Stage.Approaching||State==Stage.Settling||State==Stage.Analysing;
  public static string Hash(byte[] b){using(var s=SHA256.Create())return BitConverter.ToString(s.ComputeHash(b)).Replace("-","").ToLowerInvariant();}
  public void Initialize(){if(initialized)return;initialized=true;safety=GetComponent<MAEKSafetyDemo>();safety.Initialize();tour=safety.Tour;
   Endpoint=Environment.GetEnvironmentVariable("MAEK_THERMAL_ENDPOINT")??Endpoint;SelectAsset(AssetId);}
  void Start(){Initialize();SelectAsset(AssetId);}
  public bool SelectAsset(string id){
   Initialize();if(Busy)return false;
   var services=FindFirstObjectByType<MAEKPipeServices>();if(!services){Status="배관 계통 정보 없음";return false;}services.Initialize();
   var pipe=services.Data.pipes.FirstOrDefault(p=>p.id==id);if(pipe==null){Status="등록되지 않은 배관 ID";return false;}
   AssetId=id;inputAsset=id;Observation=null;LastCapture=null;if(thermalImage)DestroyImmediate(thermalImage);if(rgbImage)DestroyImmediate(rgbImage);
   var asset=FindObjectsByType<MAEKPipeService>(FindObjectsSortMode.None).FirstOrDefault(p=>p.lineId==id);
   captureLeg=Array.FindIndex(tour.Plan.points,p=>p.pipeId==id);
   if(!asset||captureLeg<0){fixture=null;Status=id+": 기존 경로의 유효 촬영 지점 없음 · 검사 보류";return false;}
   fixture=asset.transform;surface=asset.GetComponentInChildren<Collider>();var point=tour.Plan.points[captureLeg];hover=point.position;aim=point.target;axisOrigin=aim;
   axis=pipe.points.Length>1?(MAEKPipeServices.V(pipe.points[1].position)-MAEKPipeServices.V(pipe.points[0].position)).normalized:Vector3.right;
   axisScale=Mathf.Clamp(pipe.length*.5f,.5f,2f);State=Stage.Waiting;Status=id+" 선택 · 기존 촬영 경로 사용 · 합성 온도";return true;
  }
  bool PreparePath(){
   path.Clear();pathIndex=0;var current=tour.tourCamera.transform.position;
   var candidates=tour.Plan.points.Take(captureLeg+1).Select(p=>p.position).ToArray();int first=0;
   while(Vector3.Distance(current,hover)>.001f){int reachable=-1;for(int i=candidates.Length-1;i>=first;i--)if(tour.SegmentClear(current,candidates[i])){reachable=i;break;}
    if(reachable<0){Deferred("기존 경로 연결 미확보 · 검사 보류");return false;}
    current=candidates[reachable];path.Add(current);first=reachable+1;
   }return true;
  }
  public void Begin(string condition){
   Initialize();if(!fixture||Busy||GetComponent<MAEKWorkerUT>()?.Busy==true||safety.AccidentActive||!safety.ControlAvailable){Status="진행 중 검사/사고/대상 조건 확인 필요";return;}
   if(!safety.Grounded&&!safety.CanInspect){Status="지상 재승인 또는 비행 중 안전 조건 확인 필요";return;}
   if(safety.Grounded&&!safety.CanStart){Status="오른쪽 정상 조건 → 지상 시연 승인 후 시작하세요";return;}
   Condition=condition;Generation++;seq=0;RequestId=Guid.NewGuid().ToString("N");started=DateTime.UtcNow.ToString("o");Observation=null;LastCapture=null;
   if(thermalImage)DestroyImmediate(thermalImage);if(rgbImage)DestroyImmediate(rgbImage);
   Displaying=true;routeReady=false;tour.externalClock=true;
   if(safety.Grounded){safety.RequestStart();State=Stage.Launching;Status="모의 이륙 · 기존 안전 게이트 적용";}else{State=Stage.Approaching;Status=AssetId+" 촬영 지점 접근";}
   if(Application.isPlaying)StartCoroutine(PostEvent("Launching",0));
  }
  public void Cancel(){if(!initialized)return;Generation++;StopAllCoroutines();eventSending=false;Observation=null;LastCapture=null;
   if(thermalImage)DestroyImmediate(thermalImage);if(rgbImage)DestroyImmediate(rgbImage);
   State=Stage.Interrupted;Status="열화상 중단 · 현재 판정 확정 차단";
   if(Application.isPlaying&&RequestId!="")StartCoroutine(PostEvent("Interrupted",++seq));
   if(!safety.Grounded)safety.RequestStop();
  }
  void Deferred(string message){Observation=null;State=Stage.Deferred;Status=message;if(Application.isPlaying)StartCoroutine(PostEvent("Deferred",++seq));}
  public void Tick(float dt){Initialize();dt=Mathf.Clamp(dt,0,.1f);
   if(Busy&&(safety.AccidentActive||safety.Gate.Latched||!safety.ControlAvailable||State!=Stage.Launching&&!safety.CanInspect)){Cancel();return;}
   if(State==Stage.Launching&&safety.CanInspect){State=Stage.Approaching;Status=AssetId+" 기존 경로 · 충돌 검사하며 접근";if(!PreparePath())return;routeReady=true;if(Application.isPlaying)StartCoroutine(PostEvent("Approaching",++seq));}
   if(State==Stage.Approaching){if(!routeReady){if(!PreparePath())return;routeReady=true;}var p=tour.tourCamera.transform.position;var destination=pathIndex<path.Count?path[pathIndex]:hover;var next=Vector3.MoveTowards(p,destination,8*dt);
    if(!tour.SegmentClear(p,next)){Deferred("접근 경로 차단 · 촬영 보류");return;}
    tour.tourCamera.transform.position=next;var rotation=Quaternion.LookRotation(aim-next);tour.tourCamera.transform.rotation=Quaternion.RotateTowards(tour.tourCamera.transform.rotation,rotation,80*dt);
    if(Vector3.Distance(next,destination)<.001f&&pathIndex<path.Count)pathIndex++;
    if(Vector3.Distance(next,hover)<.001f&&Quaternion.Angle(tour.tourCamera.transform.rotation,rotation)<.1f){State=Stage.Settling;dwell=0;Status="정지 · 대상 표면과 가림 확인";if(Application.isPlaying)StartCoroutine(PostEvent("Settling",++seq));}
   }
   if(State==Stage.Settling){dwell+=dt;if(dwell>1.5f){
    try{LastCapture=Capture();State=Stage.Analysing;Status="장면 정합 온도 영상 생성·규칙 분석 중";if(Application.isPlaying)StartCoroutine(Analyse(Generation));}
    catch(Exception e){Deferred("촬영 보류: "+e.Message);}
   }}
   if(Displaying)RefreshObserver();
  }
  bool Visible(){
   var direction=(aim-tour.tourCamera.transform.position).normalized;var side=Vector3.Cross(direction,Vector3.up).normalized;int visible=0;
   for(int i=-2;i<=2;i++){var target=aim+side*(i*.025f);var d=target-tour.tourCamera.transform.position;
    if(Physics.Raycast(tour.tourCamera.transform.position,d.normalized,out var h,d.magnitude+.6f,1<<8,QueryTriggerInteraction.Ignore)&&MAEKSupplementaryCircuits.TargetId(h.collider)==AssetId)visible++;
   }return visible>=3;
  }
  public ThermalCaptureRequest Capture(){
   if(!safety.CanInspect||safety.AccidentActive||!Visible())throw new InvalidOperationException("대상 표면 가시성/안전 조건 미확보");
   var cam=tour.tourCamera;float oldAspect=cam.aspect;var oldRT=cam.targetTexture;var oldActive=RenderTexture.active;
   var rt=RenderTexture.GetTemporary(320,256,24);var image=new Texture2D(320,256,TextureFormat.RGB24,false);
   try{cam.aspect=320f/256;cam.targetTexture=rt;cam.Render();RenderTexture.active=rt;image.ReadPixels(new Rect(0,0,320,256),0,0);image.Apply();
    byte[] png=image.EncodeToPNG();byte[] geom;int count=0;
    using(var stream=new MemoryStream())using(var writer=new BinaryWriter(stream)){
     for(int y=0;y<256;y++)for(int x=0;x<320;x++){
      var ray=cam.ViewportPointToRay(new Vector3((x+.5f)/320,1-(y+.5f)/256,0));float axial=0,up=0,inside=0;
      if(Physics.Raycast(ray,out var h,200,1<<8,QueryTriggerInteraction.Ignore)&&MAEKSupplementaryCircuits.TargetId(h.collider)==AssetId){axial=Mathf.Clamp(Vector3.Dot(h.point-axisOrigin,axis)/axisScale,-1,1);up=h.normal.y;inside=1;count++;}
      writer.Write(axial);writer.Write(up);writer.Write(inside);
     }geom=stream.ToArray();
    }
    if(count<500)throw new InvalidOperationException("보이는 배관 픽셀 부족");
    if(rgbImage)DestroyImmediate(rgbImage);rgbImage=new Texture2D(2,2);rgbImage.LoadImage(png);
    return new ThermalCaptureRequest{assetId=AssetId,requestId=RequestId,sessionId=SessionId,runId=RequestId,startedAt=started,capturedAt=DateTime.UtcNow.ToString("o"),sequence=++seq,condition=Condition,
     rgbBase64=Convert.ToBase64String(png),rgbSha256=Hash(png),geometryBase64=Convert.ToBase64String(geom),geometrySha256=Hash(geom),position=cam.transform.position,rotation=cam.transform.rotation,fieldOfView=cam.fieldOfView};
   }finally{cam.aspect=oldAspect;cam.targetTexture=oldRT;RenderTexture.active=oldActive;RenderTexture.ReleaseTemporary(rt);DestroyImmediate(image);}
  }
  [Serializable] class Event {public string sessionId,runId,requestId,assetId,startedAt,stage;public int sequence;}
  IEnumerator PostEvent(string stage,int sequence){
   int token=Generation;while(eventSending&&token==Generation)yield return null;if(token!=Generation)yield break;eventSending=true;
   var e=new Event{assetId=AssetId,sessionId=SessionId,runId=RequestId,requestId=RequestId,startedAt=started,stage=stage,sequence=sequence};
   try{using(var req=UnityWebRequest.Post(Endpoint+"/api/thermal/event",JsonUtility.ToJson(e),"application/json")){req.timeout=5;yield return req.SendWebRequest();}}finally{eventSending=false;}
  }
  IEnumerator Analyse(int generation){
   yield return PostEvent("Analysing",seq);if(generation!=Generation||State!=Stage.Analysing)yield break;
   using(var req=UnityWebRequest.Post(Endpoint+"/api/thermal/capture",JsonUtility.ToJson(LastCapture),"application/json")){
    req.timeout=30;yield return req.SendWebRequest();if(generation!=Generation||State!=Stage.Analysing)yield break;
    if(req.result!=UnityWebRequest.Result.Success){Deferred("열화상 서버 오류 · 결과 없음: "+req.error);yield break;}
    if(!Accept(req.downloadHandler.text,generation))Deferred("촬영 ID/원본/응답 불일치 · 판정 보류");
   }
  }
  public bool Accept(string json,int generation){
   if(generation!=Generation||State!=Stage.Analysing||LastCapture==null||!safety.CanInspect||safety.AccidentActive)return false;
   try{var r=JsonUtility.FromJson<ThermalObservation>(json);
    if(r==null||r.requestId!=RequestId||r.runId!=RequestId||r.sessionId!=SessionId||r.assetId!=AssetId||r.rgbSha256!=LastCapture.rgbSha256||r.geometrySha256!=LastCapture.geometrySha256||!r.synthetic||r.workPermissionStatus!="not_assessed"||r.width!=320||r.height!=256||r.quality==null||r.roiPixels<500||float.IsNaN(r.maxC)||float.IsInfinity(r.maxC)||!(new[]{"anomaly_observed","no_anomaly_observed","indeterminate"}).Contains(r.status))return false;
    var bytes=Convert.FromBase64String(r.thermalPngBase64);if(Hash(bytes)!=r.thermalSha256)return false;
    var texture=new Texture2D(2,2);if(!texture.LoadImage(bytes)||texture.width!=320||texture.height!=256){DestroyImmediate(texture);return false;}
    if(thermalImage)DestroyImmediate(thermalImage);thermalImage=texture;Observation=r;State=Stage.Complete;
    Status=r.status=="indeterminate"?"판독 불가 · 현장 재확인 필요":r.status=="anomaly_observed"?"표면 온도 이상 후보 · CUI 확정 아님":"이번 합성 관측에서 이상 후보 미검출 · 안전 판정 아님";return true;
   }catch{return false;}
  }
  void RefreshObserver(){if(!observer)return;var sensor=tour.tourCamera;var desired=sensor.transform.position-sensor.transform.forward*2.5f+Vector3.up*1.1f;var delta=desired-sensor.transform.position;
   if(!Physics.SphereCast(sensor.transform.position,.07f,delta.normalized,out _,delta.magnitude,1<<8,QueryTriggerInteraction.Ignore)&&!Physics.CheckSphere(desired,.07f,1<<8)){
    observer.transform.position=desired;observer.transform.LookAt(sensor.transform.position+sensor.transform.forward*1.5f);observer.enabled=true;
   }else{observer.enabled=false;sensor.enabled=true;}
  }
  void Update(){if(!ExternalClock)Tick(Time.deltaTime);}
  void OnGUI(){if(!initialized)return;if(label==null){font=Font.CreateDynamicFontFromOSFont(new[]{"Malgun Gothic","Arial"},16);label=new GUIStyle(GUI.skin.label){font=font,fontSize=16,wordWrap=true};button=new GUIStyle(GUI.skin.button){font=font,fontSize=16};}
   if(!Displaying){if(GUI.Button(new Rect(12,105,390,30),"드론 열화상 시연 보기",button))Displaying=true;return;}
   GUI.depth=-120;var area=new Rect(12,140,Mathf.Min(570,Screen.width*.44f),Mathf.Max(300,Screen.height-400));var previousColor=GUI.color;GUI.color=new Color(.025f,.055f,.085f,1);GUI.DrawTexture(area,Texture2D.whiteTexture);GUI.color=previousColor;GUILayout.BeginArea(new Rect(area.x+10,area.y+8,area.width-20,area.height-16));scroll=GUILayout.BeginScrollView(scroll);
   GUILayout.Label("드론 열화상 · "+AssetId,label);GUILayout.Label("기존 공정 배관 모델 · 합성 온도 · 현장 실측 아님",label);GUI.enabled=!Busy;GUILayout.BeginHorizontal();inputAsset=GUILayout.TextField(inputAsset,40);if(GUILayout.Button("배관 적용",button))SelectAsset(inputAsset.Trim());GUILayout.EndHorizontal();GUI.enabled=true;GUILayout.Label(Status,label);
   if(GUILayout.Button(Displaying?"열화상 시연 시점 끄기":"열화상 시연 시점 보기",button)){Displaying=!Displaying;if(observer)observer.enabled=Displaying;}
   GUI.enabled=!Busy;GUILayout.BeginHorizontal();if(GUILayout.Button("기준 온도",button))Begin("normal");if(GUILayout.Button("국부 온도 이상",button))Begin("wet");if(GUILayout.Button("반사/저방사율",button))Begin("reflective");GUILayout.EndHorizontal();GUI.enabled=true;
   if(GUILayout.Button("열화상 중단 · 안전 복귀 요청",button))Cancel();
   if(rgbImage||thermalImage){if(GUILayout.Button(thermalView?"최근 촬영 RGB 보기":"최근 촬영 열화상 보기",button))thermalView=!thermalView;
    var image=thermalView&&thermalImage?thermalImage:rgbImage;if(image){var rect=GUILayoutUtility.GetAspectRect(320f/256);GUI.DrawTexture(rect,image,ScaleMode.ScaleToFit);
     if(thermalView&&thermalImage&&Observation?.findings!=null){var old=GUI.color;GUI.color=Color.yellow;foreach(var f in Observation.findings){if(f.bbox==null||f.bbox.Length!=4)continue;var q=new Rect(rect.x+rect.width*f.bbox[0]/320f,rect.y+rect.height*f.bbox[1]/256f,rect.width*(f.bbox[2]-f.bbox[0])/320f,rect.height*(f.bbox[3]-f.bbox[1])/256f);GUI.Box(q,"");}GUI.color=old;}
    }}
   if(Observation!=null){GUILayout.Label("겉보기 표면 온도 · 최대 "+Observation.maxC.ToString("F1")+"°C / 평균 "+Observation.meanC.ToString("F1")+"°C",label);GUILayout.Label("비교 영역 대비 ΔT "+Observation.deltaC.ToString("F1")+"°C · 색상 범위 10~100°C",label);GUILayout.Label(Observation.quality.message,label);}
   GUILayout.EndScrollView();GUILayout.EndArea();
  }
  void OnDestroy(){if(thermalImage)DestroyImmediate(thermalImage);if(rgbImage)DestroyImmediate(rgbImage);if(font)DestroyImmediate(font);}
 }
}
