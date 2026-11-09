using System;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace MAEK.Editor {
 public static class VerifyMaintenanceInspector {
  const string Scene="Assets/MAEK/Scenes/MAEKInspectionDemo.unity";
  static string Output=>Path.GetFullPath(Path.Combine(Application.dataPath,"../../../visualization/maintenance_inspector"));
  [Serializable] sealed class Report {public string status,sceneBefore,sceneAfter;public int cataloguePipes,requiredCaptures,renderedPixels;public float actorHeight;public Vector3 position;public bool originalRouteClear,supplementaryRouteClear;}
  static string Sha(string path){using(var hash=SHA256.Create())return BitConverter.ToString(hash.ComputeHash(File.ReadAllBytes(path))).Replace("-","").ToLowerInvariant();}
  static void Require(bool ok,string message){if(!ok)throw new Exception(message);}
  [MenuItem("MAEK/Characters/Verify maintenance inspector")]
  public static void Run(){
   Directory.CreateDirectory(Output);var report=new Report{sceneBefore=Sha(Scene)};
   try{
    EditorSceneManager.OpenScene(Scene);Physics.SyncTransforms();
    var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();tour.Initialize();
    report.cataloguePipes=tour.Plan.pipeIds.Length;report.requiredCaptures=tour.Plan.requiredCaptures;
    Require(report.cataloguePipes==247&&report.requiredCaptures==771,"Original catalogue changed");
    var actor=MAEKMaintenanceInspector.TrySpawn(tour);Require(actor,"Inspector was not placed: "+MAEKMaintenanceInspector.LastPlacementStatus);
    var body=actor.GetComponent<CapsuleCollider>();Require(body&&body.enabled&&body.gameObject.layer==8,"Missing environment collider");
    report.originalRouteClear=MAEKMaintenanceInspector.PreservesRoute(body,tour.Plan)&&MAEKMaintenanceInspector.PreservesViews(body,tour.Plan);Require(report.originalRouteClear,"Inspector obstructs original drone route/view");
    var extra=tour.GetComponent<MAEKSupplementaryCircuits>();var plan=JsonUtility.FromJson<TourPlan>(extra.inspectionRoute.text);
    report.supplementaryRouteClear=MAEKMaintenanceInspector.PreservesRoute(body,plan)&&MAEKMaintenanceInspector.PreservesViews(body,plan);Require(report.supplementaryRouteClear,"Inspector obstructs supplementary route/view");
    var centre=actor.transform.position+Vector3.up*.9f;
    var crossing=new TourPlan{radius=.34f,points=new[]{new TourPoint{position=centre-Vector3.right*3,target=centre+Vector3.right*3,pipeId="test"},new TourPoint{position=centre+Vector3.right*3}}};
    Require(!MAEKMaintenanceInspector.PreservesRoute(body,crossing),"Collision guard accepts a segment through the actor");
    Require(!MAEKMaintenanceInspector.PreservesViews(body,crossing),"Sightline guard accepts an actor occlusion");
    Require(Mathf.Abs(body.radius-.5f)<1e-6f&&Mathf.Abs(body.height-1.8f)<1e-6f,"Collision test failed to restore the actor body");
    Require(MAEKMaintenanceInspector.TrySpawn(tour)==actor,"Duplicate inspector spawn");
    var visual=actor.GetComponent<MAEKInspectorVisual>();for(int i=0;i<120;i++)visual.Advance(1f/60,0,true,0,false);
    Require(visual.Pda&&visual.PhotoLens,"PDA reference is missing");
    var skin=actor.GetComponentInChildren<SkinnedMeshRenderer>();report.actorHeight=skin.bounds.size.y;report.position=actor.transform.position;
    Require(report.actorHeight>1.6f&&report.actorHeight<1.9f,"Invalid inspector scale");
    Require(actor.GetComponentsInChildren<Renderer>().All(r=>r.sharedMaterials.All(m=>m&&m.shader&&m.shader.isSupported)),"Missing/unsupported material");
    // Bake the current procedural pose for deterministic Editor rendering; the prefab remains skinned.
    var mesh=new Mesh();skin.BakeMesh(mesh);var baked=new GameObject("Inspector render surrogate");baked.transform.SetParent(skin.transform,false);baked.AddComponent<MeshFilter>().sharedMesh=mesh;baked.AddComponent<MeshRenderer>().sharedMaterials=skin.sharedMaterials;skin.enabled=false;
    var camera=new GameObject("Inspector verification camera").AddComponent<Camera>();camera.transform.position=actor.transform.position+new Vector3(3,1.55f,-3);camera.transform.LookAt(actor.transform.position+Vector3.up*.9f);camera.fieldOfView=32;camera.farClipPlane=300;
    var rt=new RenderTexture(960,540,24);rt.Create();camera.targetTexture=rt;camera.Render();var old=RenderTexture.active;RenderTexture.active=rt;
    var image=new Texture2D(960,540,TextureFormat.RGB24,false);image.ReadPixels(new Rect(0,0,960,540),0,0);image.Apply();
    report.renderedPixels=image.GetPixels32().Count(c=>c.r>100&&c.g>70&&c.b<90);Require(report.renderedPixels>100,"Inspector helmet/uniform not visible");
    File.WriteAllBytes(Path.Combine(Output,"inspector.png"),image.EncodeToPNG());RenderTexture.active=old;camera.targetTexture=null;rt.Release();
    report.sceneAfter=Sha(Scene);Require(report.sceneBefore==report.sceneAfter,"Saved main scene was modified");report.status="PASS";
    File.WriteAllText(Path.Combine(Output,"verification.json"),JsonUtility.ToJson(report,true));Debug.Log("MAEK_INSPECTOR_PASS "+Output);
    if(Application.isBatchMode)EditorApplication.Exit(0);
   }catch(Exception e){report.status="FAIL";File.WriteAllText(Path.Combine(Output,"verification.json"),JsonUtility.ToJson(report,true));Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}
  }
 }
}
