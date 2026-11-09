using System.Collections.Generic;
using UnityEngine;
using UnityEngine.Rendering;

namespace MAEK {
 // Kinematic presentation only: the layout-first tour owns the sensor pose and collision checks.
 [DefaultExecutionOrder(200)]
 public sealed class MAEKVirtualDrone : MonoBehaviour {
  public const float DroneEnvelopeRadius = .24f;
  public const float EnvelopeRadius = DroneEnvelopeRadius;
  public MAEKInspectionTour tour;
  public bool chaseView = false;
  public GameObject ModelRoot { get { return modelRoot; } }
  public Camera DisplayCamera {
   get {
    return isActiveAndEnabled && tour && tour.Active && chaseView && chaseValid &&
     chaseCamera && chaseCamera.enabled ? chaseCamera : tour ? tour.tourCamera : null;
   }
  }

  const int ModelLayer = 11;
  const int EnvironmentMask = 1 << 8;
  const float ChaseRadius = .07f;
  GameObject modelRoot;
  Camera chaseCamera, maskedCamera;
  Transform gimbal;
  readonly List<Transform> rotors = new List<Transform>();
  readonly List<Material> materials = new List<Material>();
  Mesh guardMesh;
  int originalMask;
  bool chaseValid, ownsCameraFlags, priorFpvEnabled;

  public void EnsureRig() {
   if (!tour) tour = GetComponent<MAEKInspectionTour>();
   if (!tour || !tour.tourCamera) return;
   MaskSensor();
   if (modelRoot) return;
   // Deliberately unparented: a scaled builder/tour object must not enlarge the envelope.
   modelRoot = new GameObject("0.48m generic virtual drone (kinematic sphere)");
   modelRoot.hideFlags = HideFlags.DontSave;
   modelRoot.layer = ModelLayer;
   var shell = Material("Microdrone graphite", new Color(.085f,.11f,.14f));
   var metal = Material("Microdrone frame", new Color(.32f,.39f,.44f));
   var accent = Material("Microdrone safety orange", new Color(.95f,.38f,.055f));
   var lens = Material("Microdrone lens", new Color(.035f,.15f,.22f));
   var led = Material("Microdrone LED", new Color(.1f,1f,.4f), true);
   Part("Central frame", PrimitiveType.Cube, modelRoot.transform,
    Vector3.zero, new Vector3(.049f,.019f,.057f), shell);
   Part("Battery cover", PrimitiveType.Cube, modelRoot.transform,
    new Vector3(0,.013f,-.003f), new Vector3(.032f,.009f,.039f), accent);
   guardMesh = GuardMesh();
   for (int x = -1; x <= 1; x += 2) for (int z = -1; z <= 1; z += 2) {
    var center = new Vector3(x*.052f,0,z*.052f);
    var arm = Part("Frame arm", PrimitiveType.Cube, modelRoot.transform,
     center*.5f, new Vector3(.009f,.008f,center.magnitude), metal);
    arm.transform.localRotation = Quaternion.LookRotation(center);
    Part("Motor", PrimitiveType.Cylinder, modelRoot.transform,
     center + Vector3.up*.009f, new Vector3(.014f,.008f,.014f), shell);
    var guard = new GameObject("Continuous propeller guard");
    guard.hideFlags = HideFlags.DontSave;
    guard.layer = ModelLayer;
    guard.transform.SetParent(modelRoot.transform, false);
    guard.transform.localPosition = center + Vector3.up*.019f;
    guard.AddComponent<MeshFilter>().sharedMesh = guardMesh;
    ConfigureRenderer(guard.AddComponent<MeshRenderer>(), accent);
    for (int side = -1; side <= 1; side += 2)
     Part("Guard support", PrimitiveType.Cube, modelRoot.transform,
      center + new Vector3(side*.014f,.013f,0), new Vector3(.028f,.003f,.003f), metal);
    var rotor = new GameObject("Spinning propeller").transform;
    rotor.gameObject.hideFlags = HideFlags.DontSave;
    rotor.gameObject.layer = ModelLayer;
    rotor.SetParent(modelRoot.transform, false);
    rotor.localPosition = center + Vector3.up*.021f;
    rotors.Add(rotor);
    Part("Propeller blade", PrimitiveType.Cube, rotor, Vector3.zero,
     new Vector3(.052f,.0016f,.005f), metal);
    Part("Propeller hub", PrimitiveType.Cylinder, rotor, Vector3.zero,
     new Vector3(.007f,.0015f,.007f), accent);
   }
   Part("Gimbal mount", PrimitiveType.Cylinder, modelRoot.transform,
    new Vector3(0,-.016f,.022f), new Vector3(.012f,.005f,.012f), metal);
   gimbal = new GameObject("Independent sensor gimbal visual").transform;
   gimbal.gameObject.hideFlags = HideFlags.DontSave;
   gimbal.gameObject.layer = ModelLayer;
   gimbal.SetParent(modelRoot.transform, false);
   gimbal.localPosition = new Vector3(0,-.026f,.028f);
   Part("Camera housing", PrimitiveType.Cube, gimbal, Vector3.zero,
    new Vector3(.021f,.018f,.021f), shell);
   var glass = Part("Camera lens", PrimitiveType.Cylinder, gimbal,
    new Vector3(0,0,.012f), new Vector3(.013f,.002f,.013f), lens);
   glass.transform.localRotation = Quaternion.Euler(90,0,0);
   Part("Tiny status LED", PrimitiveType.Sphere, modelRoot.transform,
    new Vector3(0,.006f,-.0295f), Vector3.one*.003f, led);
   // Scale the procedural mesh inside the declared sphere, including rotor/gimbal motion.
   float visualScale=DroneEnvelopeRadius*.98f/VisualRadius();
   foreach(Transform child in modelRoot.transform){child.localPosition*=visualScale;child.localScale*=visualScale;}
   var envelope = modelRoot.AddComponent<SphereCollider>();
   envelope.radius = EnvelopeRadius;
   var body = modelRoot.AddComponent<Rigidbody>();
   body.useGravity = false;
   body.isKinematic = true;
   // This collider lives only on layer 11; the original layer-8 environment mask is untouched.
   modelRoot.SetActive(isActiveAndEnabled && tour.Active);
   Debug.Assert(VisualRadius() <= EnvelopeRadius, "Microdrone exceeds its visual envelope");
  }

