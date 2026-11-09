# MAEK inspection simulator harness

Scope: this Unity project and its inspection-demo integration with `maek/`.

- Read `../RULES.md` and `../docs/inspection-demo.md` before changing the demo.
- `MAEKInspectionDemo.unity` is the continuous RGB demonstration entry point.
  Preserve the earlier hydraulic/CFD scenes. Generated scenes are rebuilt through
  `MAEK.Editor.BuildInspectionTour.Run`, not hand-edited YAML.
- Run `../scripts/run_inspection_harness.ps1` after route, camera, collider,
  inference contract, or evidence-mapping changes. A saved scene and a screenshot
  alone do not prove that the integrated demonstration works.
- Every transit segment must pass swept-sphere collision checks. Camera cuts
  cannot be described as continuous flight. Unexpected obstacles must stop motion.
- Catalogue coverage must match all 247 distinct pipe IDs, not just a count. Retain
  every original per-pipe waypoint (forward or reversed), with explicit transfer
  spans and unique capture sample IDs. Validate planned vs captured vs analysed IDs.
- Require visible target-pipe surface evidence at every capture. Port endpoints may
  be occluded by equipment; add collision-checked viewpoints, never treat occlusion
  or an empty response as a completed healthy-pipe inspection.
- Run full-network Play-mode verification as well as the deterministic editor run.
  Fast verification may repeat small physics steps per frame but must not skip
  movement segments, planned photographs, HTTP analysis, or surface projection.
- Capture unannotated RGB. Run `maek.camera.segment.segment_rust` on those pixels.
  Never feed synthetic defect labels or expected answers to the detector.
- Match request ID, PNG SHA-256 and dimensions before applying results. Map using
  the capture pose, and accept only the first visible hit on the requested pipe.
- Missing server, timeout, malformed response and no detection are different
  states. None means that a pipe is safe. Preserve negative inspection routes.
- Use the labels “synthetic scene” and “RGB rust baseline”; never rename the
  output to crack probability, remaining life, or future fracture prediction.
- Record PNG frames plus per-frame evidence metadata. Verify an encoded video
  decodes and includes result labels before claiming video delivery.
- Do not mark prior evidence current after source changes. Run the harness and
  refresh its source hash seal. Keep failures in `../docs/failures/inspection-demo.md`.
- Visual enrichment runs through `EnhanceSteelworks.Apply` after the original route
  is computed. Keep `visualization/realism/baseline` immutable. Hash-check original
  geometry, process sources and exact final route; never reroute to fit decoration.
  Added physical assets need layer-8 colliders. Reject additions that obstruct a
  preserved flight segment, capture sightline or original process pipe. Reject an
  auxiliary pipe assembly as a whole so filtering cannot leave disconnected elbows.
  Auxiliary visual loops must not become new process IDs or hydraulic claims.
- Interior work must follow a saved-scene collider audit. Preserve the initial
  failures and the passing pre-interior gate in `visualization/interior_detail`.
  Use `EnhanceInteriors.Apply` for the two cast houses and three maintenance halls.
  Protect the central access corridor, workstation approaches and original flight
  route; use capsule sweeps as well as sample overlaps for pedestrian access.
  New training spools are closed visual fixtures, not new MAEK process IDs.
  Validate every spool joint and accept workstations only as complete assemblies.
  Only planar floor paint and printed faces may use `MAEKSurfaceMarking` without a
  collider; the supporting floor, panel or instrument retains its collider.
  Printed labels must depth-test against walls. Inspect the saved interior renders
  for lighting, text visibility and suspended-fixture attachment before delivery.
- Do not erase Blender camera animation when rebuilding CFD. The current Unity
  demo has an independent tested route; the old Blender file remains a static
  camera deliverable until its camera tracks are separately restored and tested.

- Keep `Source/process_context.json` aligned with the 14 services and all 247 pipe IDs.
  Preserve the distinction between 138 primary inspection candidates, 98 process-context
  pipes, four training-loop pipes and seven standalone utility pipes. A role is a demo
  editing choice, not a validated risk rank. New real process circuits require explicit
  source/sink topology and fresh hydraulic/collision evidence; a descriptive label is
  not proof of a physical connection.
- Preserve `follow_up.json` provenance: every row must match the planned capture count,
  observed request IDs and candidate/occlusion state. Partial or occluded capture sets
  stay incomplete even if another image has a candidate. Keep assumed pressure/flow
  conditions and out-of-scope nitrogen sealing, oxygen and PCI circuits visible in
  the process guide and recording metadata.
