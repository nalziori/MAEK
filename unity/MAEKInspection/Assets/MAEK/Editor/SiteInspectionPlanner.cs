using System;
using System.Collections.Generic;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using UnityEngine;

namespace MAEK.Editor {
 // Plans on the completed scene. Geometry is never removed or relocated by this planner.
 public static class SiteInspectionPlanner {
  public const float BodyRadius=.24f, ClearanceMargin=.10f, Radius=BodyRadius+ClearanceMargin;
  const int Mask=1<<8, NodeBudget=8000;
  static readonly Dictionary<float,Dictionary<Vector3Int,bool>> occupancy=new Dictionary<float,Dictionary<Vector3Int,bool>>();
  [Serializable] class Shape {public string path,type;public Vector3 position,scale,centre,size;public Quaternion rotation;}
  public static string LayoutSignature(){
   Physics.SyncTransforms();var rows=new List<string>();
   foreach(var c in UnityEngine.Object.FindObjectsByType<Collider>(FindObjectsSortMode.None).Where(c=>c.gameObject.layer==8)){
    string path=c.name;for(var p=c.transform.parent;p;p=p.parent)path=p.name+"/"+path;
    rows.Add(JsonUtility.ToJson(new Shape{path=path,type=c.GetType().Name,position=c.transform.position,rotation=c.transform.rotation,scale=c.transform.lossyScale,centre=c.bounds.center,size=c.bounds.size}));
   }
   using(var hash=SHA256.Create())return BitConverter.ToString(hash.ComputeHash(Encoding.UTF8.GetBytes(string.Join("\n",rows.OrderBy(s=>s,StringComparer.Ordinal))))).Replace("-","").ToLowerInvariant();
  }
  public static bool Clear(Vector3 a,Vector3 b,float radius=Radius){
   if(Physics.CheckSphere(a,radius,Mask,QueryTriggerInteraction.Ignore)||Physics.CheckSphere(b,radius,Mask,QueryTriggerInteraction.Ignore))return false;
   var d=b-a;return d.sqrMagnitude<1e-8f||!Physics.SphereCast(a,radius,d.normalized,out _,d.magnitude,Mask,QueryTriggerInteraction.Ignore);
  }
  static string Blockers(Vector3 position)=>string.Join(" / ",Physics.OverlapSphere(position,Radius,Mask,QueryTriggerInteraction.Ignore).Select(c=>c.name).Distinct().OrderBy(n=>n).Take(4));
  public static int VisibleSamples(Vector3 position,Vector3 target,string id){
   var direction=target-position;if(direction.sqrMagnitude<1e-8f)return 0;
   var rotation=Quaternion.LookRotation(direction);float tangent=Mathf.Tan(52*Mathf.Deg2Rad*.5f);int visible=0;
   for(int y=-2;y<=2;y++)for(int x=-2;x<=2;x++){
    var ray=rotation*new Vector3(x*.024f*tangent*16/9,y*.024f*tangent,1).normalized;
    if(Physics.Raycast(position,ray,out var hit,250,Mask,QueryTriggerInteraction.Ignore)&&MAEKSupplementaryCircuits.TargetId(hit.collider)==id)visible++;
   }
   return visible;
  }
  static List<Vector3> Path(Vector3 start,Vector3 end){
   if(!Clear(start,start)||!Clear(end,end))return null;
   if(Clear(start,end))return new List<Vector3>{start,end};
   foreach(float rise in new[]{2f,6f,14f,30f}){
    float height=Mathf.Max(start.y,end.y)+rise;var a=new Vector3(start.x,height,start.z);var b=new Vector3(end.x,height,end.z);
    if(Clear(start,a)&&Clear(a,b)&&Clear(b,end))return new List<Vector3>{start,a,b,end};
   }
   foreach(float grid in new[]{2f,1f,.5f}){var path=Search(start,end,grid);if(path!=null)return path;}
   return null;
  }
  static List<Vector3> Search(Vector3 start,Vector3 end,float step){
   var min=Vector3.Min(start,end)-new Vector3(20,8,20);var max=Vector3.Max(start,end)+new Vector3(20,30,20);min.y=Mathf.Max(Radius+.02f,min.y);
   if(!occupancy.TryGetValue(step,out var cache)){cache=new Dictionary<Vector3Int,bool>();occupancy[step]=cache;}
   Func<Vector3Int,Vector3> position=k=>new Vector3(k.x*step,k.y*step,k.z*step);
   Func<Vector3Int,bool> free=k=>{var p=position(k);if(p.x<min.x||p.x>max.x||p.y<min.y||p.y>max.y||p.z<min.z||p.z>max.z)return false;if(!cache.TryGetValue(k,out bool value)){value=Clear(p,p);cache[k]=value;}return value;};
   var queue=new SortedSet<Tuple<float,int>>();var nodes=new Dictionary<int,Vector3Int>();var costs=new Dictionary<Vector3Int,float>();var previous=new Dictionary<Vector3Int,Vector3Int>();int serial=0;
   var centre=Vector3Int.RoundToInt(start/step);
   for(int x=-2;x<=2;x++)for(int y=-2;y<=2;y++)for(int z=-2;z<=2;z++){
    var k=centre+new Vector3Int(x,y,z);if(!free(k)||!Clear(start,position(k)))continue;
    float cost=Vector3.Distance(start,position(k));costs[k]=cost;nodes[serial]=k;queue.Add(Tuple.Create(cost+Vector3.Distance(position(k),end),serial++));
   }
   var closed=new HashSet<Vector3Int>();var directions=new[]{Vector3Int.right,Vector3Int.left,Vector3Int.up,Vector3Int.down,new Vector3Int(0,0,1),new Vector3Int(0,0,-1)};Vector3Int goal=default;bool found=false;
   while(queue.Count>0&&closed.Count<NodeBudget){
    var item=queue.Min;queue.Remove(item);var key=nodes[item.Item2];if(!closed.Add(key))continue;var point=position(key);
    if(Vector3.Distance(point,end)<step*2.5f&&Clear(point,end)){goal=key;found=true;break;}
    foreach(var d in directions){var next=key+d;if(closed.Contains(next)||!free(next)||!Clear(point,position(next)))continue;float cost=costs[key]+step;if(costs.TryGetValue(next,out float old)&&cost>=old)continue;costs[next]=cost;previous[next]=key;nodes[serial]=next;queue.Add(Tuple.Create(cost+Vector3.Distance(position(next),end),serial++));}
   }
   if(!found)return null;
   var reverse=new List<Vector3>{end,position(goal)};while(previous.ContainsKey(goal)){goal=previous[goal];reverse.Add(position(goal));}reverse.Add(start);reverse.Reverse();
   var smooth=new List<Vector3>{start};int at=0;while(at<reverse.Count-1){int next=reverse.Count-1;while(next>at+1&&!Clear(reverse[at],reverse[next]))next--;smooth.Add(reverse[next]);at=next;}return smooth;
  }
  static void Transit(List<TourPoint> points,List<Vector3> path,Vector3 target,string id){
   for(int i=1;i<path.Count;i++){
    var a=path[i-1];var b=path[i];int count=Mathf.Max(1,Mathf.CeilToInt(Vector3.Distance(a,b)/8));
    for(int j=1;j<=count;j++)points.Add(new TourPoint{position=Vector3.Lerp(a,b,(float)j/count),target=target,speed=8,routePipeId=id,phase="transit"});
   }
  }
  public static TourPlan Build(TourPlan legacy){
   Physics.SyncTransforms();occupancy.Clear();
   var start=legacy.points[0];if(!Clear(start.position,start.position))throw new Exception("Site overview position is obstructed; choose an operator launch location without moving equipment");
   var points=new List<TourPoint>{new TourPoint{position=start.position,target=start.target,speed=8,phase="overview"}};
   var access=new List<InspectionAccess>();var visits=new List<PipeVisit>();var transfers=new List<PipeTransfer>();string previousPipe="OVERVIEW";
   foreach(var visit in legacy.visits){
    var samples=legacy.points.Where(p=>p.pipeId==visit.pipeId).ToArray();int first=-1,last=-1,scheduled=0;
    foreach(var sample in samples){
     var row=new InspectionAccess{pipeId=sample.pipeId,sampleId=sample.sampleId,position=sample.position,target=sample.target,sourceIndex=sample.sourceIndex,accessible=false};
     if(!Clear(sample.position,sample.position)){row.status="blocked_clearance";row.reason="기체 반경 0.24m + 여유 0.10m 간섭: "+Blockers(sample.position);}
     else if(VisibleSamples(sample.position,sample.target,sample.pipeId)==0){row.status="occluded";row.reason="설비·배관 가림으로 대상 표면 시선 미확보";}
     else{
      var path=Path(points.Last().position,sample.position);
      if(path==null){row.status="no_route";row.reason="고정 설비에서 연속 이동 경로 미확보 (탐색 2/1/0.5m, 각 "+NodeBudget+"노드; 절대 접근 불가 판정 아님)";}
      else{
       int transitStart=points.Count-1;Transit(points,path,sample.target,sample.pipeId);
       if(scheduled==0)transfers.Add(new PipeTransfer{fromPipe=previousPipe,toPipe=sample.pipeId,firstLeg=transitStart,lastLeg=points.Count-1,length=path.Zip(path.Skip(1),(a,b)=>Vector3.Distance(a,b)).Sum()});
       points.Add(new TourPoint{position=sample.position,target=sample.target,speed=3,dwell=.4f,pipeId=sample.pipeId,routePipeId=sample.pipeId,phase="inspection",sourceIndex=sample.sourceIndex,sampleId=sample.sampleId});
       if(first<0)first=points.Count-1;last=points.Count-1;scheduled++;previousPipe=sample.pipeId;row.accessible=true;row.status="accessible";row.reason="기체 여유·대상 시야·연속 경로 확보; 아직 관측 완료를 뜻하지 않음";
      }
     }
     access.Add(row);
    }
    visits.Add(new PipeVisit{pipeId=visit.pipeId,firstLeg=first,lastLeg=last,captures=scheduled,requiredCaptures=samples.Length,accessStatus=scheduled==0?"deferred":scheduled<samples.Length?"partial":"accessible",accessReasons=access.Where(a=>a.pipeId==visit.pipeId&&!a.accessible).Select(a=>a.status).Distinct().OrderBy(s=>s).ToArray()});
    Debug.Log("MAEK_SITE_ACCESS "+visits.Count+"/"+legacy.pipeIds.Length+" "+visit.pipeId+" scheduled="+scheduled+"/"+samples.Length);
   }
   var result=new TourPlan{version=3,siteFirst=true,bodyRadius=BodyRadius,clearanceMargin=ClearanceMargin,radius=Radius,requiredCaptures=access.Count,basis="Layout first; fixed generated equipment. Generic 0.48m spherical drone + assumed 0.10m clearance. Bounded route search and sampled sightlines, not actual POSCO as-built or flight authorization. Unscheduled observations remain deferred.",pipeIds=legacy.pipeIds,points=points.ToArray(),visits=visits.ToArray(),transfers=transfers.ToArray(),expectedCaptures=access.Count(a=>a.accessible),access=access.ToArray()};
   for(int i=1;i<points.Count;i++){if(!Clear(points[i-1].position,points[i].position))throw new Exception("Site plan segment obstructed "+i);result.distanceM+=Vector3.Distance(points[i-1].position,points[i].position);}
   if(result.expectedCaptures==0)Debug.LogWarning("No accessible observations. Catalogue retained as inspection deferred.");
   return result;
  }
 }
}
