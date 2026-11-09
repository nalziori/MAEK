using UnityEngine;
namespace MAEK {
 [ExecuteAlways] public sealed class MAEKPrintedLabel : MonoBehaviour {
  void OnEnable(){Bind(true);Font.textureRebuilt+=Rebuilt;}
  void OnDisable(){Font.textureRebuilt-=Rebuilt;}
  void Rebuilt(Font font){var t=GetComponent<TextMesh>();if(t&&t.font==font)Bind(false);}
  public void Bind(bool request){
   var t=GetComponent<TextMesh>();var r=GetComponent<Renderer>();if(!t||!t.font||!r)return;
   if(request)t.font.RequestCharactersInTexture(t.text,t.fontSize,t.fontStyle);
   var block=new MaterialPropertyBlock();r.GetPropertyBlock(block);block.SetTexture("_MainTex",t.font.material.mainTexture);r.SetPropertyBlock(block);
  }
 }
}
