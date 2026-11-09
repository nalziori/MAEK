using UnityEngine;
namespace MAEK {
 [RequireComponent(typeof(CharacterController))]
 public sealed class MAEKWalkthrough : MonoBehaviour {
  public Camera viewCamera;
  public float speed=4f, mouseSensitivity=2f;
  CharacterController controller; float pitch,vertical;
  void Awake(){controller=GetComponent<CharacterController>();}
  void Update(){
   if(Input.GetKeyDown(KeyCode.Escape))Cursor.lockState=CursorLockMode.None;
   if(Input.GetMouseButtonDown(0)){var panel=FindFirstObjectByType<MAEKPipeServices>();if(!panel||!panel.PointerOverPanel(Input.mousePosition))Cursor.lockState=CursorLockMode.Locked;}
   if(Cursor.lockState==CursorLockMode.Locked){
    transform.Rotate(0,Input.GetAxis("Mouse X")*mouseSensitivity,0);
    pitch=Mathf.Clamp(pitch-Input.GetAxis("Mouse Y")*mouseSensitivity,-80,80);
    viewCamera.transform.localRotation=Quaternion.Euler(pitch,0,0);
   }
   Vector3 axis=new Vector3((Input.GetKey(KeyCode.D)?1:0)-(Input.GetKey(KeyCode.A)?1:0),0,(Input.GetKey(KeyCode.W)?1:0)-(Input.GetKey(KeyCode.S)?1:0));
   Vector3 move=transform.TransformDirection(Vector3.ClampMagnitude(axis,1))*speed;
   if(controller.isGrounded && vertical<0)vertical=-2;
   vertical+=Physics.gravity.y*Time.deltaTime;
   controller.Move((move+Vector3.up*vertical)*Time.deltaTime);
  }
  void OnGUI(){
   GUI.Box(new Rect(12,12,540,48),"MAEK inspection environment\nWASD: walk  |  Click: mouse look  |  Esc: release mouse");
  }
 }
}
