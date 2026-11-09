using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using MAEK.Simulation;
using MAEK.Tests;
namespace MAEK.Editor {
 [Serializable] public class FurnaceReport {public string status,scope;public List<PhysicsCheck> checks;public double massResidualKg,energyResidualJ,liquidKg,tapKgS,runnerM3,receivedM3;}
 public static class BuildFurnaceScene {
  const string Root="Assets/MAEK";
  [MenuItem("MAEK/Build and verify furnace physics")]
  public static void Run(){try{Build();if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  public static void Build(){
   string reportDir=Path.GetFullPath(Path.Combine(Application.dataPath,"../../../visualization"));Directory.CreateDirectory(reportDir);
   var checks=FurnacePhysicsChecks.Run();Action<string,bool,string> check=(name,pass,detail)=>checks.Add(new PhysicsCheck{name=name,pass=pass,detail=detail});
   if(checks.Any(c=>!c.pass))throw new Exception("Numerical checks failed: "+string.Join("; ",checks.Where(c=>!c.pass).Select(c=>c.name+" "+c.detail)));
   var scene=EditorSceneManager.OpenScene(Root+"/Scenes/MAEKDroneInspection.unity");
   string cfg=Root+"/Source/furnace_config.json";if(!File.Exists(cfg))File.WriteAllText(cfg,JsonUtility.ToJson(new FurnaceConfig(),true));AssetDatabase.ImportAsset(cfg,ImportAssetOptions.ForceSynchronousImport);
   string matPath=Root+"/Generated/Materials/FurnaceSection.mat";var template=AssetDatabase.LoadAssetAtPath<Material>(matPath);var shader=Shader.Find("MAEK/FurnaceSection");if(shader==null)throw new Exception("Section shader not imported");
   if(template==null){template=new Material(shader);AssetDatabase.CreateAsset(template,matPath);}template.SetFloat("_SectionZ",18);template.SetFloat("_Section",0);
   var host=new GameObject("MAEK furnace reaction and liquid-flow simulation");var simulation=host.AddComponent<MAEKFurnaceSimulation>();simulation.configuration=AssetDatabase.LoadAssetAtPath<TextAsset>(cfg);simulation.sectionTemplate=template;
   var camera=new GameObject("Furnace process section camera").AddComponent<Camera>();camera.enabled=false;camera.nearClipPlane=.04f;camera.farClipPlane=1300;camera.fieldOfView=58;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.12f,.17f,.22f);simulation.processCamera=camera;simulation.startInProcessView=true;
   simulation.Initialize();simulation.SetProcessView(true);simulation.Advance(180);
   var model=simulation.Models[0];
   var expected=File.ReadAllLines(Path.Combine(reportDir,"furnace_physics_trace.csv"))[181].Split(',');
   check("Unity and Blender trace agree at 180 seconds",Math.Abs(model.LiquidIronKg-double.Parse(expected[2],System.Globalization.CultureInfo.InvariantCulture))<.01&&Math.Abs(model.Channel.VolumeM3-double.Parse(expected[10],System.Globalization.CultureInfo.InvariantCulture))<1e-6,"Identical solver, inputs and 30-second opening time");
   bool framed=true;foreach(var p in new[]{new Vector3(-62,51,18),new Vector3(-62,3.2f,18),new Vector3(-62,3.19f,47.7f)}){var v=camera.WorldToViewportPoint(p);if(v.z<=0||v.x<.03f||v.x>.97f||v.y<.03f||v.y>.97f)framed=false;}
   check("furnace and runner fit process camera",framed,"Top, hearth and receiving end within camera frame");check("section visual follows solved hearth level",Math.Abs(simulation.Baths[0].localScale.y-model.HeadM)<1e-5,"Rendered height equals mass/(density*effective hearth area)");
   check("runner visual follows all finite-volume cells",simulation.SurfaceCells[0].Select((t,i)=>Math.Abs(t.localScale.y-Math.Max(.00001,model.Channel.Depth[i]))<1e-5).All(x=>x),"48 calculated depths per runner");
   check("connected melt reaches collection vessel",model.Channel.OutletM3>0&&model.TappedKg>0,"Hearth -> taphole -> runner -> receiving vessel");
   check("process view owns active camera",camera.enabled&&simulation.ProcessView&&!UnityEngine.Object.FindFirstObjectByType<MAEKWalkthrough>().enabled&&!UnityEngine.Object.FindFirstObjectByType<MAEKDroneInspection>().enabled,"No competing walk/drone controls");
   check("section hides occluding conveyors",UnityEngine.Object.FindObjectsByType<MAEKAssetInfo>(FindObjectsSortMode.None).Where(i=>i.assetId=="BF1.CONVEYOR"||i.assetId=="BF2.CONVEYOR").All(i=>!i.GetComponent<Renderer>().enabled),"Render-only hiding while retaining colliders");
   check("section does not remove physical environment colliders",UnityEngine.Object.FindObjectsByType<MeshCollider>(FindObjectsSortMode.None).Length==323,"Original 323 mesh colliders retained");
   // Verify each previously generated route still clears the imported environment.
   var routes=JsonUtility.FromJson<DroneRouteSet>(File.ReadAllText(Root+"/Source/drone_routes.json"));UnityEngine.Physics.SyncTransforms();int mask=1<<8;
   foreach(var route in routes.routes){bool safe=true;for(int k=0;k<route.waypoints.Length;k++){var p=MAEKDroneInspection.V(route.waypoints[k].position);if(UnityEngine.Physics.CheckSphere(p,route.radius,mask,QueryTriggerInteraction.Ignore)){safe=false;break;}if(k>0){var a=MAEKDroneInspection.V(route.waypoints[k-1].position);var d=p-a;if(d.magnitude>.00001f&&UnityEngine.Physics.SphereCast(a,route.radius,d.normalized,out var hit,d.magnitude,mask,QueryTriggerInteraction.Ignore)){safe=false;break;}}}check("retained drone "+route.id,safe,"Existing environment collision policy unchanged");}
   if(SystemInfo.graphicsDeviceType!=UnityEngine.Rendering.GraphicsDeviceType.Null){
    var rt=new RenderTexture(1400,900,24);camera.targetTexture=rt;camera.Render();var previous=RenderTexture.active;RenderTexture.active=rt;var image=new Texture2D(1400,900,TextureFormat.RGB24,false);image.ReadPixels(new Rect(0,0,1400,900),0,0);image.Apply();File.WriteAllBytes(Path.Combine(reportDir,"unity_furnace_physics.png"),image.EncodeToPNG());RenderTexture.active=previous;camera.targetTexture=null;rt.Release();UnityEngine.Object.DestroyImmediate(rt);UnityEngine.Object.DestroyImmediate(image);
    check("process view rendered",File.Exists(Path.Combine(reportDir,"unity_furnace_physics.png")),"Native Unity camera at 180 simulated seconds");
   }
   var report=new FurnaceReport{status=checks.All(c=>c.pass)?"PASS":"FAIL",scope="Reduced-order net reaction/enthalpy model; pure-iron phase proxy; Darcy taphole and 1-D Saint-Venant runner. Numerical verification, not industrial validation.",checks=checks,massResidualKg=model.MassResidualKg,energyResidualJ=model.EnergyResidualJ,liquidKg=model.LiquidIronKg,tapKgS=model.TapKgPerSecond,runnerM3=model.Channel.VolumeM3,receivedM3=model.Channel.OutletM3};
   simulation.SetProcessView(false);check("walking and drone restored on leaving section",UnityEngine.Object.FindFirstObjectByType<MAEKWalkthrough>().enabled&&UnityEngine.Object.FindFirstObjectByType<MAEKDroneInspection>().enabled&&!camera.enabled,"Camera and controls restored");simulation.DisposePreview();
   report.status=checks.All(c=>c.pass)?"PASS":"FAIL";File.WriteAllText(Path.Combine(reportDir,"furnace_physics_report.json"),JsonUtility.ToJson(report,true));if(report.status!="PASS")throw new Exception("Scene verification failed");
   if(!EditorSceneManager.SaveScene(scene,Root+"/Scenes/MAEKFurnacePhysics.unity"))throw new Exception("Scene save failed");EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene(Root+"/Scenes/MAEKFurnacePhysics.unity",true)};AssetDatabase.SaveAssets();
   AssetDatabase.ExportPackage(Root,Path.Combine(reportDir,"MAEK_Furnace_Physics.unitypackage"),ExportPackageOptions.Recurse);
   Debug.Log("FURNACE_PHYSICS_COMPLETE "+JsonUtility.ToJson(report));
  }
 }
}

