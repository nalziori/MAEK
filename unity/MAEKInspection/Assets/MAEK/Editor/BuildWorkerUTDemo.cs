using System;
using System.IO;
using System.Collections.Generic;
using System.Net;
using System.Text;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEditor.Build.Reporting;
using UnityEngine;
namespace MAEK.Editor {
 public static class BuildWorkerUTDemo {
  const string Scene="Assets/MAEK/Scenes/MAEKWorkerUTDemo.unity";
  static string Output=>Path.GetFullPath("WorkerUTOutput");
  [Serializable] class Check {public string name;public bool pass;}
  [Serializable] class Report {public string scope="worker staged contact plus real loopback Python pitting MLP on frozen synthetic examples";public Check[] checks;}
  static readonly List<Check> checks=new List<Check>();
  static void CheckThat(string name,bool pass){checks.Add(new Check{name=name,pass=pass});if(!pass)throw new Exception(name);}
  [MenuItem("MAEK/Worker UT/Create and open worker UT demo")]
  public static void Create(){
   BuildSafetyDemo.Create();var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();
   var worker=tour.gameObject.AddComponent<MAEKWorkerUT>();worker.devicePrefab=AssetDatabase.LoadAssetAtPath<GameObject>("Assets/MAEK/Generated/MAEKPortableUT.prefab");
   EditorSceneManager.SaveScene(tour.gameObject.scene,Scene);AssetDatabase.SaveAssets();
  }
  static MAEKWorkerUT Load(){EditorSceneManager.OpenScene(Scene);var worker=UnityEngine.Object.FindFirstObjectByType<MAEKWorkerUT>();worker.ExternalClock=true;worker.Initialize();var s=worker.GetComponent<MAEKSafetyDemo>();s.ExternalClock=true;s.Tour.externalClock=true;return worker;}
  static MAEKWorkerUT StartContact(bool poor=false){var w=Load();Debug.Log("UT_STATION "+w.Status+" actor="+(w.Actor!=null)+" placement="+MAEKMaintenanceInspector.LastPlacementStatus);CheckThat("worker and physically reachable pipe station",w.Ready&&w.Actor);var s=w.GetComponent<MAEKSafetyDemo>();s.SetNormal();s.Approve();w.SimulatePoorContact=poor;w.Begin();for(int i=0;i<4000&&w.Busy&&w.State!=MAEKWorkerUT.Stage.Contact;i++)w.Tick(.1f);CheckThat("worker walks to contact without crossing colliders",w.State==MAEKWorkerUT.Stage.Contact);CheckThat("reference surface and couplant complete before contact",w.ReferenceChecked&&w.SurfacePrepared&&w.CouplantApplied);return w;}
  static string Predict(MAEKWorkerUT worker){
   var data=JsonUtility.ToJson(new MAEKWorkerUT.Request{requestId=worker.PendingRequestId,pipeId=worker.PipeId,sample=worker.Sample});
   var bytes=Encoding.UTF8.GetBytes(data);var req=(HttpWebRequest)WebRequest.Create(worker.Endpoint);req.Method="POST";req.ContentType="application/json";req.Timeout=20000;req.ContentLength=bytes.Length;using(var stream=req.GetRequestStream())stream.Write(bytes,0,bytes.Length);using(var response=req.GetResponse())using(var reader=new StreamReader(response.GetResponseStream()))return reader.ReadToEnd();
  }
  [MenuItem("MAEK/Worker UT/Verify and build worker UT %#F8")]
  public static void Run(){Directory.CreateDirectory(Output);checks.Clear();try {
   Create();var w=Load();w.Begin();CheckThat("unknown approval blocks UT",!w.Busy&&w.Measurement==null);
   w=Load();var gate=w.GetComponent<MAEKSafetyDemo>();gate.SetNormal();gate.Approve();w.SimulateReferenceFailure=true;w.Begin();
   for(int i=0;i<40;i++)w.Tick(.1f);CheckThat("failed reference blocks walking and result",w.State==MAEKWorkerUT.Stage.Deferred&&!w.ReferenceChecked&&w.Measurement==null);
   foreach(var stage in new[]{MAEKWorkerUT.Stage.ReferenceCheck,MAEKWorkerUT.Stage.SurfacePreparation,MAEKWorkerUT.Stage.Couplant}){
    w=Load();gate=w.GetComponent<MAEKSafetyDemo>();gate.SetNormal();gate.Approve();w.Begin();
    for(int i=0;i<4000&&w.Busy&&w.State!=stage;i++)w.Tick(.1f);
    CheckThat("procedure reaches "+stage,w.State==stage&&w.Measurement==null&&w.PendingRequestId=="");
    gate.TriggerRupture();w.Tick(.1f);CheckThat("accident cancels "+stage,w.State==MAEKWorkerUT.Stage.Interrupted&&w.Measurement==null);
   }
   w=StartContact(true);for(int i=0;i<30;i++)w.Tick(.1f);CheckThat("poor contact never creates result",w.State==MAEKWorkerUT.Stage.Deferred&&w.Measurement==null);
   w=StartContact();for(int i=0;i<30;i++)w.Tick(.1f);CheckThat("contact dwell reaches analysis",w.State==MAEKWorkerUT.Stage.Analysing);int gen=w.Generation;string id=w.PendingRequestId;var result=Predict(w);
   CheckThat("real Python response accepted",w.Accept(result,id,gen)&&w.State==MAEKWorkerUT.Stage.Complete&&w.Measurement.wave.Length==4096);
   CheckThat("synthetic origin and no permission inference",w.Measurement.synthetic&&w.Measurement.workPermissionStatus=="not_assessed");
   w=StartContact();for(int i=0;i<30;i++)w.Tick(.1f);id=w.PendingRequestId;gen=w.Generation;result=Predict(w);w.GetComponent<MAEKSafetyDemo>().TriggerRupture();w.Tick(.1f);
   CheckThat("rupture cancels worker UT",w.State==MAEKWorkerUT.Stage.Interrupted&&w.Measurement==null);CheckThat("late response after accident rejected",!w.Accept(result,id,gen));
   w=StartContact();for(int i=0;i<30;i++)w.Tick(.1f);id=w.PendingRequestId;gen=w.Generation;result=Predict(w).Replace("be4be1f82633378c803ff3112d43738ad89b928778c1ba69033c738a624d1e6d",new string('0',64));CheckThat("wrong source hash rejected",!w.Accept(result,id,gen)&&w.Measurement==null);
   EditorSceneManager.OpenScene(Scene);BuildStandaloneTeam.Configure();PlayerSettings.productName="MAEK Worker UT V5";PlayerSettings.resizableWindow=true;
   var output=Path.Combine(Output,"Player","MAEK_Player.exe");Directory.CreateDirectory(Path.GetDirectoryName(output));var build=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{Scene},locationPathName=output,target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});CheckThat("Windows build",build.summary.result==BuildResult.Succeeded);Debug.Log("MAEK_WORKER_UT_V5_PASS "+checks.Count);
  }catch(Exception e){Debug.LogException(e);throw;}finally{File.WriteAllText(Path.Combine(Output,"verification.json"),JsonUtility.ToJson(new Report{checks=checks.ToArray()},true));}}
 }
}
