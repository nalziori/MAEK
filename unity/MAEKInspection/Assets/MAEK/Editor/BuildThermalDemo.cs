using System;
using System.IO;
using System.Net;
using System.Collections.Generic;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEditor.Build.Reporting;
namespace MAEK.Editor {
 public static class BuildThermalDemo {
  const string Scene="Assets/MAEK/Scenes/MAEKThermalDemo.unity";
  static string Output=>Path.GetFullPath("ThermalOutput");
  [Serializable] class Approach{public string stage,status;public Vector3 position,hover;}
  [Serializable] class Check {public string name;public bool pass;}
  [Serializable] class Report {public string scope="existing catalogue pipe surface capture, synthetic assumed temperature, main dashboard";public Check[] checks;}
  [Serializable] class Event {public string sessionId,runId,requestId,assetId,startedAt,stage;public int sequence;}
  static readonly List<Check> checks=new List<Check>();
  static void Assert(string n,bool p){checks.Add(new Check{name=n,pass=p});if(!p)throw new Exception(n);}
  static string Post(string path,string json){var bytes=System.Text.Encoding.UTF8.GetBytes(json);var r=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:8894"+path);r.Method="POST";r.ContentType="application/json";r.Timeout=30000;r.ContentLength=bytes.Length;using(var s=r.GetRequestStream())s.Write(bytes,0,bytes.Length);using(var response=r.GetResponse())using(var reader=new StreamReader(response.GetResponseStream()))return reader.ReadToEnd();}
  static Material Material(string name,Color color){var path="Assets/MAEK/Generated/"+name+".mat";var m=AssetDatabase.LoadAssetAtPath<Material>(path);if(!m){m=new Material(Shader.Find("Unlit/Color")){color=color};AssetDatabase.CreateAsset(m,path);}return m;}
  static GameObject Part(Transform root,string name,Vector3 at,Vector3 size,Material m,PrimitiveType shape=PrimitiveType.Cube){var o=GameObject.CreatePrimitive(shape);o.name=name;o.layer=8;o.transform.SetParent(root,false);o.transform.localPosition=at;o.transform.localScale=size;o.GetComponent<Renderer>().sharedMaterial=m;return o;}
  [MenuItem("MAEK/Thermal/Create and open integrated sensor demo")]
  public static void Create(){
   BuildWorkerUTDemo.Create();var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();tour.Initialize();var home=tour.Plan.points[0].position;
   var thermal=tour.gameObject.AddComponent<MAEKThermalDemo>();thermal.Initialize();if(!thermal.SelectAsset("BF1-Q005"))throw new Exception(thermal.Status);
   if(UnityEngine.Object.FindObjectsByType<MAEKPipeService>(FindObjectsSortMode.None).Length!=247)throw new Exception("Original catalogue changed");
   var observer=new GameObject("Thermal demonstration observer (camera cuts, not flight evidence)").AddComponent<Camera>();observer.depth=70;observer.fieldOfView=55;observer.nearClipPlane=.05f;observer.enabled=false;thermal.observer=observer;
   EditorSceneManager.SaveScene(tour.gameObject.scene,Scene);AssetDatabase.SaveAssets();
  }
  static MAEKThermalDemo Load(){EditorSceneManager.OpenScene(Scene);var t=UnityEngine.Object.FindFirstObjectByType<MAEKThermalDemo>();t.Initialize();t.ExternalClock=true;var s=t.GetComponent<MAEKSafetyDemo>();s.ExternalClock=true;s.Tour.externalClock=true;return t;}
  static void Advance(MAEKThermalDemo t){var s=t.GetComponent<MAEKSafetyDemo>();for(int i=0;i<30000&&t.Busy&&t.State!=MAEKThermalDemo.Stage.Analysing;i++){s.Tick(.1f);t.Tick(.1f);}File.WriteAllText(Path.Combine(Output,"approach_diagnostic.json"),JsonUtility.ToJson(new Approach{stage=t.State.ToString(),status=t.Status,position=s.Tour.tourCamera.transform.position,hover=t.hover},true));Assert("continuous collision-checked approach and visible capture",t.State==MAEKThermalDemo.Stage.Analysing&&t.LastCapture!=null);}
  static string Submit(MAEKThermalDemo t){var r=t.LastCapture;var e=new Event{assetId=r.assetId,sessionId=r.sessionId,runId=r.runId,requestId=r.requestId,startedAt=r.startedAt,stage="Launching",sequence=0};Post("/api/thermal/event",JsonUtility.ToJson(e));e.stage="Analysing";e.sequence=r.sequence;Post("/api/thermal/event",JsonUtility.ToJson(e));return Post("/api/thermal/capture",JsonUtility.ToJson(r));}
  [MenuItem("MAEK/Thermal/Verify and build thermal V6 %#F7")]
  public static void Run(){Directory.CreateDirectory(Output);checks.Clear();try{
   Create();var t=Load();t.Begin("wet");Assert("unknown safety blocks thermal start",!t.Busy&&t.Observation==null);
   foreach(var condition in new[]{"normal","wet","reflective"}){
    t=Load();var s=t.GetComponent<MAEKSafetyDemo>();s.SetNormal();Assert("ground approval",s.Approve());t.Begin(condition);Advance(t);
    var answer=Submit(t);Assert(condition+" response matches capture hashes",t.Accept(answer,t.Generation));
    string expected=condition=="normal"?"no_anomaly_observed":condition=="wet"?"anomaly_observed":"indeterminate";
    Assert(condition+" observation-only detector status",t.Observation.status==expected);
    Assert("synthetic origin and no work permission",t.Observation.synthetic&&t.Observation.workPermissionStatus=="not_assessed");
    File.WriteAllText(Path.Combine(Output,condition+"_response.json"),answer);File.WriteAllText(Path.Combine(Output,condition+"_capture.json"),JsonUtility.ToJson(t.LastCapture));
   }
   t=Load();var safety=t.GetComponent<MAEKSafetyDemo>();safety.SetNormal();safety.Approve();t.Begin("wet");Advance(t);string response=Submit(t);int generation=t.Generation;t.Cancel();Assert("late response after cancellation rejected",!t.Accept(response,generation)&&t.Observation==null);
   t=Load();safety=t.GetComponent<MAEKSafetyDemo>();safety.SetNormal();safety.Approve();t.Begin("wet");Advance(t);response=Submit(t);Assert("wrong pipe response rejected",!t.Accept(response.Replace("BF1-Q005","BF1-G004"),t.Generation));Assert("wrong RGB hash rejected",!t.Accept(response.Replace(t.LastCapture.rgbSha256,new string('0',64)),t.Generation));
   safety.TriggerRupture();t.Tick(.1f);Assert("rupture cancels thermal judgement",t.State==MAEKThermalDemo.Stage.Interrupted&&t.Observation==null);
   t=Load();safety=t.GetComponent<MAEKSafetyDemo>();safety.SetNormal();safety.Approve();t.Begin("wet");Advance(t);
   var block=GameObject.CreatePrimitive(PrimitiveType.Cube);block.layer=8;block.transform.position=(t.aim+t.GetComponent<MAEKSafetyDemo>().Tour.tourCamera.transform.position)*.5f;block.transform.localScale=new Vector3(2,3,2);Physics.SyncTransforms();bool rejected=false;try{t.Capture();}catch(InvalidOperationException){rejected=true;}Assert("occluded target never becomes completed inspection",rejected);UnityEngine.Object.DestroyImmediate(block);
   EditorSceneManager.OpenScene(Scene);BuildStandaloneTeam.Configure();PlayerSettings.productName="MAEK Thermal and UT V6";PlayerSettings.resizableWindow=true;
   var output=Path.Combine(Output,"Player","MAEK_Player.exe");Directory.CreateDirectory(Path.GetDirectoryName(output));var build=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{Scene},locationPathName=output,target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});Assert("Windows thermal build",build.summary.result==BuildResult.Succeeded);Debug.Log("MAEK_THERMAL_PROCESS_PASS "+checks.Count);
  }catch(Exception e){Debug.LogException(e);throw;}finally{File.WriteAllText(Path.Combine(Output,"verification.json"),JsonUtility.ToJson(new Report{checks=checks.ToArray()},true));}}
 }
}
