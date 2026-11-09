// Reduced-order reactor + single-liquid hearth + conservative 1-D runner.
// No Unity dependencies: this exact source is exercised by the standalone checks.
using System;
namespace MAEK.Simulation {
 [Serializable] public sealed class FurnaceConfig {
  public double ReferenceTemperatureK=298.15,MeltingTemperatureK=1809,LatentHeatJkg=247000;
  public double InitialTemperatureK=1883.15,InitialOreKg=50000,InitialCokeKg=60000,InitialIronKg=300000;
  public double InitialCOKg=120,InitialCO2Kg=20,InitialNitrogenKg=500;
  public double MatrixHeatCapacityJK=2e9,HeatLossWPerK=15000,GasResidenceSeconds=6;
  public bool VentEnabled=true;
  public double HearthRadiusM=5,HearthVoidFraction=.4,IronDensityKgM3=7000;
  public double TapDiameterM=.06,TapLengthM=2,TapHeightM=.35,TapRoughnessM=.001,TapMinorLoss=2.5;
  public double IronViscosityPas=.006,ViscosityReferenceK=1850,ViscosityActivationJmol=28000;
  public double CombustionRatePerSecond=20,ReductionRatePerSecond=.001,DirectRatePerSecond=.00002;
  public double ReductionActivationJmol=60000,DirectActivationJmol=90000,RateReferenceK=1700,MinimumCOFraction=.55;
  public double RunnerLengthM=24,RunnerWidthM=1.2,RunnerSlope=.015,RunnerManning=.020;
  public int RunnerCells=48;
  public double[] HeatCapacityJkgK={800,800,800,1000,918,1040,840,1040};
  public void Validate(){
   foreach(double x in new[]{MeltingTemperatureK,LatentHeatJkg,InitialTemperatureK,MatrixHeatCapacityJK,GasResidenceSeconds,HearthRadiusM,HearthVoidFraction,IronDensityKgM3,TapDiameterM,TapLengthM,TapMinorLoss,IronViscosityPas,RunnerLengthM,RunnerWidthM,RunnerManning})if(!Valid(x)||x<=0)throw new ArgumentException("Positive finite physical parameter required");
   foreach(double x in new[]{InitialOreKg,InitialCokeKg,InitialIronKg,InitialCOKg,InitialCO2Kg,InitialNitrogenKg,HeatLossWPerK,TapHeightM,TapRoughnessM,RunnerSlope,CombustionRatePerSecond,ReductionRatePerSecond,DirectRatePerSecond})if(!Valid(x)||x<0)throw new ArgumentException("Nonnegative finite physical parameter required");
   if(HearthVoidFraction>1||MinimumCOFraction<0||MinimumCOFraction>=1||RunnerCells<4||RunnerCells>1024||HeatCapacityJkgK==null||HeatCapacityJkgK.Length!=8||InitialTemperatureK<ReferenceTemperatureK)throw new ArgumentException("Invalid physical configuration");
   foreach(double cp in HeatCapacityJkgK)if(!Valid(cp)||cp<=0)throw new ArgumentException("Invalid heat capacity");
  }
  public static bool Valid(double x){return !double.IsNaN(x)&&!double.IsInfinity(x);}
 }
 [Serializable] public sealed class FurnaceInputs {
  public double OreKgPerSecond=35,CokeKgPerSecond=16,BlastKmolPerSecond=3,OxygenMoleFraction=.21;
  public double BlastTemperatureK=1473.15,FeedTemperatureK=298.15,HearthGaugePressurePa=150000,TapOpening=0;
  public void Validate(){foreach(double x in new[]{OreKgPerSecond,CokeKgPerSecond,BlastKmolPerSecond,OxygenMoleFraction,BlastTemperatureK,FeedTemperatureK,HearthGaugePressurePa,TapOpening})if(!FurnaceConfig.Valid(x)||x<0)throw new ArgumentException("Invalid furnace input");if(OxygenMoleFraction>1||TapOpening>1||BlastTemperatureK<298.15||FeedTemperatureK<298.15)throw new ArgumentException("Input outside model domain");}
 }
 public sealed class Reaction {
  public string Name;public int[] Stoich;public double HeatJPerKmol;
  public Reaction(string name,int[] stoich){Name=name;Stoich=stoich;for(int i=0;i<8;i++)HeatJPerKmol-=stoich[i]*FurnaceModel.FormationJPerKmol[i];}
 }
 public struct PhaseState {
  public double TemperatureK,LiquidKg;
  public static PhaseState Resolve(double energy,double capacity,double ironKg,double reference,double melt,double latent){
   double threshold=capacity*(melt-reference);
   if(energy<threshold)return new PhaseState{TemperatureK=reference+energy/capacity,LiquidKg=0};
   if(energy<threshold+ironKg*latent)return new PhaseState{TemperatureK=melt,LiquidKg=(energy-threshold)/latent};
   return new PhaseState{TemperatureK=reference+(energy-ironKg*latent)/capacity,LiquidKg=ironKg};
  }
 }
 public static class Hydraulics {
  public static double Velocity(double pressure,double rho,double viscosity,double diameter,double length,double roughness,double minor){
   if(pressure<=0)return 0;double v=Math.Sqrt(2*pressure/(rho*minor));
   for(int k=0;k<24;k++){
    double re=Math.Max(1e-9,rho*v*diameter/viscosity);double friction=re<2300?64/re:1/Math.Pow(-1.8*Math.Log10(Math.Pow(roughness/diameter/3.7,1.11)+6.9/re),2);
    double next=Math.Sqrt(2*pressure/(rho*(minor+friction*length/diameter)));v=(v+next)*.5;
   }
   return v;
  }
  public static double Flow(FurnaceConfig c,double level,double opening,double gaugePressure,double temperature){
   if(opening<=0||level<=c.TapHeightM||temperature<c.MeltingTemperatureK-.001)return 0;
   double d=c.TapDiameterM*Math.Sqrt(opening),area=Math.PI*d*d/4;
   double viscosity=c.IronViscosityPas*Math.Exp(c.ViscosityActivationJmol/8.314462618*(1/temperature-1/c.ViscosityReferenceK));
   double dp=gaugePressure+c.IronDensityKgM3*9.81*(level-c.TapHeightM);
   return area*Velocity(dp,c.IronDensityKgM3,viscosity,d,c.TapLengthM,c.TapRoughnessM,c.TapMinorLoss);
  }
 }
 public sealed class RunnerFlow {
  // Saint-Venant equations; Rusanov finite-volume flux, positive donor-volume limiter,
  // exact prescribed inlet, free outflow, semi-implicit Manning bed friction.
  public readonly double[] Depth,DischargePerWidth;
  public double InletM3,OutletM3,LastOutletM3s;public readonly FurnaceConfig Config;
  readonly double dx;readonly double[] fh,fq,scale;
  public RunnerFlow(FurnaceConfig c){c.Validate();Config=c;Depth=new double[c.RunnerCells];DischargePerWidth=new double[c.RunnerCells];dx=c.RunnerLengthM/c.RunnerCells;fh=new double[c.RunnerCells+1];fq=new double[c.RunnerCells+1];scale=new double[c.RunnerCells];}
  public double VolumeM3 {get{double sum=0;foreach(double h in Depth)sum+=h;return sum*dx*Config.RunnerWidthM;}}
  public double Velocity(int i){return Depth[i]>1e-8?DischargePerWidth[i]/Depth[i]:0;}
  public void Step(double dt,double inletM3s){
   if(!FurnaceConfig.Valid(dt)||dt<0||!FurnaceConfig.Valid(inletM3s)||inletM3s<0)throw new ArgumentException("Invalid runner input");
   double remaining=dt;
   while(remaining>1e-10){double wave=.1;for(int i=0;i<Depth.Length;i++)wave=Math.Max(wave,Math.Abs(Velocity(i))+Math.Sqrt(9.81*Depth[i]));double hIn=inletM3s>0?Math.Max(.003,Math.Pow(inletM3s/Config.RunnerWidthM,2.0/3)/Math.Pow(9.81,1.0/3)):0;wave=Math.Max(wave,hIn>0?inletM3s/Config.RunnerWidthM/hIn+Math.Sqrt(9.81*hIn):0);
    double step=Math.Min(remaining,Math.Min(.05,.4*dx/wave));Substep(step,inletM3s,hIn);remaining-=step;
   }
  }
  void Substep(double dt,double inflow,double hIn){
   int n=Depth.Length;double width=Config.RunnerWidthM;
   fh[0]=inflow/width;fq[0]=hIn>0?fh[0]*fh[0]/hIn+.5*9.81*hIn*hIn:.5*9.81*Depth[0]*Depth[0];
   for(int k=1;k<n;k++){double hl=Depth[k-1],hr=Depth[k],ql=DischargePerWidth[k-1],qr=DischargePerWidth[k];double ul=Velocity(k-1),ur=Velocity(k);double a=Math.Max(Math.Abs(ul)+Math.Sqrt(9.81*hl),Math.Abs(ur)+Math.Sqrt(9.81*hr));fh[k]=.5*(ql+qr)-.5*a*(hr-hl);fq[k]=.5*(ql*ul+.5*9.81*hl*hl+qr*ur+.5*9.81*hr*hr)-.5*a*(qr-ql);}
   fh[n]=Math.Max(0,DischargePerWidth[n-1]);fq[n]=fh[n]*Math.Max(0,Velocity(n-1))+.5*9.81*Depth[n-1]*Depth[n-1];
   for(int k=0;k<n;k++){double outward=Math.Max(0,fh[k+1])+Math.Max(0,-fh[k]);scale[k]=outward>0?Math.Min(1,Depth[k]*dx/(dt*outward)):1;}
   for(int k=1;k<=n;k++){double factor=fh[k]>=0?scale[k-1]:scale[k];fh[k]*=factor;fq[k]*=factor;}
   for(int k=0;k<n;k++){double h=Depth[k]+dt/dx*(fh[k]-fh[k+1]);if(h< -1e-10)throw new InvalidOperationException("Runner positivity failure");h=Math.Max(0,h);double q=DischargePerWidth[k]+dt/dx*(fq[k]-fq[k+1])+dt*9.81*h*Config.RunnerSlope;
    if(h<1e-8)q=0;else q/=1+dt*9.81*Config.RunnerManning*Config.RunnerManning*Math.Abs(q)/Math.Pow(h,7.0/3);
    Depth[k]=h;DischargePerWidth[k]=q;
   }
   InletM3+=inflow*dt;OutletM3+=fh[n]*width*dt;LastOutletM3s=fh[n]*width;
  }
 }
 public sealed class FurnaceModel {
  // Species: hematite, solid Fe, liquid Fe, coke C, O2, CO, CO2, N2; amount in kmol.
  public static readonly double[] MolarKg={2*55.845+3*15.999,55.845,55.845,12.011,2*15.999,12.011+15.999,12.011+2*15.999,2*14.007};
  public static readonly int[,] Atoms={{2,0,3,0},{1,0,0,0},{1,0,0,0},{0,1,0,0},{0,0,2,0},{0,1,1,0},{0,1,2,0},{0,0,0,2}};
  // JANAF/NIST 298.15 K formation enthalpies; liquid latent heat handled separately.
  public static readonly double[] FormationJPerKmol={-825.5032e6,0,0,0,0,-110.53e6,-393.51e6,0};
  public static readonly Reaction[] Reactions={new Reaction("2C + O2 -> 2CO",new[]{0,0,0,-2,-1,2,0,0}),new Reaction("Fe2O3 + 3CO -> 2Fe + 3CO2",new[]{-1,2,0,0,0,-3,3,0}),new Reaction("Fe2O3 + 3C -> 2Fe + 3CO",new[]{-1,2,0,-3,0,3,0,0})};
  public readonly FurnaceConfig Config;public readonly double[] Kmol=new double[8];public readonly RunnerFlow Channel;
  public double TimeSeconds,TemperatureK,ThermalEnergyJ,ProducedIronKg,TappedKg,TapKgPerSecond,LastReactionWatts,GasOutKg,FeedKg;
  public double ReactionHeatJ,FeedHeatJ,GasHeatJ,TapHeatJ,LossHeatJ;readonly double initialMass,initialEnergy;
  public FurnaceModel(FurnaceConfig config){config.Validate();Config=config;Kmol[0]=config.InitialOreKg/MolarKg[0];Kmol[3]=config.InitialCokeKg/MolarKg[3];Kmol[2]=config.InitialIronKg/MolarKg[2];Kmol[5]=config.InitialCOKg/MolarKg[5];Kmol[6]=config.InitialCO2Kg/MolarKg[6];Kmol[7]=config.InitialNitrogenKg/MolarKg[7];Channel=new RunnerFlow(config);
   ThermalEnergyJ=Capacity*(config.InitialTemperatureK-config.ReferenceTemperatureK)+(config.InitialTemperatureK>=config.MeltingTemperatureK?config.InitialIronKg*config.LatentHeatJkg:0);ResolvePhase();initialMass=InventoryMassKg;initialEnergy=ThermalEnergyJ;
  }
  public double LiquidIronKg {get{return Kmol[2]*MolarKg[2];}}
  public double SolidIronKg {get{return Kmol[1]*MolarKg[1];}}
  public double HeadM {get{return LiquidIronKg/(Config.IronDensityKgM3*Math.PI*Config.HearthRadiusM*Config.HearthRadiusM*Config.HearthVoidFraction);}}
  public double COFraction {get{return Kmol[5]+Kmol[6]>0?Kmol[5]/(Kmol[5]+Kmol[6]):0;}}
  public double Capacity {get{double c=Config.MatrixHeatCapacityJK;for(int k=0;k<8;k++)c+=Kmol[k]*MolarKg[k]*Config.HeatCapacityJkgK[k];return c;}}
  public double InventoryMassKg {get{double m=0;for(int k=0;k<8;k++)m+=Kmol[k]*MolarKg[k];return m;}}
  public double MassResidualKg {get{return InventoryMassKg+Config.IronDensityKgM3*(Channel.VolumeM3+Channel.OutletM3)+GasOutKg-initialMass-FeedKg;}}
  public double EnergyResidualJ {get{return ThermalEnergyJ-initialEnergy-ReactionHeatJ-FeedHeatJ+GasHeatJ+TapHeatJ+LossHeatJ;}}
  void ResolvePhase(){double iron=LiquidIronKg+SolidIronKg;var phase=PhaseState.Resolve(ThermalEnergyJ,Capacity,iron,Config.ReferenceTemperatureK,Config.MeltingTemperatureK,Config.LatentHeatJkg);TemperatureK=phase.TemperatureK;Kmol[2]=phase.LiquidKg/MolarKg[2];Kmol[1]=(iron-phase.LiquidKg)/MolarKg[1];}
  void Feed(int k,double kg,double temperature){Kmol[k]+=kg/MolarKg[k];FeedKg+=kg;double heat=kg*Config.HeatCapacityJkgK[k]*(temperature-Config.ReferenceTemperatureK);ThermalEnergyJ+=heat;FeedHeatJ+=heat;}
  double Apply(Reaction r,double extent){extent=Math.Max(0,extent);for(int k=0;k<8;k++)if(r.Stoich[k]<0)extent=Math.Min(extent,Kmol[k]/-r.Stoich[k]);if(r.HeatJPerKmol<0)extent=Math.Min(extent,Math.Max(0,ThermalEnergyJ-Capacity*(500-Config.ReferenceTemperatureK))/-r.HeatJPerKmol);for(int k=0;k<8;k++)Kmol[k]+=extent*r.Stoich[k];double heat=r.HeatJPerKmol*extent;ReactionHeatJ+=heat;ThermalEnergyJ+=heat;if(r.Stoich[1]>0)ProducedIronKg+=extent*r.Stoich[1]*MolarKg[1];return heat;}
  public void Step(double dt,FurnaceInputs input){if(!FurnaceConfig.Valid(dt)||dt<0||dt>60)throw new ArgumentException("dt must be finite, 0..60 seconds");if(input==null)throw new ArgumentNullException("input");input.Validate();double remain=dt;while(remain>1e-10){double step=Math.Min(.05,remain);Substep(step,input);remain-=step;}}
  void Substep(double dt,FurnaceInputs input){
   Feed(0,input.OreKgPerSecond*dt,input.FeedTemperatureK);Feed(3,input.CokeKgPerSecond*dt,input.FeedTemperatureK);Feed(4,input.BlastKmolPerSecond*input.OxygenMoleFraction*MolarKg[4]*dt,input.BlastTemperatureK);Feed(7,input.BlastKmolPerSecond*(1-input.OxygenMoleFraction)*MolarKg[7]*dt,input.BlastTemperatureK);ResolvePhase();
   double heat=0;
   if(TemperatureK>800){heat+=Apply(Reactions[0],Math.Min(Kmol[3]/2,Kmol[4])*(1-Math.Exp(-Config.CombustionRatePerSecond*dt)));}
   if(TemperatureK>900){double k=Config.ReductionRatePerSecond*Math.Exp(Config.ReductionActivationJmol/8.314462618*(1/Config.RateReferenceK-1/TemperatureK));double drive=Math.Max(0,(COFraction-Config.MinimumCOFraction)/(1-Config.MinimumCOFraction));heat+=Apply(Reactions[1],Kmol[0]*(1-Math.Exp(-k*dt))*drive);}
   if(TemperatureK>1300){double k=Config.DirectRatePerSecond*Math.Exp(Config.DirectActivationJmol/8.314462618*(1/Config.RateReferenceK-1/TemperatureK));heat+=Apply(Reactions[2],Kmol[0]*(1-Math.Exp(-k*dt)));}
   LastReactionWatts=heat/dt;ResolvePhase();
   if(Config.VentEnabled){double fraction=1-Math.Exp(-dt/Config.GasResidenceSeconds);for(int k=4;k<8;k++){double n=Kmol[k]*fraction;double kg=n*MolarKg[k];double e=kg*Config.HeatCapacityJkgK[k]*(TemperatureK-Config.ReferenceTemperatureK);Kmol[k]-=n;GasOutKg+=kg;GasHeatJ+=e;ThermalEnergyJ-=e;}}
   double loss=Math.Min(Math.Max(0,ThermalEnergyJ),Math.Max(0,Config.HeatLossWPerK*(TemperatureK-Config.ReferenceTemperatureK)*dt));LossHeatJ+=loss;ThermalEnergyJ-=loss;ResolvePhase();
   double available=Math.Max(0,LiquidIronKg-Config.TapHeightM*Config.IronDensityKgM3*Math.PI*Config.HearthRadiusM*Config.HearthRadiusM*Config.HearthVoidFraction);
   double flow=Hydraulics.Flow(Config,HeadM,input.TapOpening,input.HearthGaugePressurePa,TemperatureK);double tapped=Math.Min(available,flow*Config.IronDensityKgM3*dt);
   TapKgPerSecond=tapped/dt;double eh=tapped*(Config.HeatCapacityJkgK[2]*(TemperatureK-Config.ReferenceTemperatureK)+Config.LatentHeatJkg);Kmol[2]-=tapped/MolarKg[2];TappedKg+=tapped;TapHeatJ+=eh;ThermalEnergyJ-=eh;ResolvePhase();Channel.Step(dt,tapped/Config.IronDensityKgM3/dt);TimeSeconds+=dt;
  }
 }
}
