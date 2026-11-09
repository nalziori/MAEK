from pathlib import Path
p=Path('D:/obsd/Projects/hackerton/MAEK/unity/MAEKInspection/Assets/MAEK/Scripts')
f=p/'FurnacePhysics.cs';s=f.read_text(encoding='utf-8-sig').replace('public double InletM3,OutletM3;','public double InletM3,OutletM3,LastOutletM3s;').replace('InletM3+=inflow*dt;OutletM3+=fh[n]*width*dt;','InletM3+=inflow*dt;OutletM3+=fh[n]*width*dt;LastOutletM3s=fh[n]*width;');f.write_text(s,encoding='utf-8')
f=p/'MAEKFurnaceSimulation.cs';s=f.read_text(encoding='utf-8-sig');s=s.replace('Transform[][] markers;','LineRenderer[] fallingJets;\n  Transform[][] markers;');s=s.replace('Baths=new Transform[2];','fallingJets=new LineRenderer[2];Baths=new Transform[2];')
s=s.replace('float endZ=startZ+', '''var fall=new GameObject("Gravity-driven outlet jet "+unit).AddComponent<LineRenderer>();fall.transform.SetParent(VisualRoot.transform,false);fall.sharedMaterial=liquid;fall.positionCount=20;fall.useWorldSpace=true;fall.numCapVertices=4;fall.numCornerVertices=4;fallingJets[unit]=fall;
    float endZ=startZ+''')
s=s.replace('var mesh=new Mesh{name=name};','for(int k=0;k<tris.Count;k+=3){int tmp=tris[k+1];tris[k+1]=tris[k+2];tris[k+2]=tmp;}var mesh=new Mesh{name=name};')
s=s.replace('t.text=text;t.characterSize=size;', 't.font=Resources.GetBuiltinResource<Font>("LegacyRuntime.ttf");go.GetComponent<Renderer>().sharedMaterial=t.font.material;t.text=text;t.characterSize=size;')
s=s.replace('float glow=Mathf.Clamp', '''var falling=fallingJets[unit];falling.enabled=m.Channel.LastOutletM3s>1e-8;
    if(falling.enabled){int end=c.RunnerCells-1;double velocity=Math.Max(.01,m.Channel.Velocity(end));double y0=3.2+c.TapHeightM-c.RunnerLengthM*c.RunnerSlope+m.Channel.Depth[end]*.5;double y1=.4+collectedHeight;double fallTime=Math.Sqrt(2*Math.Max(.001,y0-y1)/9.81);for(int k=0;k<20;k++){double t=k*fallTime/19;falling.SetPosition(k,new Vector3(x,(float)(y0-.5*9.81*t*t),(float)(23.7+c.RunnerLengthM+velocity*t)));}falling.startWidth=(float)Math.Sqrt(4*m.Channel.LastOutletM3s/(Math.PI*velocity));falling.endWidth=(float)Math.Sqrt(4*m.Channel.LastOutletM3s/(Math.PI*Math.Sqrt(velocity*velocity+Math.Pow(9.81*fallTime,2))));}
    float glow=Mathf.Clamp''')
f.write_text(s,encoding='utf-8')
