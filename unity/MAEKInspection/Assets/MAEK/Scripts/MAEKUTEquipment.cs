using UnityEngine;
using System.Collections.Generic;

namespace MAEK {
 // Presentation props only. No colliders, sensor measurements or calibration of the frozen model.
 public sealed class MAEKUTEquipment {
  public readonly Transform Root, Probe, Instrument, Reference, Cloth, Bottle, Gel;
  public readonly LineRenderer Cable;
  readonly List<Material> materials=new List<Material>();
  readonly Transform indicator;
  Material Mat(Color color){var m=new Material(Shader.Find("Unlit/Color")){color=color};materials.Add(m);return m;}
  Transform Part(Transform parent,string name,PrimitiveType shape,Vector3 position,Vector3 scale,Material material){
   var o=GameObject.CreatePrimitive(shape);o.name=name;Object.DestroyImmediate(o.GetComponent<Collider>());o.layer=11;
   o.transform.SetParent(parent,false);o.transform.localPosition=position;o.transform.localScale=scale;o.GetComponent<Renderer>().sharedMaterial=material;return o.transform;
  }
  public MAEKUTEquipment(){
   Root=new GameObject("UT presentation kit (non-physical demonstration props)").transform;
   var orange=Mat(new Color(.95f,.42f,.055f));var rubber=Mat(new Color(.055f,.065f,.08f));var metal=Mat(new Color(.62f,.68f,.73f));var cyan=Mat(new Color(.15f,.8f,.95f));var white=Mat(new Color(.87f,.93f,.96f));
   Instrument=new GameObject("Handheld UT gauge").transform;Instrument.SetParent(Root);
   Part(Instrument,"Rubber bumper",PrimitiveType.Cube,Vector3.zero,new Vector3(.20f,.26f,.075f),rubber);
   Part(Instrument,"Orange housing",PrimitiveType.Cube,new Vector3(0,0,-.006f),new Vector3(.18f,.24f,.075f),orange);
   Part(Instrument,"LCD",PrimitiveType.Cube,new Vector3(0,.038f,-.048f),new Vector3(.145f,.115f,.008f),rubber);
   for(int i=0;i<3;i++)Part(Instrument,"Key "+i,PrimitiveType.Cube,new Vector3((i-1)*.045f,-.067f,-.049f),new Vector3(.03f,.025f,.012f),white);
   // Three sides form a small handle on the side held by the worker.
   Part(Instrument,"Handle upper",PrimitiveType.Cube,new Vector3(.115f,.065f,0),new Vector3(.04f,.018f,.035f),rubber);
   Part(Instrument,"Handle lower",PrimitiveType.Cube,new Vector3(.115f,-.065f,0),new Vector3(.04f,.018f,.035f),rubber);
   Part(Instrument,"Handle grip",PrimitiveType.Cube,new Vector3(.135f,0,0),new Vector3(.018f,.15f,.035f),rubber);
   // Mesh screen markings depth-test normally; no always-on-top text through hands or bodies.
   for(int i=0;i<20;i++){float h=.008f+.06f*Mathf.Exp(-Mathf.Pow((i-5)/1.7f,2))+.045f*Mathf.Exp(-Mathf.Pow((i-15)/1.5f,2));
    Part(Instrument,"Illustrative screen trace "+i,PrimitiveType.Cube,new Vector3(-.063f+i*.0065f,.005f+h*.5f,-.054f),new Vector3(.003f,h,.003f),cyan);}
   indicator=Part(Instrument,"Status indicator",PrimitiveType.Cube,new Vector3(0,.084f,-.055f),new Vector3(.11f,.008f,.003f),cyan);
   Probe=new GameObject("Separate contact probe").transform;Probe.SetParent(Root);
   Part(Probe,"Probe body",PrimitiveType.Cylinder,new Vector3(0,.032f,0),new Vector3(.047f,.032f,.047f),rubber);
   Part(Probe,"Metal contact shoe",PrimitiveType.Cylinder,new Vector3(0,.004f,0),new Vector3(.05f,.004f,.05f),metal);
   Part(Probe,"Cable connector",PrimitiveType.Cylinder,new Vector3(0,.073f,0),new Vector3(.019f,.012f,.019f),orange);
   Reference=new GameObject("Carried reference block - procedure demo only").transform;Reference.SetParent(Root);
   Part(Reference,"Reference block",PrimitiveType.Cube,Vector3.zero,new Vector3(.13f,.035f,.08f),metal);
   Part(Reference,"Reference step",PrimitiveType.Cube,new Vector3(.033f,.027f,0),new Vector3(.062f,.02f,.08f),metal);
   Part(Reference,"Carried reference holder",PrimitiveType.Cube,new Vector3(0,-.028f,0),new Vector3(.15f,.02f,.10f),rubber);
   Cloth=Part(Root,"Surface preparation cloth",PrimitiveType.Cube,Vector3.zero,new Vector3(.085f,.035f,.06f),white);
   Bottle=new GameObject("Couplant bottle").transform;Bottle.SetParent(Root);
   Part(Bottle,"Bottle",PrimitiveType.Cylinder,Vector3.zero,new Vector3(.045f,.06f,.045f),cyan);
   Part(Bottle,"Nozzle",PrimitiveType.Cylinder,new Vector3(0,.078f,0),new Vector3(.012f,.018f,.012f),white);
   Gel=Part(Root,"Couplant visual marker",PrimitiveType.Sphere,Vector3.zero,new Vector3(.07f,.006f,.07f),cyan);
   var line=new GameObject("Flexible UT probe cable");line.transform.SetParent(Root);line.layer=11;Cable=line.AddComponent<LineRenderer>();Cable.positionCount=17;Cable.startWidth=Cable.endWidth=.008f;Cable.sharedMaterial=rubber;
  }
  public void SetDisplay(string text){indicator.localScale=new Vector3(text.Contains("mm")?.11f:.055f,.008f,.003f);}
  public void UpdateCable(){
   var a=Instrument.TransformPoint(new Vector3(-.055f,.14f,0));var b=Probe.TransformPoint(new Vector3(0,.085f,0));
   for(int i=0;i<17;i++){float t=i/16f;Cable.SetPosition(i,Vector3.Lerp(a,b,t)+Vector3.down*(.20f*4*t*(1-t)));}
  }
  public void Dispose(){if(Root)Object.DestroyImmediate(Root.gameObject);foreach(var m in materials)if(m)Object.DestroyImmediate(m);}
 }
}
