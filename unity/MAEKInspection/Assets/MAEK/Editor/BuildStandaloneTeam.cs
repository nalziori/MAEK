using System;
using System.IO;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEngine;
namespace MAEK.Editor {
 public static class BuildStandaloneTeam {
  public static void Configure(){
   var graphics=new SerializedObject(AssetDatabase.LoadAllAssetsAtPath("ProjectSettings/GraphicsSettings.asset")[0]);var included=graphics.FindProperty("m_AlwaysIncludedShaders");
   foreach(var name in new[]{"Unlit/Color","MAEK/WeatheredSteel","MAEK/CFDSurface","MAEK/CFDField"}){var shader=Shader.Find(name);if(!shader)throw new Exception("Missing runtime shader "+name);bool found=false;for(int i=0;i<included.arraySize;i++)if(included.GetArrayElementAtIndex(i).objectReferenceValue==shader)found=true;if(!found){int i=included.arraySize;included.InsertArrayElementAtIndex(i);included.GetArrayElementAtIndex(i).objectReferenceValue=shader;}}
   graphics.ApplyModifiedPropertiesWithoutUndo();AssetDatabase.SaveAssets();
   PlayerSettings.companyName="MAEK";PlayerSettings.productName="MAEK Simulator";PlayerSettings.SetScriptingBackend(UnityEditor.Build.NamedBuildTarget.Standalone,ScriptingImplementation.Mono2x);PlayerSettings.insecureHttpOption=InsecureHttpOption.AlwaysAllowed;PlayerSettings.defaultIsFullScreen=false;PlayerSettings.fullScreenMode=FullScreenMode.Windowed;PlayerSettings.defaultScreenWidth=1280;PlayerSettings.defaultScreenHeight=720;
  }
  public static void Run(){try{Configure();
   string output=Path.GetFullPath("../../visualization/standalone_release/20261109_oxygen_sinter/dist/MAEK/Player/MAEK_Player.exe");Directory.CreateDirectory(Path.GetDirectoryName(output));
   var result=BuildPipeline.BuildPlayer(new BuildPlayerOptions{scenes=new[]{"Assets/MAEK/Scenes/MAEKInspectionDemo.unity"},locationPathName=output,target=BuildTarget.StandaloneWindows64,options=BuildOptions.None});if(result.summary.result!=BuildResult.Succeeded)throw new Exception("Standalone build failed: "+result.summary.result);
   Debug.Log("MAEK_WINDOWS_BUILD_PASS "+output+" bytes="+result.summary.totalSize);if(Application.isBatchMode)EditorApplication.Exit(0);
  }catch(Exception e){Debug.LogException(e);if(Application.isBatchMode)EditorApplication.Exit(1);else throw;}}
 }
}
