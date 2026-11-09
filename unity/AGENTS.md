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
- Catalogue coverage must account for all 247 pipe IDs. Keep the legacy route immutable
  as a reference, but plan only after physical site generation. Partition every required
  observation into scheduled or deferred, with a reason. Zero scheduled images must
  remain unobserved/inspection deferred; it is never a successful negative inspection.
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
- Generate the complete fixed physical site before drone routing. Never remove, move,
  shrink or omit equipment to preserve a flight path, camera sightline or photograph.
  Keep `visualization/realism/baseline` and original six inputs immutable as legacy
  evidence; write current plans separately to `site_inspection_tour.json` and
  `site_supplementary_tour.json`. Preserve physical pipe connections and reject genuine
  unrelated penetrations. Pedestrian access is a site constraint, not a drone corridor.
  A bounded search failure means no route found under configured resolution/budget,
  not proof that no possible route exists. Report that limit and defer the observation.
- Interior work must follow a saved-scene collider audit. Preserve the initial
  failures and the passing pre-interior gate in `visualization/interior_detail`.
  Use `EnhanceInteriors.Apply` for the two cast houses and three maintenance halls.
  Protect the central pedestrian access corridor and workstation approaches; use
  capsule sweeps and sample overlaps. Do not protect a prior drone route or view.
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

- Worker accident sources must identify the reported medium, process area and work.
  Do not label BFG as oxygen, boiler flue as sinter dedusting, or slurry as acid piping.
  `worker_safety_context.json` explicitly distinguishes unmodelled reported cases from
  synthetic examples. RGB candidates and zero flow never imply work permission,
  structural load capacity, no residual gas or accident prevention. Validate all 14
  service profiles and retain `workPermissionStatus=not_assessed` in follow-up evidence.


- Oxygen/sinter additions use a separate typed graph and `MAEKSupplementaryLine` tags.
  Preserve the original 247 catalogue and legacy route evidence. Require physical endpoint checks,
  directed source-to-sink reachability, all-scene collider checks and explicit per-view
  accessible/deferred classification. Shared declared ports may touch; unrelated equipment cannot penetrate.
  Oxygen reference scope ends at the consumer inlet boundary. Sinter secondary dust
  extraction is not blast-furnace flue or primary sinter process gas. Do not reuse the
  old assumed pressure/flow results as new-circuit operating conditions.
- Native Windows delivery must exercise the packaged local bridge and player through
  both original 247/771 and supplementary 17/17 captures, projected RGB evidence,
  work-permission-not-assessed follow-ups and recording. Unity build success alone
  does not prove the EXE demonstration works.

- Use the existing repository `dashboard/` for live integration. Keep stored RGB,
  thermal and locally registered NDT evidence separate from live Unity observations.
  Draw analysis boxes only on the matching hash-verified still, never the current
  moving preview. Scenario truth belongs only in evaluation, not detector inputs.
  Run `MAEK.Editor.VerifyInspectionScenarios.Run` for scenario and RGB-contract
  changes. Preserve genuine false positives; missing UT/IR must remain unmeasured.
- Configure scenarios through the Unity game view, not the web dashboard. Web UI
  changes alone may refresh an existing full evidence seal with `--seal-ui` and
  hash-bound browser QA; this must reject changed engine sources or core reports.
