using System;
using System.IO;
using UnityEngine;
namespace MAEK.Editor {
 public static class CaptureInteriorPhotos {
  public static void CaptureScene(){
   string folder=Path.GetFullPath("../../visualization/interior_detail/photos/"+DateTime.Now.ToString("yyyyMMdd-HHmmss"));Directory.CreateDirectory(folder);
   var c=new GameObject("Temporary interior photography camera").AddComponent<Camera>();c.enabled=false;c.nearClipPlane=.05f;c.farClipPlane=200;
   CaptureFactoryPhotos.Capture(c,folder,"01_cast_house_aisle",new Vector3(-62,2.4f,42),new Vector3(-65,2.2f,54),68);
   CaptureFactoryPhotos.Capture(c,folder,"02_existing_inspection_loop",new Vector3(-63.5f,2.2f,47),new Vector3(-69,1.7f,53),64);
   CaptureFactoryPhotos.Capture(c,folder,"03_maintenance_hall",new Vector3(-97,3.8f,96.5f),new Vector3(-97,2.3f,111),82);
   CaptureFactoryPhotos.Capture(c,folder,"04_cold_spool_workstation",new Vector3(-99.2f,2.5f,98),new Vector3(-104.5f,1.9f,102),57);
   CaptureFactoryPhotos.Capture(c,folder,"05_cast_house_workbench",new Vector3(-65,2.0f,41.5f),new Vector3(-70,1.25f,44.1f),57);
   UnityEngine.Object.DestroyImmediate(c.gameObject);File.WriteAllText(Path.Combine(folder,"../../latest_photos.txt"),folder);Debug.Log("MAEK_INTERIOR_PHOTOS "+folder);
  }
 }
}
