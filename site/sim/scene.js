// three.js scene: BF1 gas-cleaning area from the MAEK virtual steelworks, drone path, RGB + thermal views.
import * as THREE from "../vendor/three.module.min.js";

// Pipe routes (three.js metres): x = unity.x + 80, y = unity.y, z = 34 - unity.z  (collision_network.json)
const G003 = [[18, 49, 20], [4, 49, 20], [0, 29, 0], [0, 24, 0]].map((p) => new THREE.Vector3(...p));
const G004 = [new THREE.Vector3(-3.2, 18, 0), new THREE.Vector3(-8, 18, 0)];
const G005x = -26;
const ROUTE_PIPES = { "BF1-G003": 1, "BF1-G004": 1, "BF1-G005": 1 };
const IR_WIDTH = 320; // render the thermal view at a thermal-camera resolution, upscaled by CSS
const V = (x, y, z) => new THREE.Vector3(x, y, z);
const lerp = THREE.MathUtils.lerp, smooth = (a, b, x) => THREE.MathUtils.smoothstep(x, a, b);

// Drone pose as a pure function of time (seconds, 0..120)
export function dronePose(t) {
  if (t < 20) { // spiral down along the G003 downcomer slope
    const s = smooth(0, 20, t) * 0.95 + 0.0;
    const c = G003[1].clone().lerp(G003[2], s);
    const th = 0.6 + s * Math.PI * 2.2;
    return { pos: c.clone().add(V(Math.cos(th) * 9, 3.5 - s * 1.5, Math.sin(th) * 9)), look: c };
  }
  if (t < 40) { // spiral around the dust catcher, passing the G004 outlet
    const s = (t - 20) / 20;
    const y = lerp(27, 17, smooth(0, 1, s));
    const th = 0.6 + Math.PI * 2.2 + s * Math.PI * 1.55;
    return { pos: V(Math.cos(th) * 13, y + 1.5, Math.sin(th) * 13), look: V(0, y, 0) };
  }
  const hover = V(G005x + 3.2, 13, 0.2), target = V(G005x, 13, 0);
  if (t < 55) { // transit then spiral down the G005 riser
    const s = smooth(40, 55, t);
    const th = Math.PI * 0.5 * (1 - s);
    const orbit = V(G005x + Math.cos(th) * 3.2, lerp(23, 13, s), Math.sin(th) * 6);
    const from = dronePose(39.999).pos;
    const k = smooth(40, 46, t);
    return { pos: from.clone().lerp(orbit, k), look: V(lerp(-6, G005x, k), lerp(17, 13, s), 0) };
  }
  if (t < 100) return { pos: hover.clone().add(V(0, Math.sin(t * 1.3) * 0.03, 0)), look: target };
  const s = smooth(100, 118, t); // descend and land
  return { pos: V(lerp(hover.x, -18, s), lerp(13, 0.6, s), lerp(0.2, 7, s)), look: V(-18 - 6 * (1 - s), lerp(13, 0.2, s), -4 * s) };
}

// Inferno palette (Matt Zucker polynomial fit) for the thermal camera
const INFERNO = `vec3 inferno(float t){t=clamp(t,0.,1.);
 const vec3 c0=vec3(0.0002189403691192265,0.001651004631001012,-0.01948089843709184);
 const vec3 c1=vec3(0.1065134194856116,0.5639564367884091,3.932712388889277);
 const vec3 c2=vec3(11.60249308247187,-3.972853965665698,-15.9423941062914);
 const vec3 c3=vec3(-41.70399613139459,17.43639888205313,44.35414519872813);
 const vec3 c4=vec3(77.162935699427,-33.40235894210092,-81.80730925738993);
 const vec3 c5=vec3(-71.31942824499214,32.62606426397723,73.20951985803202);
 const vec3 c6=vec3(25.13112622477341,-12.24266895238567,-23.07032500287172);
 return c0+t*(c1+t*(c2+t*(c3+t*(c4+t*(c5+t*c6)))));}`;
const irMaterial = (temp) => new THREE.ShaderMaterial({
  uniforms: { temp: { value: temp } },
  vertexShader: `varying vec3 vN; varying vec3 vW; void main(){ vec4 w=modelMatrix*vec4(position,1.); vW=w.xyz; vN=normalize(mat3(modelMatrix)*normal); gl_Position=projectionMatrix*viewMatrix*w; }`,
  fragmentShader: `uniform float temp; varying vec3 vN; varying vec3 vW; ${INFERNO}
    float h(vec3 p){return fract(sin(dot(floor(p*12.),vec3(12.9898,78.233,37.719)))*43758.5453);}
    void main(){ float shade=0.88+0.12*abs(vN.y); float n=(h(vW)-.5)*.02; gl_FragColor=vec4(inferno(temp*shade+n),1.); }`,
});

