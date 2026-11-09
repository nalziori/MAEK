Shader "MAEK/PrintedLabel" {
 Properties { _MainTex("Font atlas",2D)="white" {} }
 SubShader {
  Tags {"Queue"="Transparent" "RenderType"="Transparent"}
  Pass {
   Cull Off ZWrite Off ZTest LEqual Blend SrcAlpha OneMinusSrcAlpha
   CGPROGRAM
   #pragma vertex vert
   #pragma fragment frag
   #include "UnityCG.cginc"
   sampler2D _MainTex;
   struct appdata {float4 vertex:POSITION;float2 uv:TEXCOORD0;fixed4 color:COLOR;};
   struct v2f {float4 vertex:SV_POSITION;float2 uv:TEXCOORD0;fixed4 color:COLOR;};
   v2f vert(appdata v){v2f o;o.vertex=UnityObjectToClipPos(v.vertex);o.uv=v.uv;o.color=v.color;return o;}
   fixed4 frag(v2f i):SV_Target {fixed4 c=i.color;c.a*=tex2D(_MainTex,i.uv).a;clip(c.a-.05);return c;}
   ENDCG
  }
 }
}
