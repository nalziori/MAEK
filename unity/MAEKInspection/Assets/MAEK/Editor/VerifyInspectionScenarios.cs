using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
namespace MAEK.Editor {
 public static class VerifyInspectionScenarios {
  static readonly string Output=Path.GetFullPath("../../visualization/inspection_scenarios");
  [Serializable] class Report {public string status,scope;public float droneVisualRadius;public int scenarios,falsePositives,falseNegatives,controlChecks;public ScenarioEvaluation[] evaluations;}
  sealed class Client:WebClient {protected override WebRequest GetWebRequest(Uri address){var r=base.GetWebRequest(address);r.Timeout=5000;return r;}}
  public static void Run(){try{Verify();if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  static void Require(bool condition,string message){if(!condition)throw new Exception("SCENARIOS: "+message);}
  static string Post(Client client,string url,string body){try{return client.UploadString(url,body);}catch(WebException e){if(e.Response!=null){using(var reader=new StreamReader(e.Response.GetResponseStream()))throw new Exception(url+": "+reader.ReadToEnd(),e);}throw;}}
  static int VerifyCommands(Client client,MAEKDashboardLink link,MAEKInspectionTour tour,MAEKVirtualDrone drone){
   string session=Path.GetFileName(tour.SessionDirectory);
   var queued=JsonUtility.FromJson<DashboardCommand>(Post(client,link.BaseUrl+"/api/control","{\"command\":\"pause\"}"));
   string url=link.BaseUrl+"/api/control?sessionId="+session;
   var delivered=JsonUtility.FromJson<DashboardCommands>(client.DownloadString(url)).commands.Single(c=>c.commandId==queued.commandId);
   Require(JsonUtility.FromJson<DashboardCommands>(client.DownloadString(url)).commands.Any(c=>c.commandId==queued.commandId),"Unacknowledged command was lost");
   var ack=link.ApplyCommand(delivered,session);Require(ack.status=="applied"&&tour.Paused,"Pause command was not applied");
   Post(client,link.BaseUrl+"/api/ack",JsonUtility.ToJson(ack));Post(client,link.BaseUrl+"/api/ack",JsonUtility.ToJson(ack));
   link.ApplyCommand(new DashboardCommand{commandId=Guid.NewGuid().ToString("N"),command="resume"},session);Require(!tour.Paused,"Resume command was not applied");
   var toggle=new DashboardCommand{commandId=Guid.NewGuid().ToString("N"),command="view_toggle"};bool previous=drone.chaseView;
   link.ApplyCommand(toggle,session);link.ApplyCommand(toggle,session);Require(drone.chaseView!=previous,"Retried toggle executed twice");
   var stale=link.ApplyCommand(new DashboardCommand{commandId=Guid.NewGuid().ToString("N"),command="view_toggle"},"retired-session");Require(stale.status=="error"&&drone.chaseView!=previous,"Stale command affected current session");
   drone.chaseView=previous;drone.RefreshPose();return 5;
  }
  public static void Verify(){
   Directory.CreateDirectory(Output);EditorSceneManager.OpenScene("Assets/MAEK/Scenes/MAEKInspectionDemo.unity");
   var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();tour.externalClock=true;tour.Initialize();
   var scenarios=tour.GetComponent<MAEKInspectionScenarios>();var link=tour.GetComponent<MAEKDashboardLink>();link.publish=false;link.Initialize();
   var drone=tour.GetComponent<MAEKVirtualDrone>();drone.EnsureRig();Require(drone.VisualRadius()<=MAEKVirtualDrone.EnvelopeRadius&&MAEKVirtualDrone.EnvelopeRadius<tour.Plan.radius,"Body exceeds frozen collision envelope");
   float radius=drone.VisualRadius();int controlChecks=0;var rows=new List<ScenarioEvaluation>();
   using(var client=new Client()){client.Encoding=System.Text.Encoding.UTF8;client.Headers[HttpRequestHeader.ContentType]="application/json";
    tour.Begin();drone.RefreshPose();Post(client,link.BaseUrl+"/api/telemetry",JsonUtility.ToJson(link.Snapshot(true)));controlChecks=VerifyCommands(client,link,tour,drone);tour.End();
    foreach(var scenario in scenarios.Data.scenarios){
     scenarios.StartCase(scenario.id);drone.RefreshPose();
     Post(client,link.BaseUrl+"/api/telemetry",JsonUtility.ToJson(link.Snapshot(true)));
     if(scenario.id=="S01"){
      drone.chaseView=true;drone.RefreshPose();var display=drone.DisplayCamera;
      if(display!=tour.tourCamera)CaptureFactoryPhotos.Capture(display,Output,"virtual_drone",display.transform.position,drone.ModelRoot.transform.position,60);
      drone.chaseView=false;drone.RefreshPose();
     }
     for(int step=0;step<20000&&!tour.Complete&&!tour.Blocked&&tour.AnalysisErrors.Count==0;step++){
      tour.Advance(.1f);drone.RefreshPose();
      if(tour.PendingPipe!=""){
       try{string pipe=tour.PendingPipe;var request=tour.MakeCapture(pipe,out var context);string json=Post(client,tour.endpoint,JsonUtility.ToJson(request));tour.ApplyResult(context,json);}
       catch(Exception e){tour.Failure(e.Message);}finally{tour.ConsumePendingForVerification();}
       Post(client,link.BaseUrl+"/api/telemetry",JsonUtility.ToJson(link.Snapshot(true)));
      }
     }
     Require(!tour.Blocked,"Collision in "+scenario.id);Require(tour.Complete||tour.AnalysisErrors.Count>0,"Scenario did not finish "+scenario.id);
     // A setup/access deferral is evaluated synchronously by StartCase; never evaluate it twice.
     var row=scenarios.Running?scenarios.Evaluate():scenarios.Evaluations.Single(e=>e.runId==scenarios.RunId);rows.Add(row);Post(client,link.BaseUrl+"/api/evaluation",JsonUtility.ToJson(row));
     Require(row.guardPass,"Workflow/evidence guard failed "+scenario.id+" observed="+row.observed);
     if(row.detectionApplicable&&(scenario.id=="S01"||scenario.id=="S02"||scenario.id=="S03"||scenario.id=="S04"))Require(row.detectionPass,"Detection expectation failed "+scenario.id+" observed="+row.observed);
     Require(tour.GetComponent<MAEKProcessContext>().FollowUps().rows.All(r=>r.workPermissionStatus=="not_assessed"),"Work permission regression");
     Debug.Log("MAEK_SCENARIO_PASS "+row.scenarioId+" "+row.classification+" captures="+row.captures+" findings="+row.findings);
    }
   }
   scenarios.Cancel();Require(tour.Plan.pipeIds.Length==247,"Original catalogue not restored");
   var report=new Report{status="PASS",scope="Fixed-site accessible observations only; inaccessible cases explicitly deferred. Actual RGB pixels/HTTP; expected labels only for evaluation. No fabricated measurements or forced visibility.",droneVisualRadius=radius,scenarios=rows.Count,controlChecks=controlChecks,falsePositives=rows.Count(r=>r.classification=="false_positive"),falseNegatives=rows.Count(r=>r.classification=="false_negative"),evaluations=rows.ToArray()};
   File.WriteAllText(Path.Combine(Output,"verification.json"),JsonUtility.ToJson(report,true));Debug.Log("MAEK_SCENARIO_SUITE_PASS count="+rows.Count);
  }
 }
}
