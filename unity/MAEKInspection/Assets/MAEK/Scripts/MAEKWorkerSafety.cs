using System;
using System.Collections.Generic;
using System.Linq;
using UnityEngine;
namespace MAEK {
 [Serializable] public class WorkerSafetyCase {
  public string id,kind,title,system,work,evidence,source,modelStatus,maekContribution,limit,referenceCircuit;
  public string[] pipeIds;
 }
 [Serializable] public class WorkerSafetyProfile {
  public string serviceCode,mediumLabel,workerContext,inspectionLimit,permissionStatus;
 }
 [Serializable] public class WorkerSafetyData {public int version;public string scope;public WorkerSafetyCase[] cases;public WorkerSafetyProfile[] profiles;}
 public sealed class MAEKWorkerSafety {
  public WorkerSafetyData Data {get;private set;}
  readonly Dictionary<string,WorkerSafetyProfile> profiles=new Dictionary<string,WorkerSafetyProfile>();
  public void Initialize(TextAsset source,PipeServiceData pipes){
   if(Data!=null)return;if(!source)throw new Exception("Missing worker safety context");
   Data=JsonUtility.FromJson<WorkerSafetyData>(source.text);
   if(Data==null||Data.version!=1||Data.cases==null||Data.profiles==null)throw new Exception("Invalid worker safety context");
   foreach(var p in Data.profiles){if(p.permissionStatus!="not_assessed")throw new Exception("Inspection must not approve work");profiles.Add(p.serviceCode,p);}
   if(profiles.Count!=pipes.services.Length||pipes.pipes.Any(p=>!profiles.ContainsKey(p.serviceCode)))throw new Exception("Missing worker safety service");
   var ids=new HashSet<string>(pipes.pipes.Select(p=>p.id));var caseIds=new HashSet<string>();
   foreach(var item in Data.cases){if(!caseIds.Add(item.id)||item.pipeIds==null)throw new Exception("Invalid safety case");
    if(item.kind=="reported_accident"){if(item.modelStatus!="not_modelled"||item.pipeIds.Length!=0||!Uri.TryCreate(item.source,UriKind.Absolute,out var u)||u.Scheme!="https")throw new Exception("Reported accident falsely mapped to synthetic pipe");}
    else if(item.kind!="synthetic_example"||item.modelStatus!="modelled_synthetic"||item.pipeIds.Length==0||item.pipeIds.Any(id=>!ids.Contains(id)))throw new Exception("Invalid synthetic safety example");
    if(string.IsNullOrEmpty(item.limit)||string.IsNullOrEmpty(item.maekContribution))throw new Exception("Missing inspection limit");
   }
   if(Data.cases.Count(c=>c.kind=="reported_accident")!=4)throw new Exception("Missing source accident categories");
  }
  public WorkerSafetyProfile ForService(string code){return profiles[code];}
  public void DrawPipe(ServicePipe pipe,GUIStyle label){var p=ForService(pipe.serviceCode);
   GUILayout.Label("대상 확인: "+p.mediumLabel+" · 가상 배관 / 실제 사고 위치 아님",label);
   GUILayout.Label("작업자 위험 맥락: "+p.workerContext,label);
   GUILayout.Label("작업 안전: 미판정 · "+p.inspectionLimit,label);
  }
  public int DrawCase(int index,GUIStyle label,GUIStyle button){
   index=Mathf.Clamp(index,0,Data.cases.Length-1);
   GUILayout.BeginHorizontal();if(GUILayout.Button("이전 사례",button))index=(index+Data.cases.Length-1)%Data.cases.Length;if(GUILayout.Button("다음 사례",button))index=(index+1)%Data.cases.Length;GUILayout.EndHorizontal();
   var item=Data.cases[index];GUILayout.Label((index+1)+" / "+Data.cases.Length+" · "+item.title,label);
   GUILayout.Label("계통: "+item.system+"\n작업: "+item.work,label);
   GUILayout.Label(item.modelStatus=="not_modelled"?(string.IsNullOrEmpty(item.referenceCircuit)?"현재 장면: 해당 사고 계통 미구현 · 다른 매질로 대체하지 않음":"사고 현장 미구현 · 같은 종류의 공개 참고 계통을 별도 증설: "+item.referenceCircuit+" (E) / 사고 배관과 동일하지 않음"):"현재 장면의 가상 검사 사례: "+string.Join(", ",item.pipeIds),label);
   GUILayout.Label("확인 범위: "+item.evidence,label);GUILayout.Label("MAEK 역할: "+item.maekContribution,label);GUILayout.Label("한계: "+item.limit,label);
   if(item.source!=""&&GUILayout.Button("사고 보도 원문 열기",button))Application.OpenURL(item.source);
   return index;
  }
 }
}
