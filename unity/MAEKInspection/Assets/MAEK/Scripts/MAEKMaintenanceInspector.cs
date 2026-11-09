using System;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace MAEK {
 // A waiting inspector with a PDA, not an automatic NDT result or work-permission producer.
 public sealed class MAEKMaintenanceInspector : MonoBehaviour {
  public const string ResourcePath="MAEK/MaintenanceInspector";
  public const float BodyRadius=.5f,BodyHeight=1.8f;
  MAEKInspectorVisual visual;
  public static string LastPlacementStatus {get;private set;}="not_started";

  [RuntimeInitializeOnLoadMethod(RuntimeInitializeLoadType.AfterSceneLoad)]
  static void Install(){SceneManager.sceneLoaded-=SceneLoaded;SceneManager.sceneLoaded+=SceneLoaded;SceneLoaded(SceneManager.GetActiveScene(),LoadSceneMode.Single);}
  static void SceneLoaded(Scene scene,LoadSceneMode mode){
   if(scene.name!="MAEKInspectionDemo")return;
   var tour=UnityEngine.Object.FindFirstObjectByType<MAEKInspectionTour>();
   if(tour)TrySpawn(tour);
  }
  public static MAEKMaintenanceInspector TrySpawn(MAEKInspectionTour tour){
   var existing=UnityEngine.Object.FindFirstObjectByType<MAEKMaintenanceInspector>();if(existing)return existing;
   tour.Initialize();var prefab=Resources.Load<GameObject>(ResourcePath);
   if(!prefab){LastPlacementStatus="missing_prefab";Debug.LogError("MAEK inspector prefab is missing: "+ResourcePath);return null;}
   var actor=Instantiate(prefab);actor.name="MAEK maintenance inspector - waiting with PDA";
   var body=actor.GetComponent<CapsuleCollider>();body.enabled=false;
   var inspector=actor.GetComponent<MAEKMaintenanceInspector>();inspector.InitializeVisual();
   var plans=new List<TourPlan>{tour.Plan};var extra=tour.GetComponent<MAEKSupplementaryCircuits>();
   if(extra&&extra.inspectionRoute)plans.Add(JsonUtility.FromJson<TourPlan>(extra.inspectionRoute.text));
   if(extra&&extra.originalRoute)plans.Add(JsonUtility.FromJson<TourPlan>(extra.originalRoute.text));
   // Candidate waiting positions only. Never relocate plant equipment or alter drone waypoints.
   foreach(var candidate in new[]{new Vector3(-104,0,61.5f),new Vector3(-106,0,62),new Vector3(-110,0,60),new Vector3(-104,0,66),new Vector3(-112,0,66),new Vector3(-116,0,60)}){
    if(!Physics.Raycast(candidate+Vector3.up*2,Vector3.down,out var ground,4,1<<8,QueryTriggerInteraction.Ignore)||ground.normal.y<.95f||Mathf.Abs(ground.point.y-candidate.y)>.5f)continue;
    Vector3 position=new Vector3(candidate.x,ground.point.y+.035f,candidate.z);
    if(Physics.CheckCapsule(position+Vector3.up*BodyRadius,position+Vector3.up*(BodyHeight-BodyRadius),BodyRadius,1<<8,QueryTriggerInteraction.Ignore))continue;
    actor.transform.SetPositionAndRotation(position,Quaternion.Euler(0,90,0));body.enabled=true;Physics.SyncTransforms();
    bool clear=true;foreach(var plan in plans)if(!PreservesRoute(body,plan)||!PreservesViews(body,plan)){clear=false;break;}
    if(clear){LastPlacementStatus="placed";return inspector;}
    body.enabled=false;
   }
   LastPlacementStatus="placement_deferred";actor.SetActive(false);if(Application.isPlaying)Destroy(actor);else DestroyImmediate(actor);
   Debug.LogWarning("MAEK inspector placement deferred: no clear waiting position; equipment and drone routes unchanged");return null;
  }
  public static bool PreservesRoute(CapsuleCollider body,TourPlan plan){
   if(plan?.points==null||plan.points.Length==0)return false;
   float radius=body.radius,height=body.height;
   try{
    // Expand the actor by the drone envelope, then test each complete segment against this collider only.
    body.radius=radius+plan.radius;body.height=height+2*plan.radius;Physics.SyncTransforms();
    for(int i=0;i<plan.points.Length;i++){
     Vector3 a=plan.points[i].position;if((body.ClosestPoint(a)-a).sqrMagnitude<1e-8f)return false;
     if(i==0)continue;Vector3 b=plan.points[i-1].position,d=a-b;
     if(d.sqrMagnitude>1e-8f&&body.Raycast(new Ray(b,d.normalized),out _,d.magnitude))return false;
    }
    return true;
   }finally{body.radius=radius;body.height=height;Physics.SyncTransforms();}
  }
  public static bool PreservesViews(CapsuleCollider body,TourPlan plan){
   if(plan?.points==null)return false;
   foreach(var point in plan.points){
    if(string.IsNullOrEmpty(point.pipeId))continue;var d=point.target-point.position;
    if(d.sqrMagnitude>1e-8f&&body.Raycast(new Ray(point.position,d.normalized),out _,d.magnitude))return false;
   }
   return true;
  }
  public void InitializeVisual(){if(!visual){visual=GetComponent<MAEKInspectorVisual>();visual.Initialize();}}
  void Awake(){InitializeVisual();}
  void LateUpdate(){InitializeVisual();visual.Advance(Time.deltaTime,0,true,0,false);}
 }
}
