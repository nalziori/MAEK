// Pitting 1D-CNN (cnn_dr) exported to ONNX, run in the browser with onnxruntime-web (WASM).
import * as ort from "../vendor/ort.wasm.min.mjs";

ort.env.wasm.wasmPaths = new URL("../vendor/", import.meta.url).href;
ort.env.wasm.numThreads = 1; // GitHub Pages has no cross-origin isolation

let session;
export const loadCnn = () => (session ||= ort.InferenceSession.create(new URL("data/pitting_cnn.onnx", location.href).href));

export async function inferPitting(ascan) {
  const s = await loadCnn();
  const x = Float32Array.from(ascan.rf, (v) => (v - ascan.rf_mean) / ascan.rf_std);
  const t0 = performance.now();
  const out = await s.run({ rf: new ort.Tensor("float32", x, [1, 1, x.length]) });
  const logit = out.logit.data[0];
  return { logit, probability: 1 / (1 + Math.exp(-logit)), pitting: logit > ascan.threshold_logit, ms: performance.now() - t0 };
}
