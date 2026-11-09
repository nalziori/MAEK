using System;
using System.Collections.Generic;

namespace MAEK {
 // Software scenario gate only; these inputs are not measured plant signals.
 public sealed class SafetyInputs {
  public static readonly string[] Names = { "gas_alarm", "oxygen_alarm", "pressure_alarm", "permit_valid",
   "process_release_confirmed", "equipment_suitable", "exclusion_clear", "comms_ok", "signals_fresh", "emergency_plan_ready" };
  public bool?[] Values = new bool?[10];
  public static SafetyInputs Normal() {
   var input = new SafetyInputs();
   for (int i=0;i<10;i++) input.Values[i]=i>=3;
   return input;
  }
 }
 public sealed class SafetyDecision {
  public bool Allowed;
  public string Action;
  public string[] Reasons;
 }
 public sealed class SafetyGate {
  public bool Latched {get; private set;}
  public SafetyDecision Evaluate(SafetyInputs input, bool? airborne, bool manualReset=false) {
   var reasons=new List<string>();
   for(int i=0;i<10;i++)
    if(input==null || input.Values==null || input.Values.Length!=10 || input.Values[i]!=(bool?)(i>=3)) reasons.Add(SafetyInputs.Names[i]);
   if(!airborne.HasValue) reasons.Add("flight_status_unknown");
   if(reasons.Count>0) Latched=true;
   else if(manualReset && airborne==false) Latched=false;
   if(Latched && reasons.Count==0) reasons.Add("manual_ground_reset_required");
   bool allowed=reasons.Count==0;
   return new SafetyDecision { Allowed=allowed, Reasons=reasons.ToArray(), Action=allowed?"ALLOW_SIMULATED_INSPECTION":
    airborne==false?"BLOCK_START":"STOP_INSPECTION_REQUEST_SITE_ERP" };
  }
 }
}
