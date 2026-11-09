using System.Linq;
namespace MAEK {
 // Demonstration policy, not an approved plant emergency procedure.
 public enum SafetyResponse { None, HoldUnknown, GasDiversion, PressureDiversion, PersonnelDiversion, LostLinkReturn, PermitReturn }
 public static class MAEKSafetyResponse {
  public static SafetyResponse Select(SafetyInputs input) {
   if(input==null || input.Values==null || input.Values.Length!=10 || input.Values.Any(v=>!v.HasValue) || input.Values[8]!=true)
    return SafetyResponse.HoldUnknown;
   if(input.Values[0]==true || input.Values[1]==true)return SafetyResponse.GasDiversion;
   if(input.Values[2]==true)return SafetyResponse.PressureDiversion;
   if(input.Values[6]==false)return SafetyResponse.PersonnelDiversion;
   if(input.Values[7]==false)return SafetyResponse.LostLinkReturn;
   if(input.Values.Skip(3).Any(v=>v!=true))return SafetyResponse.PermitReturn;
   return SafetyResponse.None;
  }
 }
}
