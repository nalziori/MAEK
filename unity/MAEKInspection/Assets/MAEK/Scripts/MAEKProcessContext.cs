using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;

namespace MAEK {
 [Serializable] public class ProcessService {
  public string code,label,role,chain,inspection,followUp;
 }
 [Serializable] public class ProcessContextData {
  public int version;public string processName,processFlow,numericalScope,assumptions,scopeNote,missingSystems;
  public ProcessService[] services;
 }
 [Serializable] public class FollowUpRow {
  public string pipeId,service,role,status,action,workerContext,inspectionLimit,workPermissionStatus;public bool syntheticAsset;public int plannedImages,analysedImages,mappedFindings;
  public int scheduledImages,deferredImages;public string observationStatus,inspectionStatus,accessStatus;public string[] accessReasons;
  public string[] evidenceRequestIds;
 }
 [Serializable] public class FollowUpSet {
  public string scope="Evidence-based follow-up list; not risk ranking or defect confirmation";
  public FollowUpRow[] rows;
 }
 public sealed class MAEKProcessContext:MonoBehaviour {
  public TextAsset definitions,safetyDefinitions;public bool showDetails=true;
  public MAEKWorkerSafety WorkerSafety {get;private set;}=new MAEKWorkerSafety();bool showAccidents=true;int accidentIndex;
  public ProcessContextData Data {get;private set;}
  public bool CoreResultsOnly=false;
  MAEKPipeServices services;MAEKInspectionTour tour;
  readonly Dictionary<string,ProcessService> byService=new Dictionary<string,ProcessService>();
  readonly Dictionary<string,ServicePipe> byPipe=new Dictionary<string,ServicePipe>();
  GUIStyle label,button;Font font;Vector2 scroll;
  public void Initialize(){
   if(Data!=null)return;
   if(!definitions)throw new Exception("Missing process context");
   Data=JsonUtility.FromJson<ProcessContextData>(definitions.text);
   if(Data==null||Data.version!=1||Data.services==null)throw new Exception("Invalid process context");
   services=FindFirstObjectByType<MAEKPipeServices>();services.Initialize();
   foreach(var item in Data.services)byService.Add(item.code,item);
   foreach(var pipe in services.Data.pipes){if(!byService.ContainsKey(pipe.serviceCode))throw new Exception("Missing service role "+pipe.serviceCode);byPipe.Add(pipe.id,pipe);}
   tour=GetComponent<MAEKInspectionTour>();WorkerSafety.Initialize(safetyDefinitions,services.Data);
   // Repair display-only legacy text without rewriting frozen source catalogues.
   foreach(var item in services.Data.services){var context=byService[item.code];item.labelKo=context.label;item.route=context.chain;item.purpose=context.inspection;}
  }
  void Start(){Initialize();}
  void Update(){if(Input.GetKeyDown(KeyCode.P))showDetails=!showDetails;}
  public ProcessService ForPipe(string id){Initialize();if(!string.IsNullOrEmpty(id)&&byPipe.TryGetValue(id,out var pipe))return byService[pipe.serviceCode];var c=GetComponent<MAEKSupplementaryCircuits>()?.Circuit(id);return c==null?null:new ProcessService{code=c.id,label=c.label,role="reference_extension",chain=c.chain,inspection=c.limit,followUp=c.followUp};}
  public bool IsCore(string id){return ForPipe(id)?.role=="primary_inspection";}
  public int CountRole(string role){Initialize();return byPipe.Values.Count(p=>byService[p.serviceCode].role==role);}
  public static string RoleLabel(string role){switch(role){case "primary_inspection":return "주요 검사 후보";case "process_context":return "공정 설명 / 선택 검사";case "reference_extension":return "공개 참고 계통 / 별도 증설";case "training_only":return "훈련 전용";case "standalone_utility_demo":return "독립 유틸리티 시험대";default:return "전경";}}
  public string Caption(string id){var item=ForPipe(id);return item==null?Data.processName:item.label+" · "+RoleLabel(item.role)+" | "+item.chain;}
  public FollowUpSet FollowUps(){Initialize();tour.Initialize();var rows=new List<FollowUpRow>();
   foreach(var id in tour.Plan.pipeIds){var context=ForPipe(id);var outcomes=tour.Outcomes.Where(o=>o.pipeId==id).ToArray();var findings=tour.Findings.Where(f=>f.pipeId==id).ToArray();var coverage=tour.Coverage(id);int planned=coverage.plannedImages;
    bool candidate=tour.ValidObservations(id).Any(o=>o.status=="candidate");bool incomplete=coverage.inspectionStatus!="completed";
    string state=candidate?(incomplete?"candidate_incomplete":"candidate"):incomplete?(coverage.analysedImages==0?"inspection_deferred":"inspection_partial"):"no_rgb_candidate";
    string action=candidate?context.followUp:incomplete?"미관측/누락/가림/품질/연결 확인; 검사보류":"새 RGB 후보 없음; 두께·보온재 내부·균열 건전성 미확인";
    if(candidate&&incomplete)action+=" · 미완료/가림 촬영도 보완 · 검사보류";
    if(context.role=="training_only"||context.role=="standalone_utility_demo")action=RoleLabel(context.role)+" · "+action;
    var extra=GetComponent<MAEKSupplementaryCircuits>()?.Circuit(id);var safety=byPipe.ContainsKey(id)?WorkerSafety.ForService(byPipe[id].serviceCode):null;
    rows.Add(new FollowUpRow{pipeId=id,service=context.label,role=context.role,status=state,action=action,plannedImages=planned,analysedImages=coverage.analysedImages,scheduledImages=coverage.scheduledImages,deferredImages=coverage.deferredImages,observationStatus=coverage.observationStatus,inspectionStatus=coverage.inspectionStatus,accessStatus=coverage.accessStatus,accessReasons=coverage.accessReasons.Select(r=>r.Length>512?r.Substring(0,512):r).Distinct().Take(16).ToArray(),mappedFindings=findings.Length,evidenceRequestIds=outcomes.Select(o=>o.requestId).Distinct().ToArray(),workerContext=safety?.workerContext??extra?.workerContext,inspectionLimit=safety?.inspectionLimit??extra?.limit,workPermissionStatus="not_assessed",syntheticAsset=true});
   }
   return new FollowUpSet{rows=rows.ToArray()};
  }
  public void WriteFollowUps(string directory){if(string.IsNullOrEmpty(directory))return;File.WriteAllText(Path.Combine(directory,"follow_up.json"),JsonUtility.ToJson(FollowUps(),true));}
  public void Validate(){Initialize();if(byPipe.Count!=247||CountRole("primary_inspection")!=138||CountRole("process_context")!=98||CountRole("training_only")!=4||CountRole("standalone_utility_demo")!=7)throw new Exception("Process role coverage mismatch");if(ForPipe("UTIL-N002").role!="standalone_utility_demo"||ForPipe("BF1-H200").role!="process_context")throw new Exception("Misleading process role");}
  void OnGUI(){
   if(Data==null)return;if(label==null){font=Font.CreateDynamicFontFromOSFont(new[]{"Malgun Gothic","Arial"},14);label=new GUIStyle(GUI.skin.label){font=font,fontSize=14,wordWrap=true};button=new GUIStyle(GUI.skin.button){font=font,fontSize=14};}
   float y=tour&&tour.Active?200:170;float width=Mathf.Min(700,Screen.width*.58f);
   if(GUI.Button(new Rect(12,y,width,30),(showDetails?"접기":"펼치기")+" (P) | "+Data.processName,button))showDetails=!showDetails;
   if(!showDetails)return;float height=Mathf.Min(360,Screen.height-y-80);if(height<70)return;
   GUI.Box(new Rect(12,y+34,width,height),"");GUILayout.BeginArea(new Rect(24,y+40,width-24,height-12));scroll=GUILayout.BeginScrollView(scroll);
   GUILayout.Label(Data.processFlow,label);
   GUILayout.Label("배관 검사와 작업 안전 검토는 별도 · 실제 사고 현장을 복제한 모델 아님",label);
   if(GUILayout.Button(showAccidents?"사고 배관 확인 중 / 계통 안내로 전환":"계통 안내 중 / 사고 배관 확인",button))showAccidents=!showAccidents;
   if(showAccidents){accidentIndex=WorkerSafety.DrawCase(accidentIndex,label,button);GUILayout.Label("현재 촬영/선택 배관",label);}
   string id=tour&&tour.Active?tour.CurrentPipe:services.SelectedId;var item=ForPipe(id);
   if(item!=null){GUILayout.Label(id+" | "+item.label+" · "+RoleLabel(item.role),label);GUILayout.Label("흐름: "+item.chain,label);GUILayout.Label("후속 확인: "+item.followUp,label);if(byPipe.ContainsKey(id))WorkerSafety.DrawPipe(byPipe[id],label);else GUILayout.Label("공개 계통을 참고한 가상 증설 · 실제 사고 현장 아님 · 작업 허가 미판정",label);}
   GUILayout.Label("전체 247개 · 표시 그룹: 주요 138 / 공정 98 / 훈련 4 / 시험 7 · 위험 순위 아님",label);
   var extension=GetComponent<MAEKSupplementaryCircuits>();
   GUILayout.Label(extension&&extension.Selected?extension.Data.flowBasis:Data.numericalScope+"\n"+Data.assumptions,label);
   GUILayout.Label(Data.scopeNote,label);GUILayout.Label(Data.missingSystems,label);
   GUILayout.EndScrollView();GUILayout.EndArea();
  }
 }
}
