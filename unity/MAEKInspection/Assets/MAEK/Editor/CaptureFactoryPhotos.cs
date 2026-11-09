using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace MAEK.Editor {
 public static class CaptureFactoryPhotos {
  [MenuItem("MAEK/Capture factory photographs")]
  public static void Run() {
   try {CaptureScene();if(Application.isBatchMode)EditorApplication.Exit(0);}
   catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}
  }
  public static void CaptureScene(){
    EditorSceneManager.OpenScene("Assets/MAEK/Scenes/MAEKInspectionDemo.unity");
    string folder=Path.GetFullPath(Path.Combine(Application.dataPath,"../../../visualization/factory_photos",DateTime.Now.ToString("yyyyMMdd-HHmmss")));
    Directory.CreateDirectory(folder);
    var services=UnityEngine.Object.FindFirstObjectByType<MAEKPipeServices>();
    if(services){services.Initialize();services.SetOverlay(false);}
    var camera=new GameObject("Temporary factory photograph camera").AddComponent<Camera>();
    camera.enabled=false;camera.nearClipPlane=.05f;camera.farClipPlane=1600;
    camera.clearFlags=CameraClearFlags.Skybox;
    Capture(camera,folder,"01_factory_overview",new Vector3(-110,46,-100),new Vector3(-6,23,8),52);
    Capture(camera,folder,"02_blast_furnace",new Vector3(-108,32,-58),new Vector3(-62,29,18),48);
    Capture(camera,folder,"03_pipe_inspection_area",new Vector3(-86,10,-25),new Vector3(-68,7,-10),58);
    UnityEngine.Object.DestroyImmediate(camera.gameObject);
    File.WriteAllText(Path.Combine(folder,"capture_note.txt"),"Fresh 1920x1080 Unity renders of MAEKInspectionDemo.unity. Synthetic steelworks; no scene was saved or geometry changed.");
    File.WriteAllText(Path.Combine(folder,"../latest_capture.txt"),folder);
    Debug.Log("MAEK_FACTORY_PHOTOS_SAVED "+folder);
  }
  public static void Capture(Camera camera,string folder,string name,Vector3 position,Vector3 target,float fov) {
   camera.transform.position=position;camera.transform.LookAt(target);camera.fieldOfView=fov;camera.aspect=16f/9;
   var rt=RenderTexture.GetTemporary(new RenderTextureDescriptor(1920,1080,RenderTextureFormat.ARGB32,24){msaaSamples=4});
   var previous=RenderTexture.active;var texture=new Texture2D(1920,1080,TextureFormat.RGB24,false);
   try {camera.targetTexture=rt;camera.Render();RenderTexture.active=rt;
    texture.ReadPixels(new Rect(0,0,1920,1080),0,0);texture.Apply();
    File.WriteAllBytes(Path.Combine(folder,name+".png"),texture.EncodeToPNG());
   } finally {camera.targetTexture=null;RenderTexture.active=previous;RenderTexture.ReleaseTemporary(rt);UnityEngine.Object.DestroyImmediate(texture);}
  }
 }
}
