Shader "MAEK/FurnaceSection" {
 Properties { _Color("Color",Color)=(.5,.5,.5,1) _Metallic("Metallic",Range(0,1))=.4 _Glossiness("Smoothness",Range(0,1))=.4 _Section("Section enabled",Float)=0 _SectionZ("Section plane Z",Float)=18 }
 SubShader { Tags { "RenderType"="Opaque" } LOD 200
 CGPROGRAM
 #pragma surface surf Standard fullforwardshadows addshadow
 #pragma target 3.0
 fixed4 _Color;half _Metallic,_Glossiness;float _Section,_SectionZ;
 struct Input {float3 worldPos;};
 void surf(Input IN,inout SurfaceOutputStandard o){if(_Section>.5)clip(_SectionZ-IN.worldPos.z);o.Albedo=_Color.rgb;o.Metallic=_Metallic;o.Smoothness=_Glossiness;o.Alpha=1;}
 ENDCG
 }
 FallBack "Diffuse"
}