  void MaskSensor() {
   var sensor = tour.tourCamera;
   if (maskedCamera != sensor) {
    if (maskedCamera) maskedCamera.cullingMask = originalMask;
    maskedCamera = sensor;
    originalMask = sensor.cullingMask;
   }
   sensor.cullingMask &= ~(1 << ModelLayer);
  }

  public void RefreshPose() {
   EnsureRig();
   if (!modelRoot || !tour || !tour.tourCamera) return;
   var sensor = tour.tourCamera;
   var heading = Vector3.ProjectOnPlane(sensor.transform.forward, Vector3.up);
   // At a vertical sensor pitch retain the last valid body yaw.
   var yaw = heading.sqrMagnitude > .000001f ?
    Quaternion.LookRotation(heading, Vector3.up) : modelRoot.transform.rotation;
   modelRoot.transform.SetPositionAndRotation(sensor.transform.position, yaw);
   modelRoot.transform.localScale = Vector3.one;
   gimbal.rotation = sensor.transform.rotation;
   modelRoot.SetActive(isActiveAndEnabled && tour.Active);
   if (!isActiveAndEnabled || !tour.Active) {
    // End already restored its own saved camera flags. Never overwrite those here.
    if (chaseCamera) chaseCamera.enabled = false;
    chaseValid = false;
    ownsCameraFlags = false;
    return;
   }
   if (!ownsCameraFlags) {
    priorFpvEnabled = sensor.enabled;
    ownsCameraFlags = true;
   }
   chaseValid = chaseView && PositionChaseCamera(sensor);
   if (chaseCamera) chaseCamera.enabled = chaseValid;
   sensor.enabled = chaseValid ? false : priorFpvEnabled;
  }

