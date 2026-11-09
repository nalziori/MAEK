Shader "MAEK/CFDSurface" {
 Properties { _Color ("Color",Color)=(1,0.25,0.02,1) _Section ("Section",Float)=1 }
 SubShader { Tags {"RenderType"="Opaque"} Cull Off
 CGPROGRAM
 #pragma surface surf Standard fullforwardshadows
 #pragma target 3.0
 fixed4 _Color; float _Section;
 struct Input { float3 worldPos; };
 void surf(Input IN,inout SurfaceOutputStandard o) {
  if(_Section>0.5) clip(18.001-IN.worldPos.z);
  o.Albedo=_Color.rgb; o.Emission=_Color.rgb*0.18; o.Metallic=0.35;
  o.Smoothness=0.6; o.Alpha=1;
 }
 ENDCG
 } Fallback "Standard"
}
