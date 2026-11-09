using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using MAEK.Tests;

namespace MAEK.Editor {
 public static class BuildHydraulicScene {
  const string Root="Assets/MAEK";
  [Serializable] class Report {public string status;public List<PhysicsCheck> checks;}
  [MenuItem("MAEK/Build hydraulic CFD environment")]
  public static void Run(){try{Build();if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  static void Render(Camera camera,string path){var rt=new RenderTexture(1400,900,24);camera.targetTexture=rt;camera.Render();var old=RenderTexture.active;RenderTexture.active=rt;var tex=new Texture2D(1400,900,TextureFormat.RGB24,false);tex.ReadPixels(new Rect(0,0,1400,900),0,0);tex.Apply();File.WriteAllBytes(path,tex.EncodeToPNG());camera.targetTexture=null;RenderTexture.active=old;rt.Release();UnityEngine.Object.DestroyImmediate(rt);UnityEngine.Object.DestroyImmediate(tex);}
  public static void Build(){
   var scene=EditorSceneManager.OpenScene(Root+"/Scenes/MAEKPipeServices.unity");string output=Path.GetFullPath(Path.Combine(Application.dataPath,"../../../visualization/hydraulics"));Directory.CreateDirectory(output);
   var checks=new List<PhysicsCheck>();Action<string,bool,string> check=(n,p,d)=>checks.Add(new PhysicsCheck{name=n,pass=p,detail=d});
   int colliderCount=UnityEngine.Object.FindObjectsByType<Collider>(FindObjectsSortMode.None).Length;
   var services=UnityEngine.Object.FindFirstObjectByType<MAEKPipeServices>();services.Initialize();
   var flow=new GameObject("MAEK pressure flow and coupled shaft").AddComponent<MAEKHydraulicFlow>();flow.results=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/hydraulic_results.json");
   flow.coupledClips=new[]{"baseline","reduced_blast","utility_test"}.Select(n=>AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/coupled_cfd_"+n+".json")).ToArray();
   var material=AssetDatabase.LoadAssetAtPath<Material>(Root+"/Generated/Materials/HYDRAULIC_FLOW.mat");if(!material){material=new Material(Shader.Find("MAEK/FlowGlyph"));AssetDatabase.CreateAsset(material,Root+"/Generated/Materials/HYDRAULIC_FLOW.mat");}flow.flowMaterial=material;flow.Initialize();
   var cfd=UnityEngine.Object.FindFirstObjectByType<MAEKCFDPlayback>();cfd.startInCFDView=false;
   check("all 247 hydraulic values available",flow.Current.pipes.Length==247,"Includes closed and stagnant branches");
   var baseMass=flow.Current.furnaces[0].blast_mass_kg_s;var bf2Mass=flow.Current.furnaces[1].blast_mass_kg_s;
   check("closed nitrogen has no flow",flow.Pipe("UTIL-N002").massKgS==0,"Normal closed state");
   check("idle instrument air has zero demand",Mathf.Abs(flow.Pipe("UTIL-I003").massKgS)<1e-7f,"Static pressure is retained");
   flow.RenderFlowAtTime(3);int arrowCount=flow.VisibleArrowCount;check("computed moving arrows",arrowCount>100,"Signed mass flow drives direction");
   var glyph=flow.GetComponentInChildren<MeshFilter>().sharedMesh;var before= glyph.vertices[0];flow.RenderFlowAtTime(5);check("flow geometry advances with time",Vector3.Distance(before,glyph.vertices[0])>.001f,"Motion follows the computed signed velocity");
   flow.onlySelected=true;services.SelectPipe("UTIL-N002");flow.RenderFlowAtTime(3);check("no arrows in closed pipe",flow.VisibleArrowCount==0,"Zero flow never animates");flow.onlySelected=false;
   flow.SelectCase(1);check("blast pressure change affects BF1",flow.Current.furnaces[0].blast_mass_kg_s<baseMass,"Reduced pressure changes solved flow");check("BF2 remains independent",Mathf.Abs(flow.Current.furnaces[1].blast_mass_kg_s-bf2Mass)<1e-5f,"Only BF1 input changed");
   check("CFD has separate furnace fields",cfd.HasCoupledShaft&&cfd.Clip.unitShafts[0].velocity.Zip(cfd.Clip.unitShafts[1].velocity,(a,b)=>Mathf.Abs(a-b)).Max()>.001f,"3D fields are recomputed, not recoloured reference values");
   check("hearth VOF has recomputed unit results",cfd.HasCoupledHearth&&cfd.Clip.unitHearths[0].frames.Last().vectors.Zip(cfd.Clip.unitHearths[1].frames.Last().vectors,(a,b)=>Mathf.Abs(a-b)).Max()>1e-7f,"Gas pressure and nozzle closure feed new OpenFOAM runs");
   cfd.SetView(true);cfd.SetField(3);check("coupled shaft pressure displayed",cfd.DisplayedShaftCells>0,"Pressure field uses absolute Pa");cfd.Focus(false);Render(cfd.viewCamera,Path.Combine(output,"coupled_shaft_pressure.png"));cfd.SetField(4);Render(cfd.viewCamera,Path.Combine(output,"coupled_shaft_speed.png"));
   flow.SelectCase(2);check("scenario switch preserves CFD view",cfd.ActiveView,"Results replaced while inspecting CFD");check("open nitrogen flows",flow.Pipe("UTIL-N002").massKgS>0,"Independent regulated boundary snapshot");check("actuator demand is calculated",Mathf.Abs(flow.Pipe("UTIL-I003").massKgS-.0005f)<1e-8f,"Air remains separate from nitrogen");cfd.SetView(false);
   flow.SelectCase(0);flow.RenderFlowAtTime(3);check("case switching leaves one CFD root",UnityEngine.Object.FindObjectsByType<Transform>(FindObjectsInactive.Include,FindObjectsSortMode.None).Count(t=>t.name=="Actual CFD surfaces and spatial reaction fields")==1,"No duplicate CFD meshes after swaps");
   var camera=new GameObject("Hydraulic preview camera").AddComponent<Camera>();camera.enabled=false;camera.fieldOfView=50;camera.nearClipPlane=.03f;camera.farClipPlane=1500;camera.transform.position=new Vector3(-125,85,110);camera.transform.LookAt(new Vector3(-60,20,15));Render(camera,Path.Combine(output,"hydraulic_overview.png"));
   var chosen=services.Data.pipes.First(p=>p.id=="BF1-H003");var mid=MAEKPipeServices.V(chosen.points[chosen.points.Length/2].position);camera.transform.position=mid+new Vector3(9,7,-12);camera.transform.LookAt(mid);Render(camera,Path.Combine(output,"hydraulic_pipe_detail.png"));UnityEngine.Object.DestroyImmediate(camera.gameObject);
   check("all original colliders preserved",UnityEngine.Object.FindObjectsByType<Collider>(FindObjectsSortMode.None).Length==colliderCount,"Flow glyphs have no colliders");
   var routes=JsonUtility.FromJson<DroneRouteSet>(AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/service_drone_routes.json").text);Physics.SyncTransforms();foreach(var route in routes.routes){bool clear=true;for(int k=0;k<route.waypoints.Length;k++){var p=MAEKDroneInspection.V(route.waypoints[k].position);if(Physics.CheckSphere(p,route.radius,1<<8,QueryTriggerInteraction.Ignore)){clear=false;break;}if(k>0){var a=MAEKDroneInspection.V(route.waypoints[k-1].position);var d=p-a;if(d.magnitude>1e-6f&&Physics.SphereCast(a,route.radius,d.normalized,out var hit,d.magnitude,1<<8,QueryTriggerInteraction.Ignore)){clear=false;break;}}}check("drone "+route.id,clear,"Swept-sphere route retained");}
   cfd.DisposePreview();flow.DisposePreview();services.RestoreColors();
   var report=new Report{status=checks.All(c=>c.pass)?"PASS":"FAIL",checks=checks};File.WriteAllText(Path.Combine(output,"unity_hydraulic_report.json"),JsonUtility.ToJson(report,true));if(report.status!="PASS")throw new Exception(string.Join(";",checks.Where(c=>!c.pass).Select(c=>c.name)));
   EditorSceneManager.SaveScene(scene,Root+"/Scenes/MAEKHydraulicCFD.unity");EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene(Root+"/Scenes/MAEKHydraulicCFD.unity",true)};AssetDatabase.SaveAssets();AssetDatabase.ExportPackage(Root,Path.Combine(output,"MAEK_Hydraulic_CFD.unitypackage"),ExportPackageOptions.Recurse);Debug.Log("HYDRAULIC_SCENE_COMPLETE checks="+checks.Count);
  }
 }
}
