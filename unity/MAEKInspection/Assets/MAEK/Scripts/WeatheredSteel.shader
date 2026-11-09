Shader "MAEK/WeatheredSteel" {
 Properties {
  _Color("Base metal",Color)=(.38,.40,.39,1)
  _Rust("Oxidation",Range(0,1))=.2
  _Metallic("Metallic",Range(0,1))=.4
  _Glossiness("Smoothness",Range(0,1))=.22
  _Ribs("Corrugation",Range(0,1))=0
 }
 SubShader {
  Tags {"RenderType"="Opaque"} LOD 250
  CGPROGRAM
  #pragma surface surf Standard fullforwardshadows
  #pragma target 3.0
  struct Input {float3 worldPos;};
  fixed4 _Color; half _Rust,_Metallic,_Glossiness,_Ribs;
  float hash(float3 p){p=frac(p*.1031);p+=dot(p,p.yzx+33.33);return frac((p.x+p.y)*p.z);}
  float noise(float3 p){float3 i=floor(p),f=frac(p);f=f*f*(3-2*f);
   return lerp(lerp(lerp(hash(i),hash(i+float3(1,0,0)),f.x),lerp(hash(i+float3(0,1,0)),hash(i+float3(1,1,0)),f.x),f.y),
    lerp(lerp(hash(i+float3(0,0,1)),hash(i+float3(1,0,1)),f.x),lerp(hash(i+float3(0,1,1)),hash(i+1),f.x),f.y),f.z);}
  void surf(Input IN,inout SurfaceOutputStandard o){
   float3 p=IN.worldPos;
   float coarse=noise(p*.65),fine=noise(p*19),grain=noise(p*80);
   float streak=noise(p*float3(7,.18,7));
   float rust=smoothstep(1-_Rust*.75,1-_Rust*.75+.13,coarse*.65+streak*.35);
   float3 oxide=lerp(float3(.105,.047,.022),float3(.34,.145,.048),fine);
   float dirt=.84+.06*coarse+.10*fine;
   float phase=(p.x+p.z)*19.5;
   float rib=lerp(.92,.84+.16*smoothstep(.1,.65,abs(sin(phase))),saturate(1-fwidth(phase)*.35));
   float seam=1-.17*(1-smoothstep(.015,.065,abs(frac(p.y/2.1)-.5)));
   o.Albedo=lerp(_Color.rgb*dirt,oxide,rust)*lerp(1,rib*seam,_Ribs)*(.94+.06*grain);
   o.Metallic=lerp(_Metallic,.06,rust);o.Smoothness=lerp(_Glossiness,.07,rust)*(.65+.35*fine);
   o.Occlusion=.9+.1*coarse;o.Alpha=1;
  }
  ENDCG
 }
 FallBack "Standard"
}
