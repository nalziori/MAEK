using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace MAEK.Editor {
 [InitializeOnLoad]
 public static class VerifyInspectionPlayMode {
  const string Key="MAEK.InspectionPlayVerify";
  static double started,lastLog;static bool recordingTest;static string recordingPath;static Report catalogue;static int acknowledgedBefore;
  [Serializable] class Report {public string status,reason,session,recording;public int captures,findings,recordedFrames,coveredPipes,expectedCaptures,collisionSteps,runtimeScenarios,evaluationAcks,unsentEvaluations,cataloguePipes,scheduledPipes,requiredCaptures,deferredCaptures,deferredPipes,partialPipes;public bool siteFirst;public bool completed;public float maxMovementStep,maxRotationStep;}
  static VerifyInspectionPlayMode(){EditorApplication.playModeStateChanged+=Changed;}
  public static void Run() {
   EditorSceneManager.OpenScene("Assets/MAEK/Scenes/MAEKInspectionDemo.unity");
   SessionState.SetBool(Key,true);EditorApplication.EnterPlaymode();
  }
  static void Changed(PlayModeStateChange state) {
   if(!SessionState.GetBool(Key,false))return;
   if(state==PlayModeStateChange.EnteredPlayMode){started=EditorApplication.timeSinceStartup;lastLog=started;recordingTest=false;recordingPath="";catalogue=null;EditorApplication.update+=Tick;}
  }
  static void Tick() {
   if(!EditorApplication.isPlaying)return;
   var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();
   if(EditorApplication.timeSinceStartup-started>3600){Finish(tour,"Play mode timeout");return;}
   if(!tour)return;
   if(catalogue!=null){
    var cases=tour.GetComponent<MAEKInspectionScenarios>();var link=tour.GetComponent<MAEKDashboardLink>();
    tour.verificationStepsPerUpdate=120;
    if(cases.SuiteRunning||link.EvaluationPending)return;
    catalogue.runtimeScenarios=cases.Evaluations.Count;catalogue.evaluationAcks=link.EvaluationAcknowledged-acknowledgedBefore;catalogue.unsentEvaluations=link.UnsentEvaluations;
    Finish(tour,catalogue.runtimeScenarios!=11||catalogue.evaluationAcks!=11||catalogue.unsentEvaluations!=0||cases.Evaluations.Any(e=>!e.guardPass)?"Runtime scenario/evaluation delivery failed":"");return;
   }
   if(!tour.Active)return;
   tour.verificationStepsPerUpdate=120;
   if(EditorApplication.timeSinceStartup-lastLog>12){lastLog=EditorApplication.timeSinceStartup;Debug.Log("MAEK_PLAY_PROGRESS leg="+tour.Leg+" pipes="+tour.AnalysedPipes+" captures="+tour.Captures.Count+" findings="+tour.Findings.Count);}
   if(tour.Captures.Count>0&&!recordingTest){
    recordingTest=true;var recorder=tour.Recorder;recorder.width=640;recorder.height=360;recorder.fps=12;
    recorder.StartRecording(tour);recordingPath=recorder.OutputDirectory;
    File.WriteAllBytes(Path.Combine(BuildInspectionTour.Output,"play_mode_evidence.png"),tour.CapturePixels(640,360));
   }
   if(recordingTest&&tour.Recorder.Recording&&tour.Recorder.FrameCount>=24)tour.Recorder.StopRecording();
   if(tour.Blocked){Finish(tour,"Unexpected route obstruction");return;}
   if(tour.Complete){var process=tour.GetComponent<MAEKProcessContext>();try{if(!process)throw new Exception("Missing process context");process.Validate();var follow=process.FollowUps();if(follow.rows.Length!=247||follow.rows.Any(r=>r.evidenceRequestIds.Length!=r.scheduledImages||r.workPermissionStatus!="not_assessed"||!r.syntheticAsset||string.IsNullOrEmpty(r.workerContext)||r.deferredImages>0&&r.inspectionStatus=="completed"||r.analysedImages==0&&r.status=="no_rgb_candidate"))throw new Exception("Incorrect observation/deferred follow-up evidence");}catch(Exception e){Finish(tour,e.Message);return;}Finish(tour,tour.AnalysisErrors.Count>0?string.Join(";",tour.AnalysisErrors):
    tour.Captures.Count!=tour.Plan.expectedCaptures||tour.Outcomes.Count!=tour.Plan.expectedCaptures?"Incomplete planned captures":tour.Plan.pipeIds.Length!=247?"Catalogue entries missing":
    tour.Captures.Any(c=>c.visibleTargetSamples<1)?"Target occluded in capture":
    !tour.Captures.Select(c=>c.sampleId).SequenceEqual(tour.Plan.points.Where(p=>p.pipeId!="").Select(p=>p.sampleId))?"Capture order mismatch":
    tour.MaxMovementStep>1.201f||tour.MaxRotationStep>6.05f?"Discontinuous movement":
    !tour.Plan.access.Any(a=>!a.accessible)?"No inaccessible observations were retained":
    tour.Recorder.FrameCount<24?"Runtime recorder did not write 24 frames":"");}
  }
  static Report ReadReport(MAEKInspectionTour tour,string reason) {
   return new Report{siteFirst=tour&&tour.Plan.siteFirst,cataloguePipes=tour?.Plan?.pipeIds.Length??0,scheduledPipes=tour?.Plan?.visits.Count(v=>v.captures>0)??0,requiredCaptures=tour?.Plan?.requiredCaptures??0,deferredCaptures=tour?.Plan?.access.Count(a=>!a.accessible)??0,deferredPipes=tour?.Plan?.visits.Count(v=>v.captures==0)??0,partialPipes=tour?.Plan?.visits.Count(v=>v.captures>0&&v.captures<v.requiredCaptures)??0,status=reason==""?"PASS":"FAIL",reason=reason,captures=tour?tour.Captures.Count:0,
    findings=tour?tour.Findings.Count:0,completed=tour&&tour.Complete,session=tour?tour.SessionDirectory:"",
    recording=recordingPath,recordedFrames=tour&&tour.Recorder?tour.Recorder.FrameCount:0,
    expectedCaptures=tour?.Plan?.expectedCaptures??0,coveredPipes=tour?.AnalysedPipes??0,
    collisionSteps=tour?.CollisionSteps??0,maxMovementStep=tour?.MaxMovementStep??0,maxRotationStep=tour?.MaxRotationStep??0};
  }
  static void Finish(MAEKInspectionTour tour,string reason) {
   if(reason==""&&catalogue==null){catalogue=ReadReport(tour,reason);acknowledgedBefore=tour.GetComponent<MAEKDashboardLink>().EvaluationAcknowledged;tour.GetComponent<MAEKInspectionScenarios>().StartSuite();Debug.Log("MAEK_PLAY_SCENARIOS_BEGIN");return;}
   EditorApplication.update-=Tick;SessionState.SetBool(Key,false);
   var report=catalogue??ReadReport(tour,reason);report.status=reason==""?"PASS":"FAIL";report.reason=reason;
   File.WriteAllText(Path.Combine(BuildInspectionTour.Output,"play_mode_report.json"),JsonUtility.ToJson(report,true));
   Debug.Log("MAEK_PLAY_"+report.status+" "+reason);
   if(Application.isBatchMode)EditorApplication.Exit(reason==""?0:1);else EditorApplication.ExitPlaymode();
  }
 }
}
