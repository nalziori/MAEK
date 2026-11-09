using System;
using System.Collections.Generic;
using UnityEngine;
using MAEK.Simulation;
namespace MAEK {
 public sealed class MAEKFurnaceSimulation : MonoBehaviour {
  public TextAsset configuration;public Material sectionTemplate;public Camera processCamera;
  public bool startInProcessView=true;public float simulationSpeed=10;
  public FurnaceModel[] Models {get;private set;}
  public FurnaceInputs[] Inputs {get;private set;}
  public GameObject VisualRoot {get;private set;}
  public bool ProcessView {get;private set;}
  public Transform[] Baths {get;private set;}
  public Transform[][] SurfaceCells {get;private set;}
  readonly List<Renderer> sectionRenderers=new List<Renderer>();readonly List<Material[]> originalMaterials=new List<Material[]>();readonly List<Renderer> hallRenderers=new List<Renderer>();readonly List<bool> hallOriginalEnabled=new List<bool>();
  readonly List<Material> ownedMaterials=new List<Material>();readonly List<Mesh> ownedMeshes=new List<Mesh>();
  Camera[] previousCameras;bool[] previousCameraStates;MAEKWalkthrough walk;MAEKDroneInspection drone;bool previousWalk,previousDrone;
  LineRenderer[] fallingJets;
  Transform[][] markers;Transform[] jets,ladles;Renderer[][] bands;TextMesh[] legends;
  bool initialized,paused,autoTap=true;int selected;double pendingTime;float orbitYaw,orbitPitch,orbitDistance;
  void Start(){Initialize();SetProcessView(startInProcessView);}
  public void Initialize(){if(initialized)return;initialized=true;var c=new FurnaceConfig();if(configuration!=null)JsonUtility.FromJsonOverwrite(configuration.text,c);c.Validate();Models=new[]{new FurnaceModel(c),new FurnaceModel(c)};Inputs=new[]{new FurnaceInputs(),new FurnaceInputs()};
   walk=FindFirstObjectByType<MAEKWalkthrough>();drone=FindFirstObjectByType<MAEKDroneInspection>();
   foreach(var info in FindObjectsByType<MAEKAssetInfo>(FindObjectsSortMode.None)){
    var r=info.GetComponent<Renderer>();if(r==null)continue;
    if(info.assetId=="BF1.BF"||info.assetId=="BF2.BF"||info.assetId=="BF1.TOWER"||info.assetId=="BF2.TOWER"){
     sectionRenderers.Add(r);originalMaterials.Add(r.sharedMaterials);var mats=new Material[r.sharedMaterials.Length];for(int j=0;j<mats.Length;j++){var original=r.sharedMaterials[j];var m=new Material(sectionTemplate);m.color=original.color;if(original.HasProperty("_Metallic"))m.SetFloat("_Metallic",original.GetFloat("_Metallic"));if(original.HasProperty("_Glossiness"))m.SetFloat("_Glossiness",original.GetFloat("_Glossiness"));mats[j]=m;ownedMaterials.Add(m);}r.sharedMaterials=mats;
    }
    if(info.assetId=="BF1.CASTHOUSE"||info.assetId=="BF2.CASTHOUSE"||info.assetId=="BF1.CONVEYOR"||info.assetId=="BF2.CONVEYOR"||info.assetId=="BF1.CASTHOUSE.CRANE"||info.assetId=="BF2.CASTHOUSE.CRANE"){hallRenderers.Add(r);hallOriginalEnabled.Add(r.enabled);}
   }
   VisualRoot=new GameObject("Calculated furnace interiors and tapping runners");VisualRoot.transform.SetParent(transform,false);
   fallingJets=new LineRenderer[2];Baths=new Transform[2];SurfaceCells=new Transform[2][];markers=new Transform[2][];jets=new Transform[2];ladles=new Transform[2];bands=new Renderer[2][];legends=new TextMesh[2];
   var liquid=Material("Liquid iron",new Color(1,.29f,.018f),2);var refractory=Material("Runner refractory",new Color(.26f,.21f,.18f),0);var graphite=Material("Carbon burden",new Color(.10f,.12f,.13f),0);var ore=Material("Oxide burden",new Color(.36f,.12f,.045f),0);var bright=Material("Flow tracer",new Color(1,.82f,.28f),3);
   for(int unit=0;unit<2;unit++){
    float x=unit==0?-62:62;Baths[unit]=HalfCylinder("BF"+(unit+1)+" calculated hearth",new Vector3(x,3.2f,18),5,1,liquid);
    // Symbolic reaction bands: intensity follows reaction power, not a resolved 3-D field.
    bands[unit]=new Renderer[3];for(int j=0;j<3;j++){var mat=Material("Reaction indicator "+unit+" "+j,j==2?new Color(.32f,.16f,.05f):j==1?new Color(.65f,.16f,.035f):new Color(.95f,.3f,.04f),.4f);var band=HalfCylinder("Aggregate reaction indicator "+j,new Vector3(x,10+j*10,18),j==2?3:4.5f,6,mat);bands[unit][j]=band.GetComponent<Renderer>();}
    var coke=HalfCylinder("Coke bed (schematic)",new Vector3(x,5.0f,18),4.8f,2,graphite);
    HalfCylinder("Ore inlet (schematic)",new Vector3(x,39,18),2.2f,2.0f,ore);
    float startZ=23.7f,startY=3.2f+(float)c.TapHeightM;
    var spout=Rod("Taphole bore outer lining",new Vector3(x,startY,18),new Vector3(x,startY,startZ),.13f,refractory);
    jets[unit]=Rod("Calculated taphole stream",new Vector3(x,startY,18),new Vector3(x,startY,startZ+.15f),(float)c.TapDiameterM*.5f,liquid);spout.gameObject.SetActive(false); // Cutaway exposes the bore rather than occluding the calculated jet.
    int n=c.RunnerCells;float dx=(float)c.RunnerLengthM/n,width=(float)c.RunnerWidthM;
    SurfaceCells[unit]=new Transform[n];
    for(int k=0;k<n;k++){
     float z=startZ+(k+.5f)*dx,y=startY-(k+.5f)*dx*(float)c.RunnerSlope;
     Box("Runner bed "+unit+" "+k,new Vector3(x,y-.09f,z),new Vector3(width+.25f,.18f,dx+.005f),refractory);
     for(int side=-1;side<=1;side+=2)Box("Runner side "+unit+" "+k,new Vector3(x+side*(width/2+.065f),y+.22f,z),new Vector3(.13f,.6f,dx+.005f),refractory);
     SurfaceCells[unit][k]=Box("Calculated liquid cell "+unit+" "+k,new Vector3(x,y,z),new Vector3(width,.001f,dx+.002f),liquid);
    }
    markers[unit]=new Transform[12];for(int k=0;k<12;k++)markers[unit][k]=Box("Velocity tracer "+unit+" "+k,new Vector3(x,startY,startZ+k*2),new Vector3(.12f,.025f,.22f),bright);
    var fall=new GameObject("Gravity-driven outlet jet "+unit).AddComponent<LineRenderer>();fall.transform.SetParent(VisualRoot.transform,false);fall.sharedMaterial=liquid;fall.positionCount=20;fall.useWorldSpace=true;fall.numCapVertices=4;fall.numCornerVertices=4;fallingJets[unit]=fall;
    float endZ=startZ+(float)c.RunnerLengthM,endY=startY-(float)c.RunnerLengthM*(float)c.RunnerSlope;
    // Collection vessel and falling stream; outflow is accumulated, not destroyed.
    Box("Receiving ladle floor",new Vector3(x,.23f,endZ+1.3f),new Vector3(3,.3f,3),refractory);
    for(int side=-1;side<=1;side+=2){Box("Receiving ladle wall",new Vector3(x+side*1.5f,1.5f,endZ+1.3f),new Vector3(.18f,2.7f,3.2f),refractory);Box("Receiving ladle wall",new Vector3(x,1.5f,endZ+1.3f+side*1.5f),new Vector3(3,.18f,2.7f),refractory);}
    ladles[unit]=Box("Calculated received iron",new Vector3(x,.4f,endZ+1.3f),new Vector3(2.8f,.01f,2.8f),liquid);
    legends[unit]=Label("BF"+(unit+1)+" physics",new Vector3(x-7,35,19),.35f);
    Label("CO reduction (net)",new Vector3(x-7,29,19),.3f);Label("C reduction (net)",new Vector3(x-7,20,19),.3f);Label("CO generation",new Vector3(x-7,12,19),.3f);
   }
   UpdateVisuals(0);VisualRoot.SetActive(false);
  }
  Material Material(string name,Color color,float emission){var m=new Material(Shader.Find("Standard"));m.name=name;m.color=color;m.SetFloat("_Metallic",.35f);m.SetFloat("_Glossiness",.45f);if(emission>0){m.EnableKeyword("_EMISSION");m.SetColor("_EmissionColor",color*emission);}ownedMaterials.Add(m);return m;}
  Transform Box(string name,Vector3 p,Vector3 size,Material m){var go=GameObject.CreatePrimitive(PrimitiveType.Cube);go.name=name;go.transform.SetParent(VisualRoot.transform,false);go.transform.position=p;go.transform.localScale=size;DestroyImmediate(go.GetComponent<Collider>());go.GetComponent<Renderer>().sharedMaterial=m;return go.transform;}
  Transform Rod(string name,Vector3 a,Vector3 b,float radius,Material m){var go=GameObject.CreatePrimitive(PrimitiveType.Cylinder);go.name=name;go.transform.SetParent(VisualRoot.transform,false);go.transform.position=(a+b)*.5f;go.transform.up=(b-a).normalized;go.transform.localScale=new Vector3(radius*2,(b-a).magnitude*.5f,radius*2);DestroyImmediate(go.GetComponent<Collider>());go.GetComponent<Renderer>().sharedMaterial=m;return go.transform;}
  Transform HalfCylinder(string name,Vector3 p,float radius,float height,Material mat){
   const int n=48;var v=new List<Vector3>();var tris=new List<int>();v.Add(Vector3.zero);v.Add(Vector3.up);
   for(int j=0;j<=n;j++){float t=Mathf.PI+j*Mathf.PI/n;v.Add(new Vector3(Mathf.Cos(t),0,Mathf.Sin(t)));v.Add(new Vector3(Mathf.Cos(t),1,Mathf.Sin(t)));}
   for(int j=0;j<n;j++){int a=2+2*j,b=a+2;tris.AddRange(new[]{a,b,a+1,b,b+1,a+1,0,b,a,1,a+1,b+1});}
   int last=2+2*n;tris.AddRange(new[]{2,3,last,last,3,last+1});for(int k=0;k<tris.Count;k+=3){int tmp=tris[k+1];tris[k+1]=tris[k+2];tris[k+2]=tmp;}var mesh=new Mesh{name=name};mesh.SetVertices(v);mesh.SetTriangles(tris,0);mesh.RecalculateNormals();mesh.RecalculateBounds();ownedMeshes.Add(mesh);
   var go=new GameObject(name,typeof(MeshFilter),typeof(MeshRenderer));go.transform.SetParent(VisualRoot.transform,false);go.transform.position=p;go.transform.localScale=new Vector3(radius,height,radius);go.GetComponent<MeshFilter>().sharedMesh=mesh;go.GetComponent<MeshRenderer>().sharedMaterial=mat;return go.transform;
  }
  TextMesh Label(string text,Vector3 p,float size){var go=new GameObject(text);go.transform.SetParent(VisualRoot.transform,false);go.transform.position=p;go.transform.rotation=Quaternion.Euler(0,180,0);var t=go.AddComponent<TextMesh>();t.font=Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");go.GetComponent<Renderer>().sharedMaterial=t.font.material;t.text=text;t.characterSize=size;t.fontSize=40;t.color=new Color(1,.9f,.66f);return t;}
  public void SetProcessView(bool active){Initialize();if(active==ProcessView)return;ProcessView=active;
   if(active){previousCameras=FindObjectsByType<Camera>(FindObjectsSortMode.None);previousCameraStates=new bool[previousCameras.Length];for(int k=0;k<previousCameras.Length;k++){previousCameraStates[k]=previousCameras[k].enabled;previousCameras[k].enabled=false;}if(walk){previousWalk=walk.enabled;walk.enabled=false;}if(drone){previousDrone=drone.enabled;drone.enabled=false;}processCamera.enabled=true;Cursor.lockState=CursorLockMode.None;Focus();}
   else{if(previousCameras!=null)for(int k=0;k<previousCameras.Length;k++)if(previousCameras[k])previousCameras[k].enabled=previousCameraStates[k];if(walk)walk.enabled=previousWalk;if(drone)drone.enabled=previousDrone;processCamera.enabled=false;}
   foreach(var r in sectionRenderers)foreach(var m in r.sharedMaterials)m.SetFloat("_Section",active?1:0);
   for(int k=0;k<hallRenderers.Count;k++)hallRenderers[k].enabled=active?false:hallOriginalEnabled[k];VisualRoot.SetActive(active);
  }
  void Focus(){var offset=new Vector3(18,21,65);orbitDistance=offset.magnitude;orbitYaw=Mathf.Atan2(offset.x,offset.z)*Mathf.Rad2Deg;orbitPitch=Mathf.Asin(offset.y/orbitDistance)*Mathf.Rad2Deg;Orbit();}
  void Orbit(){float x=selected==0?-62:62;var target=new Vector3(x,23,25);processCamera.transform.position=target+Quaternion.Euler(-orbitPitch,orbitYaw,0)*Vector3.forward*orbitDistance;processCamera.transform.LookAt(target);}
  public void Advance(double seconds){Initialize();double left=seconds;while(left>1e-9){double dt=Math.Min(.05,left);for(int k=0;k<2;k++){if(autoTap)Inputs[k].TapOpening=Models[k].TimeSeconds>=30-1e-8&&Models[k].TimeSeconds<400-1e-8?1:0;Models[k].Step(dt,Inputs[k]);}UpdateVisuals(dt);left-=dt;}}
  void UpdateVisuals(double dt){for(int unit=0;unit<2;unit++){var m=Models[unit];var c=m.Config;float x=unit==0?-62:62;var bath=Baths[unit];bath.localScale=new Vector3(5,(float)Math.Max(.0001,m.HeadM),5);bath.gameObject.SetActive(m.LiquidIronKg>.001);jets[unit].gameObject.SetActive(m.TapKgPerSecond>1e-6);
    for(int k=0;k<c.RunnerCells;k++){float h=(float)m.Channel.Depth[k];var cell=SurfaceCells[unit][k];float baseY=3.2f+(float)c.TapHeightM-(k+.5f)*(float)c.RunnerLengthM/c.RunnerCells*(float)c.RunnerSlope;cell.position=new Vector3(x,baseY+h/2,cell.position.z);cell.localScale=new Vector3((float)c.RunnerWidthM,Mathf.Max(.00001f,h),(float)c.RunnerLengthM/c.RunnerCells+.002f);cell.gameObject.SetActive(h>1e-6);}
    foreach(var marker in markers[unit]){double distance=marker.position.z-23.7;int k=Math.Max(0,Math.Min(c.RunnerCells-1,(int)(distance/c.RunnerLengthM*c.RunnerCells)));distance+=m.Channel.Velocity(k)*dt;if(distance>=c.RunnerLengthM||distance<0)distance=0;k=Math.Max(0,Math.Min(c.RunnerCells-1,(int)(distance/c.RunnerLengthM*c.RunnerCells)));marker.position=new Vector3(x,(float)(3.2+c.TapHeightM-distance*c.RunnerSlope+m.Channel.Depth[k]+.02),23.7f+(float)distance);marker.gameObject.SetActive(m.Channel.Depth[k]>.0001);}
    double collectedHeight=m.Channel.OutletM3/(2.8*2.8);ladles[unit].localScale=new Vector3(2.8f,(float)Math.Max(.00001,collectedHeight),2.8f);ladles[unit].position=new Vector3(x,.4f+(float)collectedHeight/2,ladles[unit].position.z);ladles[unit].gameObject.SetActive(collectedHeight>1e-6);
    var falling=fallingJets[unit];falling.enabled=m.Channel.LastOutletM3s>1e-8;
    if(falling.enabled){int end=c.RunnerCells-1;double velocity=Math.Max(.01,m.Channel.Velocity(end));double y0=3.2+c.TapHeightM-c.RunnerLengthM*c.RunnerSlope+m.Channel.Depth[end]*.5;double y1=.4+collectedHeight;double fallTime=Math.Sqrt(2*Math.Max(.001,y0-y1)/9.81);for(int k=0;k<20;k++){double t=k*fallTime/19;falling.SetPosition(k,new Vector3(x,(float)(y0-.5*9.81*t*t),(float)(23.7+c.RunnerLengthM+velocity*t)));}falling.startWidth=(float)Math.Sqrt(4*m.Channel.LastOutletM3s/(Math.PI*velocity));falling.endWidth=(float)Math.Sqrt(4*m.Channel.LastOutletM3s/(Math.PI*Math.Sqrt(velocity*velocity+Math.Pow(9.81*fallTime,2))));}
    float glow=Mathf.Clamp((float)m.LastReactionWatts/1.5e8f,.05f,2);foreach(var band in bands[unit])band.sharedMaterial.SetColor("_EmissionColor",band.sharedMaterial.color*glow);
    legends[unit].text="BF"+(unit+1)+"  "+(m.TemperatureK-273.15).ToString("F0")+" C\n"+m.TapKgPerSecond.ToString("F1")+" kg/s  |  "+(m.LiquidIronKg/1000).ToString("F1")+" t";
   }}
  void Update(){if(Input.GetKeyDown(KeyCode.P))SetProcessView(!ProcessView);if(!ProcessView)return;if(Input.GetMouseButton(1)){orbitYaw+=Input.GetAxis("Mouse X")*2;orbitPitch=Mathf.Clamp(orbitPitch-Input.GetAxis("Mouse Y")*2,5,70);Orbit();}float zoom=Input.GetAxis("Mouse ScrollWheel");if(Mathf.Abs(zoom)>.001f){orbitDistance=Mathf.Clamp(orbitDistance-zoom*25,35,140);Orbit();}if(Input.GetKeyDown(KeyCode.Alpha1)){selected=0;Focus();}if(Input.GetKeyDown(KeyCode.Alpha2)){selected=1;Focus();}if(Input.GetKeyDown(KeyCode.Space))paused=!paused;if(!paused){pendingTime+=Time.unscaledDeltaTime*simulationSpeed;double advance=Math.Min(1,pendingTime);Advance(advance);pendingTime-=advance;}}
  public void DisposePreview(){if(ProcessView)SetProcessView(false);for(int k=0;k<sectionRenderers.Count;k++)if(sectionRenderers[k])sectionRenderers[k].sharedMaterials=originalMaterials[k];if(VisualRoot)DestroyImmediate(VisualRoot);foreach(var m in ownedMaterials)if(m)DestroyImmediate(m);foreach(var m in ownedMeshes)if(m)DestroyImmediate(m);initialized=false;}
  void OnGUI(){if(!initialized)return;if(!ProcessView){GUI.Box(new Rect(12,150,540,28),"P: furnace reactions and molten-iron flow");return;}var m=Models[selected];var input=Inputs[selected];GUI.Box(new Rect(12,12,380,530),"");GUILayout.BeginArea(new Rect(24,22,354,510));GUILayout.Label("MAEK | BF"+(selected+1)+" REACTION + TAPPING");GUILayout.Label("P: return | 1/2: furnace | Space: pause\nRight mouse: orbit | Wheel: zoom");GUILayout.Label("Reduced-order / pure-iron proxy");GUILayout.Space(8);GUILayout.Label("Time "+m.TimeSeconds.ToString("F1")+" s   Temperature "+(m.TemperatureK-273.15).ToString("F1")+" C");GUILayout.Label("Liquid "+(m.LiquidIronKg/1000).ToString("F2")+" t   Head "+m.HeadM.ToString("F3")+" m");GUILayout.Label("Tap "+m.TapKgPerSecond.ToString("F2")+" kg/s   Produced "+(m.ProducedIronKg/1000).ToString("F2")+" t");GUILayout.Label("CO/(CO+CO2) "+(m.COFraction*100).ToString("F1")+"%   Reaction "+(m.LastReactionWatts/1e6).ToString("F1")+" MW");GUILayout.Label("Runner "+m.Channel.VolumeM3.ToString("F3")+" m3   Received "+(m.Channel.OutletM3*m.Config.IronDensityKgM3/1000).ToString("F2")+" t");GUILayout.BeginHorizontal();if(GUILayout.Button(input.TapOpening>0?"Close taphole":"Open taphole")){autoTap=false;input.TapOpening=input.TapOpening>0?0:1;}if(GUILayout.Button(paused?"Resume":"Pause"))paused=!paused;GUILayout.EndHorizontal();
   GUILayout.Label("Blast oxygen "+(input.OxygenMoleFraction*100).ToString("F0")+"%");input.OxygenMoleFraction=GUILayout.HorizontalSlider((float)input.OxygenMoleFraction,.15f,.35f);
   GUILayout.Label("Blast temperature "+(input.BlastTemperatureK-273.15).ToString("F0")+" C");input.BlastTemperatureK=GUILayout.HorizontalSlider((float)input.BlastTemperatureK,1073.15f,1673.15f);
   GUILayout.Label("Ore feed "+input.OreKgPerSecond.ToString("F1")+" kg/s");input.OreKgPerSecond=GUILayout.HorizontalSlider((float)input.OreKgPerSecond,0,70);
   GUILayout.Label("Coke feed "+input.CokeKgPerSecond.ToString("F1")+" kg/s");input.CokeKgPerSecond=GUILayout.HorizontalSlider((float)input.CokeKgPerSecond,0,35);
   GUILayout.Label("Speed "+simulationSpeed.ToString("F0")+"x");simulationSpeed=GUILayout.HorizontalSlider(simulationSpeed,1,20);
   GUILayout.Label("Mass residual "+m.MassResidualKg.ToString("E1")+" kg | Heat residual "+m.EnergyResidualJ.ToString("E1")+" J");GUILayout.EndArea();}
 }
}
