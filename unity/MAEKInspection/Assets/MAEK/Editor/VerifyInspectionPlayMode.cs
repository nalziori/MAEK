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
  static double started,lastLog;static bool recordingTest;static string recordingPath;
  [Serializable] class Report {public string status,reason,session,recording;public int captures,findings,recordedFrames,coveredPipes,expectedCaptures,collisionSteps;public bool completed;public float maxMovementStep,maxRotationStep;}
  static VerifyInspectionPlayMode(){EditorApplication.playModeStateChanged+=Changed;}
  public static void Run() {
   EditorSceneManager.OpenScene("Assets/MAEK/Scenes/MAEKInspectionDemo.unity");
   SessionState.SetBool(Key,true);EditorApplication.EnterPlaymode();
  }
  static void Changed(PlayModeStateChange state) {
   if(!SessionState.GetBool(Key,false))return;
   if(state==PlayModeStateChange.EnteredPlayMode){started=EditorApplication.timeSinceStartup;lastLog=started;recordingTest=false;recordingPath="";EditorApplication.update+=Tick;}
  }
  static void Tick() {
   if(!EditorApplication.isPlaying)return;
   var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();
   if(EditorApplication.timeSinceStartup-started>3600){Finish(tour,"Play mode timeout");return;}
   if(!tour||!tour.Active)return;
   tour.verificationStepsPerUpdate=120;
   if(EditorApplication.timeSinceStartup-lastLog>12){lastLog=EditorApplication.timeSinceStartup;Debug.Log("MAEK_PLAY_PROGRESS leg="+tour.Leg+" pipes="+tour.AnalysedPipes+" captures="+tour.Captures.Count+" findings="+tour.Findings.Count);}
   if(tour.Findings.Any(f=>f.pipeId=="BF1-W002")&&!recordingTest){
    recordingTest=true;var recorder=tour.Recorder;recorder.width=640;recorder.height=360;recorder.fps=12;
    recorder.StartRecording(tour);recordingPath=recorder.OutputDirectory;
    File.WriteAllBytes(Path.Combine(BuildInspectionTour.Output,"play_mode_evidence.png"),tour.CapturePixels(640,360));
   }
   if(recordingTest&&tour.Recorder.Recording&&tour.Recorder.FrameCount>=24)tour.Recorder.StopRecording();
   if(tour.Blocked){Finish(tour,"Unexpected route obstruction");return;}
   if(tour.Complete){var process=tour.GetComponent<MAEKProcessContext>();try{if(!process)throw new Exception("Missing process context");process.Validate();var follow=process.FollowUps();if(follow.rows.Length!=247||follow.rows.Any(r=>r.status=="incomplete"||r.status=="candidate_incomplete"||r.evidenceRequestIds.Length!=r.plannedImages))throw new Exception("Incomplete follow-up evidence");}catch(Exception e){Finish(tour,e.Message);return;}Finish(tour,tour.AnalysisErrors.Count>0?string.Join(";",tour.AnalysisErrors):
    tour.Captures.Count!=tour.Plan.expectedCaptures||tour.Outcomes.Count!=tour.Plan.expectedCaptures?"Incomplete planned captures":tour.AnalysedPipes!=247?"Expected 247 analysed pipes":
    tour.Captures.Any(c=>c.visibleTargetSamples<1)?"Target occluded in capture":
    !tour.Captures.Select(c=>c.sampleId).SequenceEqual(tour.Plan.points.Where(p=>p.pipeId!="").Select(p=>p.sampleId))?"Capture order mismatch":
    tour.MaxMovementStep>1.201f||tour.MaxRotationStep>6.05f?"Discontinuous movement":
    !tour.Findings.Any(f=>f.pipeId=="BF1-W002")?"Missing mapped RGB finding":
    tour.Recorder.FrameCount<24?"Runtime recorder did not write 24 frames":"");}
  }
  static void Finish(MAEKInspectionTour tour,string reason) {
   EditorApplication.update-=Tick;SessionState.SetBool(Key,false);
   var report=new Report{status=reason==""?"PASS":"FAIL",reason=reason,captures=tour?tour.Captures.Count:0,
    findings=tour?tour.Findings.Count:0,completed=tour&&tour.Complete,session=tour?tour.SessionDirectory:"",
    recording=recordingPath,recordedFrames=tour&&tour.Recorder?tour.Recorder.FrameCount:0,
    expectedCaptures=tour?.Plan?.expectedCaptures??0,coveredPipes=tour?.AnalysedPipes??0,
    collisionSteps=tour?.CollisionSteps??0,maxMovementStep=tour?.MaxMovementStep??0,maxRotationStep=tour?.MaxRotationStep??0};
   File.WriteAllText(Path.Combine(BuildInspectionTour.Output,"play_mode_report.json"),JsonUtility.ToJson(report,true));
   Debug.Log("MAEK_PLAY_"+report.status+" "+reason);
   if(Application.isBatchMode)EditorApplication.Exit(reason==""?0:1);else EditorApplication.ExitPlaymode();
  }
 }
}
