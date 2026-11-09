using System;
using System.IO;
using UnityEngine;

namespace MAEK {
 // Fixed simulation timestep + PNG frames: wall-clock rendering speed cannot skip route samples.
 // Python encoder adds the same evidence labels from frames.jsonl and encodes H.264.
 public sealed class MAEKTourRecorder:MonoBehaviour {
  public int width=1280,height=720,fps=24;
  public bool Recording {get;private set;} public int FrameCount {get;private set;}
  public string OutputDirectory {get;private set;}
  MAEKInspectionTour tour;StreamWriter metadata;
  public void StartRecording(MAEKInspectionTour source,string output=null) {
   if(Recording)return;tour=source;
   if(!tour.Active)throw new InvalidOperationException("Start the inspection tour first");
   OutputDirectory=output??Path.Combine(tour.SessionDirectory,"video-"+DateTime.Now.ToString("HHmmss-fff"));
   Directory.CreateDirectory(OutputDirectory);FrameCount=0;
   metadata=new StreamWriter(Path.Combine(OutputDirectory,"frames.jsonl"),false);
   File.WriteAllText(Path.Combine(OutputDirectory,"recording.json"),JsonUtility.ToJson(new Settings{fps=fps,width=width,height=height},true));
   Recording=true;
  }
  [Serializable] class Settings {public int fps,width,height;public string overlay="MAEK evidence metadata; no future-crack claim";}
  public void CaptureFrame() {
   if(!Recording)return;
   try {
    File.WriteAllBytes(Path.Combine(OutputDirectory,FrameCount.ToString("D06")+".png"),tour.CapturePixels(width,height));
    metadata.WriteLine(JsonUtility.ToJson(tour.VideoFrame(FrameCount,(float)FrameCount/fps)));metadata.Flush();FrameCount++;
   }catch(Exception e){StopRecording();tour.Failure("녹화 실패: "+e.Message);throw;}
  }
  void LateUpdate(){if(Recording&&!tour.externalClock){CaptureFrame();if(tour.Complete||tour.Blocked)StopRecording();}}
  public void StopRecording(){if(!Recording)return;Recording=false;metadata?.Dispose();metadata=null;Debug.Log("MAEK recording saved: "+OutputDirectory);}
  void OnDisable(){StopRecording();}
 }
}
