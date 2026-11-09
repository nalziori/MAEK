from pathlib import Path
p=Path('D:/obsd/Projects/hackerton/MAEK/unity/MAEKInspection/Assets/MAEK/Editor')
s=(p/'BuildCollisionScene.cs').read_text(encoding='utf-8-sig')
a=s.index(' [Serializable]');b=s.index(' public static class BuildCollisionScene')
s=s[:a]+s[b:]
s=s.replace('class BuildCollisionScene','class BuildDroneScene').replace('MAEK/Build and verify collision environment','MAEK/Build and verify drone inspection')
s=s.replace('unity_interior_report.json','unity_drone_report.json').replace('MAEKInteriorEnvironment.prefab','MAEKDroneEnvironment.prefab').replace('MAEKInterior.unity','MAEKDroneInspection.unity').replace('MAEK_Interior_Ready.unitypackage','MAEK_Drone_Verified.unitypackage')
s=s.replace('mesh.name=id;', 'mesh.name=Safe(id);')
needle='   Physics.SyncTransforms();\n   var report='
insert='''   var droneCamera=new GameObject("Virtual inspection drone camera").AddComponent<Camera>();droneCamera.enabled=false;droneCamera.nearClipPlane=.04f;droneCamera.farClipPlane=1200;droneCamera.fieldOfView=74;droneCamera.backgroundColor=cam.backgroundColor;droneCamera.clearFlags=CameraClearFlags.SolidColor;
   var flight=new GameObject("MAEK per-pipe drone inspection").AddComponent<MAEKDroneInspection>();flight.routeData=AssetDatabase.LoadAssetAtPath<TextAsset>(Base+"/Source/drone_routes.json");flight.droneCamera=droneCamera;flight.inspectorCamera=cam;flight.walker=walk;flight.environmentLayer=env;
   if(flight.routeData==null)throw new Exception("Missing verified drone routes");
   Physics.SyncTransforms();
   var report='''
assert needle in s;s=s.replace(needle,insert)
needle='   Check("metre scale"'
idx=s.index(needle)
insert='''   var droneRoutes=JsonUtility.FromJson<DroneRouteSet>(flight.routeData.text);
   Check("drone coverage",droneRoutes.routes.Length==manifest.pipe_count&&droneRoutes.routes.Select(r=>r.id).Distinct().Count()==manifest.pipe_count,"One route per tagged pipe");
   foreach(var route in droneRoutes.routes){bool safe=true;string detail="Swept sphere clearance; "+route.waypoints.Length+" waypoints";
    for(int i=0;i<route.waypoints.Length;i++){var pos=MAEKDroneInspection.V(route.waypoints[i].position);
     if(Physics.CheckSphere(pos,route.radius,mask,QueryTriggerInteraction.Ignore)){safe=false;detail="Blocked waypoint "+i;break;}
     if(i>0){var prev=MAEKDroneInspection.V(route.waypoints[i-1].position);var delta=pos-prev;
      if(delta.magnitude>.0001f&&Physics.SphereCast(prev,route.radius,delta.normalized,out var obstacle,delta.magnitude,mask,QueryTriggerInteraction.Ignore)){safe=false;detail="Blocked leg "+i+" by "+obstacle.collider.name;break;}}
    }
    Check("drone "+route.id,safe,detail);
   }
'''
s=s[:idx]+insert+s[idx:]
s=s.replace('EditorSceneManager.SaveScene(scene,Base+"/Scenes/MAEKDroneInspection.unity");','if(!EditorSceneManager.SaveScene(scene,Base+"/Scenes/MAEKDroneInspection.unity"))throw new Exception("Scene save failed");')
(p/'BuildDroneScene.cs').write_text(s,encoding='utf-8')
