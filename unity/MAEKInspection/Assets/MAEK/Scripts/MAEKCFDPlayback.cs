using System;
using System.Collections.Generic;
using UnityEngine;
namespace MAEK {
 [Serializable] public class CFDSurfaceData { public float[] vertices; public int[] triangles; }
 [Serializable] public class CFDHearthFrame { public float time; public CFDSurfaceData iron,slag; public float[] vectors,pressure; }
 [Serializable] public class CFDShaftFrame { public float time; public float[] temperature,co,reduction; }
 [Serializable] public class CFDUnitShaft {public string unit;public CFDShaftFrame[] frames;public float[] velocity,pressure;}
 [Serializable] public class CFDUnitHearth {public string unit;public CFDHearthFrame[] frames;public float[] vectorPositions;}
 [Serializable] public class CFDClip {
  public int version,hearthCells; public string solver,scope; public float hearthCellM,shaftCellM;
  public float[] vectorPositions,shaftPositions,shaftVelocity,shaftPressure;
  public CFDHearthFrame[] hearthFrames; public CFDShaftFrame[] shaftFrames;
  public CFDUnitShaft[] unitShafts;public CFDUnitHearth[] unitHearths;public string couplingLabel;
 }
 public sealed class MAEKCFDPlayback:MonoBehaviour {
  public TextAsset results; public Material exteriorSection; public Camera viewCamera;
  public bool startInCFDView=true;
  public CFDClip Clip {get;private set;} public GameObject VisualRoot {get;private set;}
  public bool ActiveView {get;private set;} public int HearthIndex {get;private set;}
  public int ShaftIndex {get;private set;} public int DisplayedShaftCells {get;private set;}
  readonly List<Material> ownedMaterials=new List<Material>(); readonly List<Mesh> ownedMeshes=new List<Mesh>();
  readonly List<Renderer> shells=new List<Renderer>(),occluders=new List<Renderer>();
  readonly List<Material[]> oldMaterials=new List<Material[]>(); readonly List<bool> oldVisibility=new List<bool>();
  Material ironMaterial,slagMaterial,fieldMaterial; Mesh[] ironMeshes,slagMeshes,shaftMeshes,vectorMeshes;
  Camera[] oldCameras; bool[] oldCameraEnabled; MAEKWalkthrough walk; MAEKDroneInspection drone;
  bool oldWalk,oldDrone,initialized,paused,detail,section=true; int unit,fieldMode;
  float hearthTime,shaftTime,slice=.5f,yaw,pitch=15,distance=55;
  public static Vector3 Map(float x,float y,float z,int unit=0,float floor=3.2f) {
   return new Vector3((unit==0?-62:62)+x,floor+z,18+y);
  }
  void Start(){Initialize();SetView(startInCFDView);}
  Material MakeMaterial(string shader,Color color){var m=new Material(Shader.Find(shader));m.color=color;ownedMaterials.Add(m);return m;}
  Mesh MakeMesh(string name,Material material){var g=new GameObject(name,typeof(MeshFilter),typeof(MeshRenderer));g.transform.SetParent(VisualRoot.transform,false);var m=new Mesh{name=name,indexFormat=UnityEngine.Rendering.IndexFormat.UInt32};g.GetComponent<MeshFilter>().sharedMesh=m;g.GetComponent<MeshRenderer>().sharedMaterial=material;ownedMeshes.Add(m);return m;}
  public void Initialize(){
   if(initialized)return; initialized=true;
   Clip=JsonUtility.FromJson<CFDClip>(results.text);
   if(Clip.version!=1||Clip.hearthFrames.Length<2||Clip.shaftFrames.Length<2)throw new Exception("Invalid CFD cache");
   VisualRoot=new GameObject("Actual CFD surfaces and spatial reaction fields");VisualRoot.transform.SetParent(transform,false);
   ironMaterial=MakeMaterial("MAEK/CFDSurface",new Color(1,.22f,.025f));slagMaterial=MakeMaterial("MAEK/CFDSurface",new Color(.32f,.22f,.065f));
   fieldMaterial=new Material(Shader.Find("MAEK/CFDField"));ownedMaterials.Add(fieldMaterial);
   ironMeshes=new Mesh[2];slagMeshes=new Mesh[2];shaftMeshes=new Mesh[2];vectorMeshes=new Mesh[2];
   for(int i=0;i<2;i++){ironMeshes[i]=MakeMesh("BF"+(i+1)+" iron alpha=0.5",ironMaterial);slagMeshes[i]=MakeMesh("BF"+(i+1)+" slag alpha=0.5",slagMaterial);shaftMeshes[i]=MakeMesh("BF"+(i+1)+" spatial shaft slice",fieldMaterial);vectorMeshes[i]=MakeMesh("BF"+(i+1)+" solved velocity arrows",fieldMaterial);}
   walk=FindFirstObjectByType<MAEKWalkthrough>();drone=FindFirstObjectByType<MAEKDroneInspection>();
   foreach(var info in FindObjectsByType<MAEKAssetInfo>(FindObjectsSortMode.None)){
    var r=info.GetComponent<Renderer>();if(!r)continue;
    if(info.assetId=="BF1.BF"||info.assetId=="BF2.BF"||info.assetId=="BF1.TOWER"||info.assetId=="BF2.TOWER"){
     shells.Add(r);oldMaterials.Add(r.sharedMaterials);var mats=new Material[r.sharedMaterials.Length];for(int j=0;j<mats.Length;j++){var m=new Material(exteriorSection);m.color=r.sharedMaterials[j].color;m.SetFloat("_Section",0);m.SetFloat("_SectionZ",18);mats[j]=m;ownedMaterials.Add(m);}r.sharedMaterials=mats;
    }
    if(info.assetId.EndsWith(".CASTHOUSE")||info.assetId.EndsWith(".CONVEYOR")||info.assetId.EndsWith(".CASTHOUSE.CRANE")){occluders.Add(r);oldVisibility.Add(r.enabled);}
   }
   ApplyFrames(0,0);VisualRoot.SetActive(false);
  }
  void Surface(Mesh mesh,CFDSurfaceData data,int u){var vs=new Vector3[data.vertices.Length/3];for(int i=0;i<vs.Length;i++)vs[i]=Map(data.vertices[3*i],data.vertices[3*i+1],data.vertices[3*i+2],u);var tris=(int[])data.triangles.Clone();for(int i=0;i<tris.Length;i+=3){int t=tris[i+1];tris[i+1]=tris[i+2];tris[i+2]=t;}mesh.Clear();mesh.vertices=vs;mesh.triangles=tris;mesh.RecalculateNormals();mesh.RecalculateBounds();}
  static Color Ramp(float value){float t=Mathf.Clamp01(value);return t<.5f?Color.Lerp(new Color(.04f,.16f,.65f),new Color(.1f,.9f,.7f),t*2):Color.Lerp(new Color(.1f,.9f,.7f),new Color(1,.12f,.025f),(t-.5f)*2);}
  void Shaft(Mesh mesh,CFDShaftFrame frame,int u){
   var vs=new List<Vector3>();var cs=new List<Color>();var ts=new List<int>();float h=Clip.shaftCellM*.49f;int n=Clip.shaftPositions.Length/3;
   var scalar=fieldMode>=3?UnitField(u):null;float min=scalar==null?0:Mathf.Min(FieldMin(0),FieldMin(1)),max=scalar==null?1:Mathf.Max(FieldMax(0),FieldMax(1));
   for(int i=0;i<n;i++){float x=Clip.shaftPositions[i*3],y=Clip.shaftPositions[i*3+1],z=Clip.shaftPositions[i*3+2];if(Mathf.Abs(y-slice)>.49f*Clip.shaftCellM)continue;
    float value=fieldMode==0?(frame.temperature[i]-750)/1150:fieldMode==1?frame.co[i]/.4f:frame.reduction[i]/.001f;
    if(scalar!=null)value=(scalar[i]-min)/Mathf.Max(1e-9f,max-min);
    Color c=Ramp(value);int s=vs.Count;vs.Add(Map(x-h,slice,z-h,u,7.2f));vs.Add(Map(x+h,slice,z-h,u,7.2f));vs.Add(Map(x+h,slice,z+h,u,7.2f));vs.Add(Map(x-h,slice,z+h,u,7.2f));for(int k=0;k<4;k++)cs.Add(c);ts.AddRange(new[]{s,s+1,s+2,s,s+2,s+3});
   }
   mesh.Clear();mesh.SetVertices(vs);mesh.SetTriangles(ts,0);mesh.SetColors(cs);mesh.RecalculateBounds();DisplayedShaftCells=vs.Count/4;
  }
  void Vectors(Mesh mesh,CFDHearthFrame frame,int u){
   var vs=new List<Vector3>();var cs=new List<Color>();var ts=new List<int>();
   var positions=HasCoupledHearth?Clip.unitHearths[u].vectorPositions:Clip.vectorPositions;
   for(int i=0;i<positions.Length/3;i++){
    var p=Map(positions[3*i],.02f,positions[3*i+2],u);
    var v=new Vector3(frame.vectors[3*i],frame.vectors[3*i+2],frame.vectors[3*i+1]);float speed=v.magnitude;if(speed<1e-6)continue;
    // Arrow displacement = velocity x 10 seconds; magnitude is not normalized away.
    var d=v*10;var side=Vector3.Cross(d,viewCamera?viewCamera.transform.forward:Vector3.forward).normalized*.012f;
    var tip=p+d;var arrowBase=tip-v.normalized*Mathf.Min(.08f,d.magnitude*.3f);int s=vs.Count;vs.AddRange(new[]{p-side,p+side,arrowBase+side,arrowBase-side,arrowBase-side*3,arrowBase+side*3,tip});for(int k=0;k<7;k++)cs.Add(Color.cyan);ts.AddRange(new[]{s,s+1,s+2,s,s+2,s+3,s+4,s+5,s+6});
   }
   mesh.Clear();mesh.SetVertices(vs);mesh.SetTriangles(ts,0);mesh.SetColors(cs);mesh.RecalculateBounds();
  }
  public bool HasCoupledShaft {get{return Clip!=null&&Clip.unitShafts!=null&&Clip.unitShafts.Length==2;}}
  public bool HasCoupledHearth {get{return Clip!=null&&Clip.unitHearths!=null&&Clip.unitHearths.Length==2;}}
  public CFDShaftFrame UnitFrame(int u,int frame){return HasCoupledShaft?Clip.unitShafts[u].frames[frame]:Clip.shaftFrames[frame];}
  float[] UnitField(int u){var pressure=HasCoupledShaft?Clip.unitShafts[u].pressure:Clip.shaftPressure;if(fieldMode==3)return pressure;var velocity=HasCoupledShaft?Clip.unitShafts[u].velocity:Clip.shaftVelocity;var speed=new float[velocity.Length/3];for(int i=0;i<speed.Length;i++)speed[i]=new Vector3(velocity[i*3],velocity[i*3+1],velocity[i*3+2]).magnitude;return speed;}
  float FieldMin(int u){float min=float.PositiveInfinity;foreach(float v in UnitField(u))min=Mathf.Min(min,v);return min;}
  float FieldMax(int u){float max=float.NegativeInfinity;foreach(float v in UnitField(u))max=Mathf.Max(max,v);return max;}
  public void ApplyFrames(int hearth,int shaft){HearthIndex=Mathf.Clamp(hearth,0,Clip.hearthFrames.Length-1);ShaftIndex=Mathf.Clamp(shaft,0,Clip.shaftFrames.Length-1);for(int u=0;u<2;u++){var hf=HasCoupledHearth?Clip.unitHearths[u].frames[HearthIndex]:Clip.hearthFrames[HearthIndex];Surface(ironMeshes[u],hf.iron,u);Surface(slagMeshes[u],hf.slag,u);Shaft(shaftMeshes[u],UnitFrame(u,ShaftIndex),u);Vectors(vectorMeshes[u],hf,u);}}
  public void SetField(int mode){fieldMode=Mathf.Clamp(mode,0,4);ApplyFrames(HearthIndex,ShaftIndex);}
  public void ReplaceResults(TextAsset next){bool visible=ActiveView;if(initialized)DisposePreview();results=next;hearthTime=shaftTime=0;Initialize();SetView(visible);}
  public void SetView(bool active){Initialize();if(active==ActiveView)return;ActiveView=active;VisualRoot.SetActive(active);
   if(active){oldCameras=FindObjectsByType<Camera>(FindObjectsSortMode.None);oldCameraEnabled=new bool[oldCameras.Length];for(int i=0;i<oldCameras.Length;i++){oldCameraEnabled[i]=oldCameras[i].enabled;oldCameras[i].enabled=false;}if(walk){oldWalk=walk.enabled;walk.enabled=false;}if(drone){oldDrone=drone.enabled;drone.enabled=false;}viewCamera.enabled=true;Cursor.lockState=CursorLockMode.None;Focus(false);}
   else{for(int i=0;i<oldCameras.Length;i++)if(oldCameras[i])oldCameras[i].enabled=oldCameraEnabled[i];if(walk)walk.enabled=oldWalk;if(drone)drone.enabled=oldDrone;viewCamera.enabled=false;}
   for(int i=0;i<occluders.Count;i++)occluders[i].enabled=active?false:oldVisibility[i];foreach(var r in shells)foreach(var m in r.sharedMaterials)m.SetFloat("_Section",active?1:0);
  }
  public void Focus(bool close){detail=close;distance=close?18:70;pitch=close?20:18;yaw=15;PositionCamera();}
  void PositionCamera(){var target=new Vector3(unit==0?-62:62,detail?5.2f:23,18);viewCamera.transform.position=target+Quaternion.Euler(-pitch,yaw,0)*new Vector3(0,0,distance);viewCamera.transform.LookAt(target);}
  void Update(){if(Input.GetKeyDown(KeyCode.P))SetView(!ActiveView);if(!ActiveView)return;
   if(Input.GetKeyDown(KeyCode.Space))paused=!paused;if(Input.GetKeyDown(KeyCode.H))Focus(true);if(Input.GetKeyDown(KeyCode.S))Focus(false);
   if(Input.GetKeyDown(KeyCode.Alpha1)){unit=0;PositionCamera();}if(Input.GetKeyDown(KeyCode.Alpha2)){unit=1;PositionCamera();}
   if(Input.GetMouseButton(1)){yaw+=Input.GetAxis("Mouse X")*2;pitch=Mathf.Clamp(pitch-Input.GetAxis("Mouse Y")*2,5,70);PositionCamera();}float scroll=Input.GetAxis("Mouse ScrollWheel");if(scroll!=0){distance=Mathf.Clamp(distance-scroll*distance*.3f,7,110);PositionCamera();}
   if(!paused){hearthTime=(hearthTime+Time.deltaTime*.5f)%(Clip.hearthFrames[Clip.hearthFrames.Length-1].time+.001f);shaftTime=(shaftTime+Time.deltaTime*5)%(Clip.shaftFrames[Clip.shaftFrames.Length-1].time+.001f);int hi=FindFrame(hearthTime,true),si=FindFrame(shaftTime,false);if(hi!=HearthIndex||si!=ShaftIndex)ApplyFrames(hi,si);}
  }
  int FindFrame(float t,bool hearth){int n=hearth?Clip.hearthFrames.Length:Clip.shaftFrames.Length;int k=0;for(int i=1;i<n;i++)if((hearth?Clip.hearthFrames[i].time:Clip.shaftFrames[i].time)<=t)k=i;return k;}
  void OnGUI(){if(!ActiveView||Clip==null)return;GUI.Box(new Rect(12,12,430,480),"MAEK | 3D CFD reference case");GUILayout.BeginArea(new Rect(26,40,405,445));
   GUILayout.Label("OpenFOAM 14 | iron / slag / gas | "+Clip.hearthCells+" cells");
   GUILayout.Label("Independent runs: hearth 0.5x / shaft 5x (not coupled clocks)");
   if(HasCoupledShaft)GUILayout.Label(Clip.couplingLabel);
   GUILayout.Label("Hearth: "+Clip.hearthFrames[HearthIndex].time.ToString("F1")+" s | orange iron, brown slag, cyan liquid velocity x 10 s");
   float ht=GUILayout.HorizontalSlider(hearthTime,0,Clip.hearthFrames[Clip.hearthFrames.Length-1].time);if(Mathf.Abs(ht-hearthTime)>.001){hearthTime=ht;paused=true;ApplyFrames(FindFrame(ht,true),ShaftIndex);}
   GUILayout.Label("Shaft: "+Clip.shaftFrames[ShaftIndex].time.ToString("F1")+" s | "+(fieldMode==0?"750 - 1900 K":fieldMode==1?"CO molar fraction 0 - 0.4":fieldMode==2?"ore reduction fraction 0 - 0.001":"Computed hydraulic field"));
   float st=GUILayout.HorizontalSlider(shaftTime,0,Clip.shaftFrames[Clip.shaftFrames.Length-1].time);if(Mathf.Abs(st-shaftTime)>.001){shaftTime=st;paused=true;ApplyFrames(HearthIndex,FindFrame(st,false));}
   GUILayout.BeginHorizontal();if(GUILayout.Button("Temperature"))SetField(0);if(GUILayout.Button("CO"))SetField(1);if(GUILayout.Button("Reduction"))SetField(2);GUILayout.EndHorizontal();
   GUILayout.BeginHorizontal();if(GUILayout.Button("Shaft pressure"))SetField(3);if(GUILayout.Button("Shaft speed"))SetField(4);GUILayout.EndHorizontal();if(fieldMode>=3)GUILayout.Label("Both units: "+Mathf.Min(FieldMin(0),FieldMin(1)).ToString("F3")+" - "+Mathf.Max(FieldMax(0),FieldMax(1)).ToString("F3")+(fieldMode==3?(HasCoupledShaft?" Pa absolute":" Pa relative to shaft top"):" m/s superficial velocity"));
   float sl=Mathf.Round(GUILayout.HorizontalSlider(slice,-3.5f,3.5f)-.5f)+.5f;GUILayout.Label("Shaft slice y = "+sl.ToString("F1")+(HasCoupledShaft?" m; separate BF1 / BF2 network solutions":" m; BF1 / BF2 replay same reference case"));if(sl!=slice||Event.current.type==EventType.MouseUp){slice=sl;ApplyFrames(HearthIndex,ShaftIndex);}
   GUILayout.BeginHorizontal();if(GUILayout.Button(paused?"Play":"Pause"))paused=!paused;if(GUILayout.Button("Hearth [H]"))Focus(true);if(GUILayout.Button("Shaft [S]"))Focus(false);if(GUILayout.Button("Cut / full")){section=!section;ironMaterial.SetFloat("_Section",section?1:0);slagMaterial.SetFloat("_Section",section?1:0);}GUILayout.EndHorizontal();
   GUILayout.Label("P: walk/drone | 1/2: furnace | right drag / wheel: camera");GUILayout.Label("Coarse, isothermal hearth; separate net CO chemistry. Not plant validated.");GUILayout.EndArea();
  }
  public void DisposePreview(){if(ActiveView)SetView(false);for(int i=0;i<shells.Count;i++)shells[i].sharedMaterials=oldMaterials[i];if(VisualRoot)DestroyImmediate(VisualRoot);foreach(var m in ownedMeshes)if(m)DestroyImmediate(m);foreach(var m in ownedMaterials)if(m)DestroyImmediate(m);shells.Clear();oldMaterials.Clear();occluders.Clear();oldVisibility.Clear();ownedMeshes.Clear();ownedMaterials.Clear();initialized=false;}
 }
}