function rustTexture() {
  const c = document.createElement("canvas"); c.width = c.height = 256;
  const g = c.getContext("2d");
  const grad = g.createRadialGradient(128, 128, 10, 128, 128, 126);
  grad.addColorStop(0, "rgba(120,52,22,1)"); grad.addColorStop(0.6, "rgba(150,72,30,.95)"); grad.addColorStop(1, "rgba(150,72,30,0)");
  g.fillStyle = grad; g.fillRect(0, 0, 256, 256);
  for (let i = 0; i < 900; i++) { // pitted, flaky texture
    const r = Math.random() * 3 + 1, a = Math.random() * Math.PI * 2, d = Math.random() ** 0.7 * 110;
    g.fillStyle = `rgba(${70 + Math.random() * 90},${30 + Math.random() * 40},${10 + Math.random() * 20},${0.35 + Math.random() * 0.5})`;
    g.beginPath(); g.arc(128 + Math.cos(a) * d, 128 + Math.sin(a) * d, r, 0, 7); g.fill();
  }
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace; return tex;
}

// Place a patch on a pipe surface facing where the drone is at time t
function facing(t, centre, axis, radius) {
  const cam = dronePose(t).pos.clone().sub(centre);
  const out = cam.sub(axis.clone().multiplyScalar(cam.dot(axis))).normalize();
  return { pos: centre.clone().addScaledVector(out, radius + 0.03), normal: out };
}

