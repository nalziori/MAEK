using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
namespace MAEK {
 [Serializable] public class InspectionScenario {public string id,title,pipeId,mode,expected,description,capability;}
 [Serializable] public class InspectionScenarioSet {public int version;public string scope;public InspectionScenario[] scenarios;}
 [Serializable] public class ScenarioEvaluation {
  public string sessionId,runId,scenarioId,title,pipeId,expected,observed,classification;
  public string observationStatus,inspectionStatus,accessStatus;public string[] accessReasons;public int requiredCaptures,scheduledCaptures;
  public bool guardPass,detectionPass,detectionApplicable;public int findings,captures;public string[] errors;public string workPermissionStatus="not_assessed";
 }
 [DefaultExecutionOrder(-150)]
 public sealed class MAEKInspectionScenarios:MonoBehaviour {
  public TextAsset definitions;public InspectionScenarioSet Data {get;private set;}
  public InspectionScenario Current {get;private set;}public string RunId {get;private set;}="";
  public bool Running {get;private set;}public bool SuiteRunning {get;private set;}public bool Finished {get;private set;}
  public bool CameraAvailable=>Current?.mode!="camera_offline";
  public float Exposure=>Current?.mode=="low_light"?.005f:1;
  public string Guidance=>Current?.mode=="ut_required"?"UT 미입력 · 내부 균열 판정 보류":Current?.mode=="ir_required"?"IR/PEC 미입력 · 보온 이상 판정 보류":"";
  public readonly List<ScenarioEvaluation> Evaluations=new List<ScenarioEvaluation>();
  MAEKInspectionTour tour;MAEKSupplementaryCircuits extra;TextAsset caseRoute;string normalEndpoint;
  readonly Dictionary<Renderer,Material[]> originals=new Dictionary<Renderer,Material[]>();
  readonly List<Material> materials=new List<Material>();GameObject occluder;int suiteIndex;float nextCase=-1;bool selecting;TourPlan cataloguePlan;
  public void Initialize(){if(Data!=null)return;tour=GetComponent<MAEKInspectionTour>();extra=GetComponent<MAEKSupplementaryCircuits>();Data=JsonUtility.FromJson<InspectionScenarioSet>(definitions.text);normalEndpoint=tour.endpoint;
   if(Data?.version!=1||Data.scenarios==null||Data.scenarios.Length<9||Data.scenarios.Select(s=>s.id).Distinct().Count()!=Data.scenarios.Length)throw new Exception("Invalid inspection scenarios");
  }
  void Start(){Initialize();}
  public void BeforeTourBegin(TextAsset route){
   if(selecting||!caseRoute)return;
   if(route!=caseRoute){Cancel(false);return;}
   Running=true;Finished=false;SuiteRunning=false;RunId=Guid.NewGuid().ToString("N");nextCase=-1;
   tour.endpoint=Current?.mode=="analysis_offline"?"http://127.0.0.1:1/analyse":normalEndpoint;
  }
  public void Cancel(bool restoreRoute=true){
   if(Data==null)return;Running=false;SuiteRunning=false;Finished=false;nextCase=-1;
   if(restoreRoute&&tour.Active)tour.End();RestoreAppearance();Current=null;RunId="";tour.endpoint=normalEndpoint;
   if(restoreRoute)extra.Select(false,false);
   if(caseRoute){if(tour.routeData!=caseRoute)DestroyImmediate(caseRoute);caseRoute=null;}
  }
  void RestoreAppearance(){foreach(var p in originals)if(p.Key)p.Key.sharedMaterials=p.Value;originals.Clear();foreach(var m in materials)if(m)DestroyImmediate(m);materials.Clear();if(occluder)DestroyImmediate(occluder);occluder=null;}
  public void Stop(){Running=false;SuiteRunning=false;Finished=false;nextCase=-1;if(tour.Active)tour.End();}
  public void StartSuite(){Initialize();Cancel();Evaluations.Clear();SuiteRunning=true;suiteIndex=0;StartCase(Data.scenarios[0].id,true);}
  public void StartCase(string id,bool suite=false){
   Initialize();tour.Initialize();var selected=Data.scenarios.Single(s=>s.id==id);bool keepSuite=suite;
   if(tour.routeData!=caseRoute)cataloguePlan=tour.Plan;
   var source=cataloguePlan;
   Cancel();SuiteRunning=keepSuite;Current=selected;RunId=Guid.NewGuid().ToString("N");selecting=true;
   try{
    bool supplementary=selected.pipeId.StartsWith("O2-")||selected.pipeId.StartsWith("SINTER-");
    if(source==null||!source.pipeIds.Contains(selected.pipeId)){extra.Select(supplementary,false);source=tour.Plan;cataloguePlan=source;}
    int first=Array.FindIndex(source.points,p=>p.pipeId==selected.pipeId);
    var sourceVisit=source.visits?.FirstOrDefault(v=>v.pipeId==selected.pipeId);
    if(first<0){StartDeferred(selected,source,sourceVisit,"no_accessible_capture");return;}
    while(first>0&&source.points[first-1].routePipeId==selected.pipeId&&source.points[first-1].phase=="inspection")first--;
    int start=first-1;while(start>0&&Vector3.Distance(source.points[start].position,source.points[first].position)<.001f)start--;start=Mathf.Max(0,start);
    var points=new List<TourPoint>{Copy(source.points[start],false,selected.pipeId)};
    for(int i=start+1;i<first;i++)points.Add(Copy(source.points[i],false,selected.pipeId));
    int last=Array.FindLastIndex(source.points,p=>p.pipeId==selected.pipeId);
    for(int i=first;i<=last;i++){
     var p=Copy(source.points[i],source.points[i].pipeId==selected.pipeId,selected.pipeId);p.sampleId=source.points[i].sampleId;points.Add(p);
    }
    int captures=points.Count(p=>p.pipeId!="");if(captures<1){StartDeferred(selected,source,sourceVisit,"no_accessible_capture");return;}
    int required=Mathf.Max(captures,RequiredForVisit(source,sourceVisit,selected.pipeId));
    var plan=new TourPlan{siteFirst=source.siteFirst,radius=source.radius,bodyRadius=source.bodyRadius,clearanceMargin=source.clearanceMargin,requiredCaptures=required,access=source.access?.Where(a=>a.pipeId==selected.pipeId).ToArray(),basis="Separate scenario session; preserved original path slice, pixel observations only; no complete-surface/flight-dynamics claim",pipeIds=new[]{selected.pipeId},points=points.ToArray(),expectedCaptures=captures,visits=new[]{new PipeVisit{pipeId=selected.pipeId,firstLeg=1,lastLeg=points.Count-1,captures=captures,requiredCaptures=required,accessStatus=sourceVisit?.accessStatus,accessReasons=sourceVisit?.accessReasons}},transfers=new[]{new PipeTransfer{fromPipe="SCENARIO_START",toPipe=selected.pipeId,firstLeg=0,lastLeg=1}}};
    for(int i=1;i<points.Count;i++)plan.distanceM+=Vector3.Distance(points[i-1].position,points[i].position);
    caseRoute=new TextAsset(JsonUtility.ToJson(plan,true));tour.SetRoute(caseRoute);
    if(!ApplyAppearance(selected)){StartDeferred(selected,source,sourceVisit,"scenario_geometry_unavailable");return;}
    if(selected.mode=="occlusion"&&!PlaceOccluder(points.First(p=>p.pipeId!=""))){StartDeferred(selected,source,sourceVisit,"occlusion_setup_unavailable");return;}
    Physics.SyncTransforms();for(int i=1;i<points.Count;i++)if(!tour.SegmentClear(points[i-1].position,points[i].position)){StartDeferred(selected,source,sourceVisit,"blocked segment="+i);return;}
    if(selected.mode=="analysis_offline")tour.endpoint="http://127.0.0.1:1/analyse";
    tour.Begin();File.WriteAllText(Path.Combine(tour.SessionDirectory,"scenario_route.json"),JsonUtility.ToJson(plan,true));Running=true;nextCase=-1;
   }catch{Cancel();throw;}finally{selecting=false;}
  }
  static int RequiredForVisit(TourPlan source,PipeVisit visit,string id)=>Mathf.Max(1,Mathf.Max(visit?.requiredCaptures??0,Mathf.Max(visit?.captures??0,source.access?.Count(a=>a.pipeId==id)??0)));
  void StartDeferred(InspectionScenario selected,TourPlan source,PipeVisit visit,string reason){
   RestoreAppearance();
   var start=Copy(source.points[0],false,selected.pipeId);
   int required=RequiredForVisit(source,visit,selected.pipeId);
   var plan=new TourPlan{siteFirst=source.siteFirst,radius=source.radius,bodyRadius=source.bodyRadius,clearanceMargin=source.clearanceMargin,
    basis="Scenario deferred by current site layout; no observations fabricated",pipeIds=new[]{selected.pipeId},points=new[]{start},
    requiredCaptures=required,expectedCaptures=0,access=source.access?.Where(a=>a.pipeId==selected.pipeId).ToArray(),
    visits=new[]{new PipeVisit{pipeId=selected.pipeId,captures=0,requiredCaptures=required,accessStatus="deferred",accessReasons=(visit?.accessReasons??Array.Empty<string>()).Concat(new[]{reason}).ToArray()}}};
   var old=caseRoute;caseRoute=new TextAsset(JsonUtility.ToJson(plan,true));tour.SetRoute(caseRoute);if(old)DestroyImmediate(old);tour.Begin();
   tour.DeferInspection(selected.pipeId,reason);Running=true;nextCase=-1;
   File.WriteAllText(Path.Combine(tour.SessionDirectory,"scenario_route.json"),JsonUtility.ToJson(plan,true));Evaluate();
  }
  static TourPoint Copy(TourPoint p,bool capture,string id)=>new TourPoint{position=p.position,target=p.target,speed=Mathf.Min(p.speed,5),dwell=capture?.5f:0,pipeId=capture?id:"",routePipeId=id,sampleId=p.sampleId,phase=capture?"inspection":"transit",sourceIndex=p.sourceIndex};
  bool ApplyAppearance(InspectionScenario s){
   var target=FindObjectsByType<MAEKPipeService>(FindObjectsSortMode.None).FirstOrDefault(p=>p.lineId==s.pipeId)?.gameObject;
   if(!target)target=FindObjectsByType<MAEKSupplementaryLine>(FindObjectsSortMode.None).FirstOrDefault(p=>p.lineId==s.pipeId)?.gameObject;
   if(!target)return false;
   var m=new Material(Shader.Find("MAEK/WeatheredSteel")){name="Temporary scenario exterior"};m.color=s.mode=="corrosion"?new Color(.42f,.19f,.07f):s.mode=="paint"?new Color(.8f,.32f,.06f):new Color(.52f,.55f,.57f);m.SetFloat("_Rust",s.mode=="corrosion"?.7f:0);m.SetFloat("_Metallic",.2f);m.SetFloat("_Glossiness",.2f);materials.Add(m);
   foreach(var r in target.GetComponentsInChildren<Renderer>()){originals[r]=r.sharedMaterials;r.sharedMaterials=r.sharedMaterials.Select(_=>m).ToArray();}return true;
  }
  bool PlaceOccluder(TourPoint p){
   var direction=(p.target-p.position).normalized;
   foreach(float fraction in new[]{.35f,.45f,.55f,.65f,.75f}){
    var g=GameObject.CreatePrimitive(PrimitiveType.Cube);g.name="Temporary scenario occlusion panel";g.layer=8;g.transform.SetPositionAndRotation(Vector3.Lerp(p.position,p.target,fraction),Quaternion.LookRotation(direction));g.transform.localScale=new Vector3(.7f,.7f,.03f);
    var m=new Material(Shader.Find("Standard")){color=new Color(.27f,.29f,.31f)};materials.Add(m);g.GetComponent<Renderer>().sharedMaterial=m;Physics.SyncTransforms();var c=g.GetComponent<Collider>();bool clash=false;
    foreach(var other in Physics.OverlapBox(c.bounds.center,c.bounds.extents,Quaternion.identity,1<<8))if(other!=c&&Physics.ComputePenetration(c,c.transform.position,c.transform.rotation,other,other.transform.position,other.transform.rotation,out _,out float depth)&&depth>.015f){clash=true;break;}
    if(!clash){occluder=g;return true;}DestroyImmediate(g);
   }
   return false;
  }
  public ScenarioEvaluation Evaluate(){
   if(!Running||Current==null)throw new InvalidOperationException("No active scenario");
   var c=Current;var coverage=tour.Coverage(c.pipeId);bool candidate=tour.Findings.Any(f=>f.pipeId==c.pipeId);string observed=coverage.scheduledImages==0?"inspection_deferred":tour.Blocked?"blocked":tour.AnalysisErrors.Count>0?(CameraAvailable?"analysis_error":"camera_error"):tour.Outcomes.Any(o=>o.status=="not_visible")?"not_visible":tour.Outcomes.Any(o=>o.status=="quality_recheck")?"quality_recheck":coverage.inspectionStatus!="completed"?(candidate?"candidate_incomplete":"inspection_deferred"):candidate?"corrosion_candidate":"no_corrosion_candidate";
   if((c.mode=="ut_required"||c.mode=="ir_required")&&tour.AnalysisErrors.Count==0&&coverage.inspectionStatus=="completed"&&tour.Captures.Count==tour.Plan.expectedCaptures&&tour.Outcomes.Count==tour.Plan.expectedCaptures&&tour.Outcomes.All(o=>o.visibleTargetSamples>0&&o.status!="quality_recheck"))observed="additional_sensor_required";
   bool applicable=coverage.analysedImages>0&&(candidate||coverage.inspectionStatus=="completed")&&(c.expected=="corrosion_candidate"||c.expected=="no_corrosion_candidate");string classification=applicable?(candidate?(c.expected=="corrosion_candidate"?"true_positive":"false_positive"):(coverage.inspectionStatus!="completed"?"inspection_deferred":c.expected=="corrosion_candidate"?"false_negative":"true_negative")):observed;
   bool scheduledObserved=tour.Captures.Count==coverage.scheduledImages&&tour.Outcomes.Count==coverage.scheduledImages&&coverage.analysedImages==coverage.scheduledImages&&tour.Outcomes.All(MAEKInspectionTour.Usable)&&tour.AnalysisErrors.Count==0;
   bool honestPartial=(c.mode=="corrosion"||c.mode=="clean"||c.mode=="paint"||c.mode=="ut_required"||c.mode=="ir_required")&&coverage.inspectionStatus!="completed"&&(observed=="inspection_deferred"||observed=="candidate_incomplete")&&scheduledObserved;
   bool guard=coverage.scheduledImages==0?coverage.observationStatus=="unobserved"&&tour.Captures.Count==0&&tour.Outcomes.Count==0&&!candidate:!tour.Blocked&&(applicable?scheduledObserved:honestPartial||observed==c.expected);
   var row=new ScenarioEvaluation{sessionId=Path.GetFileName(tour.SessionDirectory),runId=RunId,scenarioId=c.id,title=c.title,pipeId=c.pipeId,expected=c.expected,observed=observed,classification=classification,observationStatus=coverage.observationStatus,inspectionStatus=coverage.inspectionStatus,accessStatus=coverage.accessStatus,accessReasons=coverage.accessReasons.Select(r=>r.Length>512?r.Substring(0,512):r).Distinct().Take(16).ToArray(),requiredCaptures=coverage.plannedImages,scheduledCaptures=coverage.scheduledImages,guardPass=guard,detectionApplicable=applicable,detectionPass=classification=="true_positive"||classification=="true_negative",findings=tour.Findings.Count,captures=tour.Captures.Count,errors=tour.AnalysisErrors.ToArray()};
   Evaluations.Add(row);File.WriteAllText(Path.Combine(tour.SessionDirectory,"scenario_evaluation.json"),JsonUtility.ToJson(row,true));GetComponent<MAEKDashboardLink>()?.QueueEvaluation(row);Running=false;Finished=true;
   if(tour.Active)tour.End();tour.endpoint=normalEndpoint;if(SuiteRunning)nextCase=Time.unscaledTime+1.5f;return row;
  }
  void Update(){
   if(Input.GetKeyDown(KeyCode.T)||Input.GetKeyDown(KeyCode.E))Cancel();
   for(int i=0;i<Mathf.Min(9,Data.scenarios.Length);i++)if(Input.GetKeyDown((KeyCode)((int)KeyCode.Alpha1+i)))StartCase(Data.scenarios[i].id);
   if(Running&&(tour.Complete||tour.AnalysisErrors.Count>0||tour.Blocked))Evaluate();
   if(SuiteRunning&&!Running&&nextCase>=0&&Time.unscaledTime>=nextCase&&!GetComponent<MAEKDashboardLink>().EvaluationPending){if(++suiteIndex>=Data.scenarios.Length){SuiteRunning=false;nextCase=-1;}else StartCase(Data.scenarios[suiteIndex].id,true);}
  }
  void OnDestroy(){RestoreAppearance();if(caseRoute)DestroyImmediate(caseRoute);}
 }
}