  bool PositionChaseCamera(Camera sensor) {
   var origin = sensor.transform.position;
   var offset = -modelRoot.transform.forward*.38f + Vector3.up*.16f;
   var direction = offset.normalized;
   float distance = offset.magnitude;
   if (Physics.CheckSphere(origin, ChaseRadius, EnvironmentMask,
    QueryTriggerInteraction.Ignore)) return false;
   RaycastHit hit;
   if (Physics.SphereCast(origin, ChaseRadius, direction, out hit, distance,
    EnvironmentMask, QueryTriggerInteraction.Ignore)) distance = Mathf.Min(distance, hit.distance-.015f);
   if (Physics.Raycast(origin, direction, out hit, offset.magnitude,
    EnvironmentMask, QueryTriggerInteraction.Ignore)) distance = Mathf.Min(distance, hit.distance-.015f);
   // Too near to show the complete rig: use the original FPV instead.
   if (distance < .20f) return false;
   var position = origin + direction*distance;
   if (Physics.CheckSphere(position, ChaseRadius, EnvironmentMask,
    QueryTriggerInteraction.Ignore)) return false;
   if (!chaseCamera) {
    var observer = new GameObject("Microdrone chase observer (camera cuts, not flight evidence)");
    observer.hideFlags = HideFlags.DontSave;
    observer.layer = ModelLayer;
    chaseCamera = observer.AddComponent<Camera>();
    chaseCamera.enabled = false;
   }
   chaseCamera.CopyFrom(sensor);
   chaseCamera.enabled = false;
   chaseCamera.targetTexture = null;
   chaseCamera.cullingMask = sensor.cullingMask | (1 << ModelLayer);
   chaseCamera.nearClipPlane = .025f;
   chaseCamera.fieldOfView = 60;
   chaseCamera.aspect = Mathf.Clamp(sensor.aspect, .5f, 2f);
   chaseCamera.orthographic = false;
   // At this FOV/aspect, the whole near plane fits inside the .07m camera sweep sphere.
   chaseCamera.transform.SetPositionAndRotation(position,
    Quaternion.LookRotation(origin-position, Vector3.up));
   return true;
  }

  public void ToggleView() {
   if (!isActiveAndEnabled || !tour || !tour.Active) return;
   chaseView = !chaseView;
   RefreshPose();
  }

  public float VisualRadius() {
   if (!modelRoot) return 0;
   float radius = 0;
   var root = modelRoot.transform;
   var scale = root.lossyScale;
   float maxScale = Mathf.Max(Mathf.Abs(scale.x), Mathf.Abs(scale.y), Mathf.Abs(scale.z));
   foreach (var filter in modelRoot.GetComponentsInChildren<MeshFilter>(true)) {
    if (!filter.sharedMesh) continue;
    Transform rotor = null;
    foreach (var candidate in rotors)
     if (filter.transform.IsChildOf(candidate)) { rotor = candidate; break; }
    foreach (var vertex in filter.sharedMesh.vertices) {
     var point = root.InverseTransformPoint(filter.transform.TransformPoint(vertex));
     radius = Mathf.Max(radius, root.TransformVector(point).magnitude);
     if (rotor) {
      var center = root.InverseTransformPoint(rotor.position);
      var relative = point-center;
      float radial = new Vector2(center.x,center.z).magnitude +
       new Vector2(relative.x,relative.z).magnitude;
      // Conservative maximum over a FULL propeller revolution, not just this frame.
      radius = Mathf.Max(radius, Mathf.Sqrt(radial*radial+point.y*point.y)*maxScale);
     }
    }
   }
   // The gimbal can point anywhere independently of body yaw.
   if (gimbal) {
    float center = root.InverseTransformPoint(gimbal.position).magnitude;
    foreach (var filter in gimbal.GetComponentsInChildren<MeshFilter>(true))
     foreach (var vertex in filter.sharedMesh.vertices) {
      var point = root.InverseTransformPoint(filter.transform.TransformPoint(vertex));
      var pivot = root.InverseTransformPoint(gimbal.position);
      radius = Mathf.Max(radius, (center+(point-pivot).magnitude)*maxScale);
     }
   }
   return radius;
  }

