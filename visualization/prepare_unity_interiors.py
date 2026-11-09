from pathlib import Path
root=Path("D:/obsd/Projects/hackerton/MAEK/unity/MAEKInspection")
p=root/"Assets/MAEK/Editor/BuildCollisionScene.cs"
s=p.read_text(encoding="utf-8-sig")
if "class InteriorRoom" not in s:
 s=s.replace('[Serializable] public class Check', '[Serializable] public class InteriorRoom {public string id,kind;public float x,y,width,depth,height;}\n [Serializable] public class InteriorRooms {public InteriorRoom[] rooms;}\n [Serializable] public class Check')
 s=s.replace('using(var reader=new BinaryReader', 'AssetDatabase.StartAssetEditing();\n   try {\n   using(var reader=new BinaryReader')
 s=s.replace('var sun=new GameObject("Daylight")', '} finally { AssetDatabase.StopAssetEditing(); }\n   var indoor=JsonUtility.FromJson<InteriorRooms>(File.ReadAllText(Base+"/Source/interior_rooms.json"));\n   foreach(var room in indoor.rooms)foreach(float offset in new[]{-.3f,0f,.3f}) {var lamp=new GameObject(room.id+" interior light").AddComponent<Light>();lamp.type=LightType.Point;lamp.intensity=3;lamp.range=Mathf.Max(room.width,room.height)*1.25f;lamp.color=new Color(1,.94f,.84f);lamp.transform.position=new Vector3(room.x,room.height-1.3f,room.y+room.depth*offset);}\n   var sun=new GameObject("Daylight")')
 s=s.replace('var saved=person.transform.position;', '''foreach(var room in indoor.rooms){
    bool open=true;
    for(float zz=room.y-room.depth/2-1;zz<room.y+room.depth/2-.8f;zz+=.4f)
     if(Physics.CheckCapsule(new Vector3(room.x,.5f,zz),new Vector3(room.x,1.7f,zz),.3f,mask,QueryTriggerInteraction.Ignore))open=false;
    Check("walkable interior "+room.id,open,"Door and central aisle capsule clearance");
   }
   var saved=person.transform.position;
   cc.enabled=false;person.transform.position=new Vector3(-62,.2f,39);cc.enabled=true;Physics.SyncTransforms();
   for(int i=0;i<160;i++){cc.Move(new Vector3(0,-.06f,.075f));Physics.SyncTransforms();}
   Check("character enters cast house",person.transform.position.z>50&&person.transform.position.y<.3f,"Entry end "+person.transform.position.ToString("F3"));
   cc.enabled=false;person.transform.position=saved;cc.enabled=true;
   ''')
 s=s.replace('unity_collision_report.json','unity_interior_report.json').replace('MAEKEnvironment.prefab','MAEKInteriorEnvironment.prefab').replace('Scenes/MAEKInspection.unity','Scenes/MAEKInterior.unity').replace('MAEK_Collision_Ready.unitypackage','MAEK_Interior_Ready.unitypackage')
p.write_text(s,encoding="utf-8")

