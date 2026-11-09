using System;
using System.IO;
using System.Linq;
using UnityEngine;
namespace MAEK {
 public sealed class MAEKStandaloneRuntime:MonoBehaviour {
  MAEKInspectionTour tour;bool verify,supplementary;float started;string report;Report data=new Report();
  [Serializable] class Report {public string status,reason,session,supplementarySession;public int pipes,captures,findings,collisionSteps,supplementaryPipes,supplementaryCaptures,supplementaryFindings,supplementaryCollisionSteps,recordedFrames;public float maxMovementStep,supplementaryMaxMovementStep;}
  static string Argument(string key){var a=Environment.GetCommandLineArgs();int i=Array.IndexOf(a,key);return i>=0&&i+1<a.Length?a[i+1]:"";}
  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
  static void Boot(){if(Application.isEditor)return;var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();if(!tour)return;
   var runtime=new GameObject("MAEK standalone lifecycle").AddComponent<MAEKStandaloneRuntime>();runtime.tour=tour;runtime.started=Time.realtimeSinceStartup;
   string endpoint=Argument("-maek-endpoint");if(endpoint!="")tour.endpoint=endpoint;
   runtime.verify=Environment.GetCommandLineArgs().Contains("-maek-verify");runtime.report=Argument("-maek-report");
   QualitySettings.vSyncCount=0;Application.targetFrameRate=30;
  }
  void Update(){if(!verify)return;if(Time.realtimeSinceStartup-started>1800){Finish("Verification timeout");return;}
   if(tour.Active)tour.verificationStepsPerUpdate=120;
   if(tour.Blocked){Finish("Unexpected collision");return;}if(!tour.Complete)return;
   int expected=supplementary?17:247,captures=supplementary?17:771;
   string reason=tour.AnalysisErrors.Count>0?string.Join(";",tour.AnalysisErrors):tour.AnalysedPipes!=expected||tour.Captures.Count!=captures?"Incomplete capture coverage":tour.Captures.Any(c=>c.visibleTargetSamples<1)?"Invisible capture target":tour.MaxMovementStep>1.201f?"Discontinuous flight":"";
   try{var context=tour.GetComponent<MAEKProcessContext>();context.Validate();var follow=context.FollowUps();if(follow.rows.Length!=expected||follow.rows.Any(r=>r.status.Contains("incomplete")||r.workPermissionStatus!="not_assessed"||string.IsNullOrEmpty(r.workerContext)))reason="Incomplete follow-up evidence";
    if(!supplementary&&!tour.Findings.Any(f=>f.pipeId=="BF1-W002"))reason="Reference finding missing";
    if(supplementary&&!tour.Findings.Any())reason="Supplementary RGB surface mapping missing";
   }catch(Exception e){reason=e.Message;}
   if(reason!=""){Finish(reason);return;}
   if(!supplementary){data.session=tour.SessionDirectory;data.pipes=tour.AnalysedPipes;data.captures=tour.Captures.Count;data.findings=tour.Findings.Count;data.collisionSteps=tour.CollisionSteps;data.maxMovementStep=tour.MaxMovementStep;supplementary=true;tour.GetComponent<MAEKSupplementaryCircuits>().Select(true);return;}
   data.supplementarySession=tour.SessionDirectory;data.supplementaryPipes=tour.AnalysedPipes;data.supplementaryCaptures=tour.Captures.Count;data.supplementaryFindings=tour.Findings.Count;data.supplementaryCollisionSteps=tour.CollisionSteps;data.supplementaryMaxMovementStep=tour.MaxMovementStep;
   try{tour.Recorder.width=640;tour.Recorder.height=360;tour.Recorder.StartRecording(tour);for(int i=0;i<24;i++)tour.Recorder.CaptureFrame();tour.Recorder.StopRecording();data.recordedFrames=tour.Recorder.FrameCount;}catch(Exception e){Finish(e.Message);return;}
   Finish("");
  }
  void Finish(string reason){verify=false;data.status=reason==""?"PASS":"FAIL";data.reason=reason;if(report!="")File.WriteAllText(report,JsonUtility.ToJson(data,true));Debug.Log("MAEK_STANDALONE_"+data.status+" "+reason);Application.Quit(reason==""?0:1);}
  void OnGUI(){if(GUI.Button(new Rect(Screen.width-112,Screen.height-44,100,32),"Exit MAEK"))Application.Quit();}
 }
}