  void OnEnable() { EnsureRig(); }
  void Update() {
   if (Application.isPlaying && Input.GetKeyDown(KeyCode.V)) ToggleView();
   if (!Application.isPlaying || !tour || !tour.Active) return;
   for (int i=0; i<rotors.Count; i++)
    rotors[i].Rotate(Vector3.up, (i == 0 || i == 3 ? 1 : -1)*1800*Time.deltaTime, Space.Self);
  }
  void LateUpdate() { RefreshPose(); }
  void OnGUI() {
   if (!tour || !tour.Active) return;
   GUI.Box(new Rect(12,Screen.height-62,570,50),
    "0.24m body radius + 0.10m margin | generic kinematic sphere, not real flight\n"+
    (chaseValid ? "V: chase observer (view cuts, not continuous flight evidence)" : "V: FPV / collision-checked chase observer"));
  }
  void OnDisable() {
   if (chaseCamera) chaseCamera.enabled = false;
   if (modelRoot) modelRoot.SetActive(false);
   if (ownsCameraFlags && tour && tour.Active && tour.tourCamera)
    tour.tourCamera.enabled = priorFpvEnabled;
   ownsCameraFlags = false;
   chaseValid = false;
   chaseView = false;
   if (maskedCamera) maskedCamera.cullingMask = originalMask;
   maskedCamera = null;
  }
  void OnDestroy() {
   OnDisable();
   if (modelRoot) Release(modelRoot);
   if (chaseCamera) Release(chaseCamera.gameObject);
   foreach (var material in materials) if (material) Release(material);
   if (guardMesh) Release(guardMesh);
  }
  static void Release(Object value) {
   if (Application.isPlaying) Destroy(value); else DestroyImmediate(value);
  }
  Material Material(string label, Color color, bool unlit=false) {
   var shader = Shader.Find(unlit ? "Unlit/Color" : "Standard");
   if (!shader) shader = Shader.Find(unlit ? "Standard" : "Unlit/Color");
   if (!shader) throw new System.InvalidOperationException("Microdrone requires Standard or Unlit/Color shader");
   var material = new Material(shader) {
    name = label, color = color, hideFlags = HideFlags.DontSave
   };
   materials.Add(material);
   return material;
  }
  static void ConfigureRenderer(Renderer renderer, Material material) {
   renderer.sharedMaterial = material;
   // Excluding layer 11 must also prevent drone shadows/reflections in sensor RGB.
   renderer.shadowCastingMode = ShadowCastingMode.Off;
   renderer.receiveShadows = false;
   renderer.lightProbeUsage = LightProbeUsage.Off;
   renderer.reflectionProbeUsage = ReflectionProbeUsage.Off;
  }
  static GameObject Part(string label, PrimitiveType type, Transform parent,
   Vector3 position, Vector3 scale, Material material) {
   var part = GameObject.CreatePrimitive(type);
   part.name = label;
   part.hideFlags = HideFlags.DontSave;
   part.layer = ModelLayer;
   var collider = part.GetComponent<Collider>();
   collider.enabled = false;
   // Immediate removal avoids even a single-frame extra collider on the visual rig.
   DestroyImmediate(collider);
   part.transform.SetParent(parent, false);
   part.transform.localPosition = position;
   part.transform.localScale = scale;
   ConfigureRenderer(part.GetComponent<Renderer>(), material);
   return part;
  }
  static Mesh GuardMesh() {
   const int segments=48, sides=8;
   var vertices = new Vector3[segments*sides];
   var triangles = new int[segments*sides*6];
   for (int i=0; i<segments; i++) for (int j=0; j<sides; j++) {
    float a=i*Mathf.PI*2/segments, b=j*Mathf.PI*2/sides;
    float r=.030f+.002f*Mathf.Cos(b);
    int v=i*sides+j, next=((i+1)%segments)*sides;
    vertices[v]=new Vector3(r*Mathf.Cos(a),.002f*Mathf.Sin(b),r*Mathf.Sin(a));
    int t=v*6, k=(j+1)%sides;
    triangles[t]=v; triangles[t+1]=i*sides+k; triangles[t+2]=next+j;
    triangles[t+3]=i*sides+k; triangles[t+4]=next+k; triangles[t+5]=next+j;
   }
   var mesh = new Mesh {
    name="Microdrone 32mm outer-radius prop guard", hideFlags=HideFlags.DontSave
   };
   mesh.vertices=vertices; mesh.triangles=triangles;
   mesh.RecalculateNormals(); mesh.RecalculateBounds();
   return mesh;
  }
 }
}
