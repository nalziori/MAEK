"""Common centerlines for Blender geometry and independent topology/clash validation."""
import math
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def add(a,b):return tuple(x+y for x,y in zip(a,b))
def mul(a,s):return tuple(x*s for x in a)
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def norm(a):return math.sqrt(dot(a,a))
def rounded(line):
 ps=[tuple(p) for p in line["points"]]
 if line.get("exact_polyline"):return ps
 out=[ps[0]]
 for i in range(1,len(ps)-1):
  a,b,c=ps[i-1:i+2];u=sub(b,a);v=sub(c,b);la,lb=norm(u),norm(v);u=mul(u,1/la);v=mul(v,1/lb)
  if dot(u,v)>.999999:out.append(b);continue
  cut=min(line["radius_m"]*3,la*.28,lb*.28)
  start=sub(b,mul(u,cut));end=add(b,mul(v,cut));out.append(start)
  for j in range(1,9):
   t=j/8;out.append(add(add(mul(start,(1-t)**2),mul(b,2*t*(1-t))),mul(end,t*t)))
 out.append(ps[-1]);return out
def closest(a,b,c,d):
 # Closest points on finite segments (including parallel / degenerate cases).
 u=sub(b,a);v=sub(d,c);w=sub(a,c);A=dot(u,u);B=dot(u,v);C=dot(v,v);D=dot(u,w);E=dot(v,w)
 den=A*C-B*B
 s=max(0,min(1,(B*E-C*D)/den)) if den>1e-12 else 0
 t=(B*s+E)/C if C>1e-12 else 0
 if t<0:t=0;s=max(0,min(1,-D/A)) if A>1e-12 else 0
 elif t>1:t=1;s=max(0,min(1,(B-D)/A)) if A>1e-12 else 0
 p=add(a,mul(u,s));q=add(c,mul(v,t))
 return norm(sub(p,q)),p,q

