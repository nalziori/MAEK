using System;
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace MAEK.Editor {
 public static class BuildSafetyDemo {
  const string Scene="Assets/MAEK/Scenes/MAEKSafetyDemo.unity";
  static string Output=>Environment.GetEnvironmentVariable("MAEK_SAFETY_OUTPUT")??Path.GetFullPath("SafetyOutput");
  [Serializable] public class Check {public string name;public bool pass;}
  [Serializable] public class Report {public string scope="Unity editor integration with real scene colliders; synthetic safety inputs";public Check[] checks;}
  static readonly List<Check> checks=new List<Check>();
  static void Assert(string name,bool pass){checks.Add(new Check{name=name,pass=pass});if(!pass)throw new Exception(name);}
  [MenuItem("MAEK/Safety/Create and open safety demo")]
  public static void Create() {
   EditorSceneManager.OpenScene("Assets/MAEK/Scenes/MAEKInspectionDemo.unity");
   var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();
   if(!tour)throw new Exception("Missing MAEK tour");
   tour.autoStart=false;if(!tour.GetComponent<MAEKSafetyDemo>())tour.gameObject.AddComponent<MAEKSafetyDemo>();
   EditorSceneManager.SaveScene(tour.gameObject.scene,Scene);AssetDatabase.SaveAssets();
  }
  static MAEKSafetyDemo Load(){EditorSceneManager.OpenScene(Scene);Physics.SyncTransforms();var s=UnityEngine.Object.FindFirstObjectByType<MAEKSafetyDemo>();s.Initialize();s.ExternalClock=true;s.Tour.externalClock=true;return s;}
  static void ReachInspection(MAEKSafetyDemo s){s.SetNormal();Assert("manual approval",s.Approve());s.RequestStart();for(int i=0;i<4000&&s.Phase==MAEKSafetyDemo.FlightPhase.Launching;i++)s.Tick(.1f);Assert("continuous launch reaches inspection",s.CanInspect);}
  [MenuItem("MAEK/Safety/Verify safety integration")]
  public static void Verify() {
   checks.Clear();Directory.CreateDirectory(Output);
   try {
    var s=Load();var t=s.Tour;
    t.Begin();Assert("unknown inputs block all start paths",!t.Active);
    s.SetNormal();t.Begin();Assert("normal inputs alone cannot clear latch",!t.Active);
    ReachInspection(s);
    var position=t.tourCamera.transform.position;t.Advance(.1f);s.Tick(.1f);
    Assert("normal route moves",Vector3.Distance(position,t.tourCamera.transform.position)>0);
    s.SetInput(2,true);position=t.tourCamera.transform.position;var session=t.SessionDirectory;int captures=t.Captures.Count;
    t.SetPaused(false);t.Advance(.1f);t.Begin();
    Assert("alarm blocks pause and restart bypass",t.Paused&&t.SessionDirectory==session&&t.tourCamera.transform.position==position);
    bool captureBlocked=false;try{t.MakeCapture("test",out var capture);}catch(InvalidOperationException){captureBlocked=true;}
    Assert("alarm blocks actual inspection capture",captureBlocked&&t.Captures.Count==captures);
    bool resultBlocked=false;try{t.ApplyResult(new InspectionCapture(),"{}");}catch(InvalidOperationException){resultBlocked=true;}
    Assert("late analysis cannot apply during trip",resultBlocked);
    s.SetNormal();Assert("alarm clear retains latch",s.Gate.Latched&&!s.CanInspect);Assert("airborne reset rejected",!s.Approve());
    for(int i=0;i<8000&&!s.Grounded&&s.Phase!=MAEKSafetyDemo.FlightPhase.EmergencyHold;i++)s.Tick(.1f);
    Assert("reverse route and landing reach ground",s.Grounded&&s.Phase==MAEKSafetyDemo.FlightPhase.AwaitingApproval);
    t.SetPaused(false);t.Advance(.1f);Assert("grounded remains blocked before approval",!s.CanInspect&&t.Paused);
    Assert("explicit grounded approval accepted",s.Approve());Assert("approval does not take off",s.Grounded&&!s.CanInspect);
    s.RequestStart();Assert("separate start launches",s.Phase==MAEKSafetyDemo.FlightPhase.Launching);
    // A new obstacle must stop egress rather than be removed or crossed.
    s.Tick(.1f);s.SetInput(7,false);position=t.tourCamera.transform.position;
    var obstacle=GameObject.CreatePrimitive(PrimitiveType.Cube);obstacle.layer=8;obstacle.transform.position=position;Physics.SyncTransforms();s.Tick(.1f);
    Assert("new obstacle stops emergency movement",s.Phase==MAEKSafetyDemo.FlightPhase.EmergencyHold&&t.tourCamera.transform.position==position);
    UnityEngine.Object.DestroyImmediate(obstacle);s.SetNormal();s.Tick(.1f);Assert("cleared obstacle does not auto resume",s.Phase==MAEKSafetyDemo.FlightPhase.EmergencyHold&&!s.Approve());
    Assert("event log exists",File.Exists(s.LogPath)&&File.ReadAllLines(s.LogPath).Length>10);
    foreach(int signal in new[]{0,2,3,6,7,8}) {
     s=Load();ReachInspection(s);position=s.Tour.tourCamera.transform.position;
     s.SetInput(signal,signal<3?(bool?)true:signal==8?null:(bool?)false);
     var expected=signal==0?SafetyResponse.GasDiversion:signal==2?SafetyResponse.PressureDiversion:signal==3?SafetyResponse.PermitReturn:signal==6?SafetyResponse.PersonnelDiversion:signal==7?SafetyResponse.LostLinkReturn:SafetyResponse.HoldUnknown;
     Assert("signal "+signal+" distinct response",s.Response==expected&&!s.CanInspect);
     if(signal==8){for(int i=0;i<20;i++)s.Tick(.1f);Assert("missing data holds position",s.Phase==MAEKSafetyDemo.FlightPhase.EmergencyHold&&s.Tour.tourCamera.transform.position==position);s.SetNormal();s.Tick(.1f);Assert("fresh data does not auto resume",s.Phase==MAEKSafetyDemo.FlightPhase.EmergencyHold);continue;}
     for(int i=0;i<8000&&!s.Grounded&&s.Phase!=MAEKSafetyDemo.FlightPhase.EmergencyHold;i++)s.Tick(.1f);
     Assert("signal "+signal+" reaches selected landing",s.Grounded);
     if(signal==6)Assert("personnel excludes A and lands outside occupied column",s.SelectedPad!="A"&&Vector2.Distance(new Vector2(s.BaseLanding.x,s.BaseLanding.z),new Vector2(s.Tour.tourCamera.transform.position.x,s.Tour.tourCamera.transform.position.z))>5);
     Assert("signal "+signal+" needs ground reapproval",s.Gate.Latched&&!s.CanInspect);
    }
    s=Load();ReachInspection(s);s.AlternatePadsOccupied=true;s.SetInput(6,false);position=s.Tour.tourCamera.transform.position;s.Tick(.1f);
    Assert("all landing zones occupied blocks movement",s.Phase==MAEKSafetyDemo.FlightPhase.EmergencyHold&&!s.Grounded&&position==s.Tour.tourCamera.transform.position);
    s=Load();ReachInspection(s);s.SetInput(3,false);for(int i=0;i<10;i++)s.Tick(.1f);s.SetInput(6,false);
    Assert("personnel during return replans away from A",s.SelectedPad!="A"&&s.Phase==MAEKSafetyDemo.FlightPhase.Returning);
    for(int i=0;i<8000&&!s.Grounded&&s.Phase!=MAEKSafetyDemo.FlightPhase.EmergencyHold;i++)s.Tick(.1f);
    Assert("diverted return lands at alternate",s.Grounded&&s.SelectedPad!="A");
    s=Load();ReachInspection(s);position=s.Tour.tourCamera.transform.position;s.TriggerRupture();
    Assert("rupture anchored to catalogue pipe not drone",s.AccidentActive&&!string.IsNullOrEmpty(s.AccidentPipeId)&&Vector3.Distance(s.AccidentPosition,position)>1);
    Assert("A cordoned and B occupied choose C or D",s.PadCount>=3&&s.PadOccupied(1)&&(s.SelectedPad=="C"||s.SelectedPad=="D"));
    s.SetNormal();Assert("normal button cannot bypass active accident",!s.CanInspect&&!s.Approve());
    for(int i=0;i<8000&&!s.Grounded&&s.Phase!=MAEKSafetyDemo.FlightPhase.EmergencyHold;i++)s.Tick(.1f);
    Assert("rupture diversion lands",s.Grounded);Assert("active accident blocks ground approval",!s.Approve());
    s.EndAccident();Assert("accident closure keeps manual reset latch",!s.AccidentActive&&s.Gate.Latched&&!s.CanInspect);Assert("closed accident can be manually approved",s.Approve());
    s=Load();ReachInspection(s);s.TriggerRupture(false);position=s.Tour.tourCamera.transform.position;
    for(int i=0;i<30;i++)s.Tick(.1f);s.SetNormal();s.EndAccident();s.Approve();s.RequestStart();
    Assert("control lost cannot auto return or fake landing",s.Phase==MAEKSafetyDemo.FlightPhase.ControlLost&&!s.Grounded&&!s.CanInspect&&position==s.Tour.tourCamera.transform.position);
    s=Load();ReachInspection(s);s.TriggerRupture();
    for(int p=2;p<s.PadCount;p++)s.SetPadOccupied(p,true);
    Assert("rupture with no available pads holds",s.Phase==MAEKSafetyDemo.FlightPhase.EmergencyHold&&!s.Grounded);
    s=Load();s.TriggerRupture();s.SetNormal();s.RequestStart();Assert("ground accident blocks launch",s.Grounded&&!s.Tour.Active&&!s.Approve());
    File.WriteAllText(Path.Combine(Output,"unity_safety_verification.json"),JsonUtility.ToJson(new Report{checks=checks.ToArray()},true));
    Debug.Log("MAEK_SAFETY_PASS "+checks.Count);
   } catch {File.WriteAllText(Path.Combine(Output,"unity_safety_verification.json"),JsonUtility.ToJson(new Report{checks=checks.ToArray()},true));throw;}
  }
  [MenuItem("MAEK/Safety/Verify and build safety player %#F9")]
  public static void Run() {
   try {Create();Verify();EditorSceneManager.OpenScene(Scene);BuildStandaloneTeam.Configure();
    PlayerSettings.productName="MAEK Accident Response V3";PlayerSettings.resizableWindow=true;
    string exe=Path.Combine(Output,"PlayerV3","MAEK_Player.exe");Directory.CreateDirectory(Path.GetDirectoryName(exe));
    var result=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{Scene},locationPathName=exe,target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});
    if(result.summary.result!=BuildResult.Succeeded)throw new Exception("Safety build failed: "+result.summary.result);
    Debug.Log("MAEK_SAFETY_BUILD_PASS "+exe);if(Application.isBatchMode)EditorApplication.Exit(0);
   }catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}
  }
 }
}
