using System;
using System.IO;
using System.Linq;
using System.Collections.Generic;
using UnityEngine;
using UnityEditor;
using UnityEditor.SceneManagement;
using MAEK.Tests;
namespace MAEK.Editor {
 public static class BuildCFDScene {
  const string Root="Assets/MAEK";
  [Serializable] class Report {public string status; public List<PhysicsCheck> checks;}
  [MenuItem("MAEK/Build and verify 3D CFD playback")]
  public static void Run(){try{Build();if(Application.isBatchMode)EditorApplication.Exit(0);}catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
  static void Render(Camera camera,string path){var rt=new RenderTexture(1400,1000,24);camera.targetTexture=rt;camera.Render();var old=RenderTexture.active;RenderTexture.active=rt;var tex=new Texture2D(1400,1000,TextureFormat.RGB24,false);tex.ReadPixels(new Rect(0,0,1400,1000),0,0);tex.Apply();File.WriteAllBytes(path,tex.EncodeToPNG());RenderTexture.active=old;camera.targetTexture=null;rt.Release();UnityEngine.Object.DestroyImmediate(rt);UnityEngine.Object.DestroyImmediate(tex);}
  public static void Build(){
   string output=Path.GetFullPath(Path.Combine(Application.dataPath,"../../../visualization/cfd"));
   var scene=EditorSceneManager.OpenScene(Root+"/Scenes/MAEKDroneInspection.unity");
   var checks=new List<PhysicsCheck>();Action<string,bool,string> check=(n,p,d)=>checks.Add(new PhysicsCheck{name=n,pass=p,detail=d});
   var host=new GameObject("MAEK 3D CFD playback");var playback=host.AddComponent<MAEKCFDPlayback>();playback.results=AssetDatabase.LoadAssetAtPath<TextAsset>(Root+"/Source/cfd_playback.json");playback.exteriorSection=AssetDatabase.LoadAssetAtPath<Material>(Root+"/Generated/Materials/FurnaceSection.mat");
   var camera=new GameObject("CFD review camera").AddComponent<Camera>();camera.enabled=false;camera.nearClipPlane=.04f;camera.farClipPlane=1300;camera.fieldOfView=50;camera.clearFlags=CameraClearFlags.SolidColor;camera.backgroundColor=new Color(.09f,.13f,.18f);playback.viewCamera=camera;
   playback.Initialize();playback.SetView(true);var clip=playback.Clip;
   check("3D reference cache",clip.version==1&&clip.hearthCells==20224&&clip.hearthFrames.Length==13,"OpenFOAM 14; 20,224 cells; 0-12 seconds");
   check("spatial reaction cache",clip.shaftPositions.Length==1496*3&&clip.shaftFrames.Length==25,"1,496 cells; 0-120 seconds; independent run");
   foreach(var frame in clip.hearthFrames){playback.ApplyFrames(Array.IndexOf(clip.hearthFrames,frame),clip.shaftFrames.Length-1);check("CFD frame "+frame.time,frame.iron.vertices.Length>0&&frame.slag.vertices.Length>0&&playback.VisualRoot.GetComponentsInChildren<MeshFilter>().Where(m=>!m.name.Contains("velocity")).All(m=>m.sharedMesh.vertexCount>0),"Computed surfaces; zero initial velocity correctly has no arrows");}
   check("nonempty shaft section",playback.DisplayedShaftCells>100,"Actual spatial cell data");
   var shaftMesh=playback.VisualRoot.GetComponentsInChildren<MeshFilter>().First(m=>m.name.Contains("spatial shaft")).sharedMesh;var thermalColors=shaftMesh.colors;int heldFrame=playback.ShaftIndex;playback.SetField(1);check("field selector updates without advancing time",playback.ShaftIndex==heldFrame&&thermalColors.Where((c,i)=>Vector4.Distance(c,shaftMesh.colors[i])>.05f).Any(),"CO colors update immediately even when playback is paused");playback.SetField(0);
   check("physical coordinate mapping",Vector3.Distance(MAEKCFDPlayback.Map(0,0,0),new Vector3(-62,3.2f,18))<1e-6,"SI metres; existing furnace hearth origin");
   check("camera ownership",camera.enabled&&!UnityEngine.Object.FindFirstObjectByType<MAEKWalkthrough>().enabled&&!UnityEngine.Object.FindFirstObjectByType<MAEKDroneInspection>().enabled,"No competing movement controllers");
   check("colliders retained",UnityEngine.Object.FindObjectsByType<MeshCollider>(FindObjectsSortMode.None).Length==323,"Only renderers hidden in section view");
   var routes=JsonUtility.FromJson<DroneRouteSet>(File.ReadAllText(Root+"/Source/drone_routes.json"));UnityEngine.Physics.SyncTransforms();int mask=1<<8;
   foreach(var route in routes.routes){bool safe=true;for(int k=0;k<route.waypoints.Length;k++){var p=MAEKDroneInspection.V(route.waypoints[k].position);if(UnityEngine.Physics.CheckSphere(p,route.radius,mask,QueryTriggerInteraction.Ignore)){safe=false;break;}if(k>0){var a=MAEKDroneInspection.V(route.waypoints[k-1].position);var d=p-a;if(d.magnitude>.00001f&&UnityEngine.Physics.SphereCast(a,route.radius,d.normalized,out var hit,d.magnitude,mask,QueryTriggerInteraction.Ignore)){safe=false;break;}}}check("retained drone "+route.id,safe,"Existing collision geometry");}
   if(SystemInfo.graphicsDeviceType==UnityEngine.Rendering.GraphicsDeviceType.Null)throw new Exception("Graphics device required for CFD preview");
   playback.Focus(true);check("hearth camera above ground",camera.transform.position.y>8,"Positive orbit elevation must increase world Y");Render(camera,Path.Combine(output,"unity_cfd_hearth.png"));playback.Focus(false);check("shaft camera above occluders",camera.transform.position.y>40,"Above foreground structures");Render(camera,Path.Combine(output,"unity_cfd_shaft.png"));
   playback.SetView(false);check("walk and drone restored",UnityEngine.Object.FindFirstObjectByType<MAEKWalkthrough>().enabled&&UnityEngine.Object.FindFirstObjectByType<MAEKDroneInspection>().enabled&&!camera.enabled,"P exits section without removing prior navigation");playback.DisposePreview();
   var report=new Report{status=checks.All(c=>c.pass)?"PASS":"FAIL",checks=checks};File.WriteAllText(Path.Combine(output,"unity_cfd_report.json"),JsonUtility.ToJson(report,true));if(report.status!="PASS")throw new Exception("CFD view checks failed: "+string.Join(", ",checks.Where(c=>!c.pass).Select(c=>c.name)));
   if(!EditorSceneManager.SaveScene(scene,Root+"/Scenes/MAEKFurnaceCFD.unity"))throw new Exception("Save failed");EditorBuildSettings.scenes=new[]{new EditorBuildSettingsScene(Root+"/Scenes/MAEKFurnaceCFD.unity",true)};AssetDatabase.SaveAssets();AssetDatabase.ExportPackage(Root,Path.Combine(output,"MAEK_Furnace_CFD.unitypackage"),ExportPackageOptions.Recurse);Debug.Log("CFD_SCENE_COMPLETE checks="+checks.Count);
  }
 }
}
