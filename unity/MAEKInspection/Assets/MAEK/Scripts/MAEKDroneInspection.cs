using System;
using UnityEngine;
namespace MAEK {
 [Serializable] public class DroneWaypoint {public float[] position,target;}
 [Serializable] public class DroneRoute {public string id,from,to;public float radius;public int samples;public DroneWaypoint[] waypoints;}
 [Serializable] public class DroneRouteSet {public DroneRoute[] routes;}
 public sealed class MAEKDroneInspection : MonoBehaviour {
  public TextAsset routeData;public Camera droneCamera,inspectorCamera;public MAEKWalkthrough walker;
  public float speed=2;public int environmentLayer=8;
  DroneRouteSet data;int index,leg;bool active,paused,blocked;float dwell;string message="";
  public static Vector3 V(float[] p){return new Vector3(p[0],p[1],p[2]);}
  public bool InspectionActive {get{return active;}}
  public string CurrentLineId {get{return data==null?"":data.routes[index].id;}}
  void EnsureData(){if(data==null)data=JsonUtility.FromJson<DroneRouteSet>(routeData.text);}
  void Awake(){EnsureData();droneCamera.enabled=false;}
  public void InspectLine(string id){EnsureData();int found=Array.FindIndex(data.routes,r=>r.id==id);if(found<0)throw new ArgumentException("No drone route: "+id);if(!active)Toggle();Select(found);paused=true;}
  public void EndInspection(){if(active)Toggle();}
  void Select(int next){index=(next+data.routes.Length)%data.routes.Length;leg=0;blocked=false;dwell=0;message="";var wp=data.routes[index].waypoints[0];droneCamera.transform.position=V(wp.position);droneCamera.transform.LookAt(V(wp.target));}
  void Toggle(){active=!active;droneCamera.enabled=active;inspectorCamera.enabled=!active;walker.enabled=!active;Cursor.lockState=CursorLockMode.None;if(active)Select(index);}
  void Update(){
   if(Input.GetKeyDown(KeyCode.F))Toggle();if(!active)return;
   if(Input.GetKeyDown(KeyCode.RightArrow))Select(index+1);if(Input.GetKeyDown(KeyCode.LeftArrow))Select(index-1);
   if(Input.GetKeyDown(KeyCode.Space))paused=!paused;if(paused||blocked)return;
   var route=data.routes[index];
   if(leg>=route.waypoints.Length-1){dwell+=Time.deltaTime;if(dwell>1)Select(index+1);return;}
   var next=route.waypoints[leg+1];Vector3 p=droneCamera.transform.position,goal=V(next.position);Vector3 q=Vector3.MoveTowards(p,goal,speed*Time.deltaTime),delta=q-p;
   if(delta.sqrMagnitude>1e-9f&&Physics.SphereCast(p,route.radius,delta.normalized,out var hit,delta.magnitude,1<<environmentLayer,QueryTriggerInteraction.Ignore)){blocked=true;message="Stopped: route obstructed by "+hit.collider.name;return;}
   droneCamera.transform.position=q;Vector3 look=V(next.target)-q;if(look.sqrMagnitude>.001f)droneCamera.transform.rotation=Quaternion.Slerp(droneCamera.transform.rotation,Quaternion.LookRotation(look),Mathf.Min(1,Time.deltaTime*8));
   if((q-goal).sqrMagnitude<.0001f)leg++;
  }
  void OnGUI(){
   if(!active){GUI.Box(new Rect(12,65,540,27),"F: virtual drone inspection — "+(data==null?0:data.routes.Length)+" pipe routes");return;}
   var route=data.routes[index];
   GUI.Box(new Rect(12,12,720,96),"MAEK virtual inspection drone | "+(index+1)+" / "+data.routes.Length+" | "+route.id+"\n"+route.from+" → "+route.to+"\nF: walk | Left/Right: pipe (camera cut) | Space: pause | "+(paused?"PAUSED":blocked?message:"AUTO")+"\nPrechecked 0.12 m radius; flight stops if geometry obstructs route.");
   if(GUI.Button(new Rect(12,114,90,28),"Previous"))Select(index-1);if(GUI.Button(new Rect(108,114,90,28),"Next"))Select(index+1);
   if(GUI.Button(new Rect(204,114,110,28),paused?"Resume":"Pause"))paused=!paused;
  }
 }
}