export async function createScene(rgbCanvas, irCanvas, onProgress) {
  const [meta, buf] = await Promise.all([
    fetch("data/bf1.json").then((r) => r.json()),
    fetch("data/bf1.bin").then(async (r) => {
      const total = +r.headers.get("content-length") || 5.3e6, reader = r.body.getReader(), parts = [];
      let got = 0;
      for (;;) { const { done, value } = await reader.read(); if (done) break; parts.push(value); got += value.length; onProgress?.(got / total); }
      const out = new Uint8Array(got); let o = 0; for (const p of parts) { out.set(p, o); o += p.length; }
      return out.buffer;
    }),
  ]);
  const scene = new THREE.Scene();
  const root = new THREE.Group(); root.scale.setScalar(0.01); root.position.y = meta.origin_unity[1]; scene.add(root);
  const all = new Int16Array(buf);
  const rgbMats = meta.materials.map((m) => new THREE.MeshStandardMaterial({
    color: new THREE.Color().setRGB(...m.color, THREE.SRGBColorSpace), metalness: Math.min(m.metallic, 0.6), roughness: 0.7 }));
  const pipeTemp = { "BF1-G001": 0.62, "BF1-G002": 0.62, "BF1-G003": 0.58, "BF1-G004": 0.5, "BF1-G005": 0.46, "BF1-G006": 0.4,
    "BF1.DC": 0.52, "BF1.SC": 0.42, "BF1.BF": 0.7, "BF1.TOWER": 0.5, "BF1.TRT": 0.45 };
  // Merge into one draw call per (material, temperature); inspected pipes stay separate for the red highlight.
  const meshes = [], flagged = {}, groups = new Map();
  for (const m of meta.meshes) {
    const own = m.id in ROUTE_PIPES;
    const key = own ? m.id + "|" + m.material : m.material + "|" + (pipeTemp[m.id] ?? 0.28);
    if (!groups.has(key)) groups.set(key, { id: own ? m.id : null, material: m.material, temp: pipeTemp[m.id] ?? 0.28, parts: [], n: 0 });
    const g = groups.get(key); g.parts.push(all.subarray(m.start * 3, (m.start + m.count) * 3)); g.n += m.count * 3;
  }
  for (const g of groups.values()) {
    const arr = new Int16Array(g.n); let o = 0;
    for (const p of g.parts) { arr.set(p, o); o += p.length; }
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(arr, 3));
    geo.computeVertexNormals();
    const rgb = rgbMats[g.material].clone();
    const mesh = new THREE.Mesh(geo, rgb);
    mesh.userData = { rgb, ir: irMaterial(g.temp) };
    root.add(mesh); meshes.push(mesh);
    if (g.id) (flagged[g.id] ||= []).push(mesh);
  }
  const ground = new THREE.Mesh(new THREE.CircleGeometry(160, 48).rotateX(-Math.PI / 2),
    new THREE.MeshStandardMaterial({ color: 0x6e726f, roughness: 1 }));
  ground.userData = { rgb: ground.material, ir: irMaterial(0.22) };
  scene.add(ground); meshes.push(ground);
  scene.add(new THREE.HemisphereLight(0xdfe8ef, 0x4a4a44, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 2.2); sun.position.set(40, 80, 30); scene.add(sun);

  // Defects: corrosion patch on G003, hot leak on G004, pitting spot on G005
  const axis3 = G003[2].clone().sub(G003[1]).normalize();
  const c3 = G003[1].clone().lerp(G003[2], 0.66);
  const f3 = facing(14, c3, axis3, 1.35);
  const rust = new THREE.Mesh(new THREE.CircleGeometry(0.9, 32), new THREE.MeshStandardMaterial({ map: rustTexture(), transparent: true, roughness: 1 }));
  rust.position.copy(f3.pos); rust.lookAt(f3.pos.clone().add(f3.normal));
  rust.userData = { rgb: rust.material, ir: irMaterial(0.6) }; scene.add(rust); meshes.push(rust);

  const c4 = V(-5.6, 18, 0), f4 = facing(32, c4, V(1, 0, 0), 1.0);
  const leak = new THREE.Mesh(new THREE.SphereGeometry(0.45, 24, 16), new THREE.MeshStandardMaterial({ color: 0x6d6a62, roughness: 1 }));
  leak.position.copy(f4.pos); leak.scale.set(1, 1.6, 1);
  leak.userData = { rgb: leak.material, ir: irMaterial(1.0) }; scene.add(leak); meshes.push(leak);
  const plume = new THREE.Mesh(new THREE.ConeGeometry(0.9, 3.2, 24, 1, true), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.0, depthWrite: false }));
  plume.position.copy(f4.pos).add(V(0, 1.6, 0)); plume.rotation.x = Math.PI;
  plume.userData = { rgb: plume.material, ir: Object.assign(irMaterial(0.9), { transparent: true, opacity: 0.8 }) }; scene.add(plume); meshes.push(plume);

  // Robot arm attached to the FPV camera (visible during the UT phase)
  const cam = new THREE.PerspectiveCamera(62, 1, 0.1, 600);
  scene.add(cam);
  const arm = new THREE.Group();
  const steel = new THREE.MeshStandardMaterial({ color: 0xd8dde2, metalness: 0.6, roughness: 0.35 });
  const orange = new THREE.MeshStandardMaterial({ color: 0xf26b1d, roughness: 0.5 });
  const seg1 = new THREE.Mesh(new THREE.CylinderGeometry(0.06, 0.07, 1, 16).translate(0, 0.5, 0), steel);
  const joint = new THREE.Mesh(new THREE.SphereGeometry(0.1, 16, 12), orange);
  const seg2 = new THREE.Mesh(new THREE.CylinderGeometry(0.05, 0.06, 1, 16).translate(0, 0.5, 0), steel);
  const probe = new THREE.Mesh(new THREE.CylinderGeometry(0.12, 0.12, 0.12, 20).rotateX(Math.PI / 2), orange);
  arm.add(seg1, joint, seg2, probe);
  for (const m of [seg1, joint, seg2, probe]) m.userData = { rgb: m.material, ir: irMaterial(0.35) };
  meshes.push(seg1, joint, seg2, probe);
  cam.add(arm); arm.position.set(0.15, -0.55, -0.3);

  const rgbR = new THREE.WebGLRenderer({ canvas: rgbCanvas, antialias: true });
  const irR = new THREE.WebGLRenderer({ canvas: irCanvas, antialias: false });
  rgbR.setPixelRatio(1); // ponytail: fixed 1x; raise only if a faster GPU is guaranteed
  const sky = new THREE.Color(0xc9d6df), irSky = new THREE.Color(0x07030f);
  scene.fog = new THREE.Fog(sky, 60, 260);

  function setSize(r, c, maxW = Infinity) {
    const w = c.clientWidth, h = c.clientHeight, k = Math.min(1, maxW / Math.max(w, 1));
    const pw = Math.round(w * k), ph = Math.round(h * k);
    if (pw && ph && (c.width !== pw || c.height !== ph)) r.setSize(pw, ph, false);
    return w / Math.max(h, 1);
  }

  function render(t, state) {
    const p = dronePose(t);
    cam.position.copy(p.pos); cam.lookAt(p.look);
    // arm: folded until 55 s, extends 55-60, holds, retracts 92-97
    const ext = smooth(55, 60, t) * (1 - smooth(92, 97, t));
    arm.visible = ext > 0.01;
    const reach = 0.6 + ext * 1.9;
    seg1.scale.y = reach * 0.55; seg1.rotation.x = -Math.PI / 2 + 0.35 * (1 - ext);
    const tip1 = V(0, reach * 0.55, 0).applyEuler(seg1.rotation);
    joint.position.copy(tip1); seg2.position.copy(tip1); seg2.scale.y = reach * 0.5;
    seg2.rotation.x = -Math.PI / 2 - 0.25 * (1 - ext);
    probe.position.copy(tip1.clone().add(V(0, reach * 0.5, 0).applyEuler(seg2.rotation)));
    // steam plume visible in RGB only faintly, strongly in IR
    plume.material.opacity = 0.18; plume.userData.ir.opacity = 0.75;
    // red highlight on flagged pipes
    for (const [id, list] of Object.entries(flagged)) {
      const on = state.alerts.has(id);
      for (const m of list) m.userData.rgb.emissive?.setHex(on ? 0x4a0606 : 0x000000);
    }
    cam.aspect = setSize(rgbR, rgbCanvas); cam.updateProjectionMatrix();
    scene.background = sky; scene.fog.color = sky;
    for (const m of meshes) m.material = m.userData.rgb;
    rgbR.render(scene, cam);
    cam.aspect = setSize(irR, irCanvas, IR_WIDTH); cam.updateProjectionMatrix();
    scene.background = irSky; scene.fog.color = irSky;
    for (const m of meshes) m.material = m.userData.ir;
    irR.render(scene, cam);
  }
  return { render };
}
