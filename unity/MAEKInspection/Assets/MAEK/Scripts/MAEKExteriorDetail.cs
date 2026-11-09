using UnityEngine;

namespace MAEK {
 // Only visibility changes in cutaway mode. Physical obstacles remain in the world.
 public sealed class MAEKExteriorDetail : MonoBehaviour {
  Renderer[] renderers;
  bool[] visibility;
  MAEKCFDPlayback cfd;
  public bool IsHidden {get;private set;}
  void Initialize(){
   if(renderers!=null)return;
   renderers=GetComponentsInChildren<Renderer>(true);visibility=new bool[renderers.Length];
   for(int i=0;i<renderers.Length;i++)visibility[i]=renderers[i].enabled;
   cfd=FindFirstObjectByType<MAEKCFDPlayback>();
  }
  public void Refresh(){
   Initialize();bool hide=cfd&&cfd.ActiveView;
   if(hide==IsHidden)return;IsHidden=hide;
   for(int i=0;i<renderers.Length;i++)if(renderers[i])renderers[i].enabled=hide?false:visibility[i];
  }
  void LateUpdate(){Refresh();}
  void OnDisable(){
   if(renderers==null)return;
   for(int i=0;i<renderers.Length;i++)if(renderers[i])renderers[i].enabled=visibility[i];
   IsHidden=false;
  }
 }
}
