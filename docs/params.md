# 파라미터 표

`python -m maek params-table --write`로 생성됨.

| 항목 | 값 | 단위 | 근거 |
|---|---|---|---|
| `network.total_km` | 100 | km | 가정 |
| `network.segment_m` | 50 | m | 가정 |
| `network.media_mix.cooling_water` | 0.25 |  | 가정 |
| `network.media_mix.steam` | 0.2 |  | 가정 |
| `network.media_mix.byproduct_gas_co` | 0.15 |  | 가정 |
| `network.media_mix.oxygen` | 0.08 |  | 가정 |
| `network.media_mix.nitrogen` | 0.1 |  | 가정 |
| `network.media_mix.pickling_acid_hf` | 0.07 |  | 가정 |
| `network.media_mix.compressed_air` | 0.15 |  | 가정 |
| `network.install_year_min` | 1975 | year | 가정 |
| `network.install_year_max` | 2020 | year | 가정 |
| `network.insulated_fraction` | 0.45 |  | 가정 |
| `network.elevated_fraction` | 0.6 |  | 가정 |
| `network.reference_year` | 2026 | year | 가정 |
| `network.insulated_prob_steam` | 0.95 |  | 가정 |
| `network.t_min_frac` | 0.5 |  | 가정 |
| `network.traffic_levels` | [0, 1, 2] |  | 가정 |
| `network.nps_weights.nps_2` | 0.3 |  | 가정 |
| `network.nps_weights.nps_4` | 0.3 |  | 가정 |
| `network.nps_weights.nps_8` | 0.25 |  | 가정 |
| `network.nps_weights.nps_12` | 0.15 |  | 가정 |
| `network.material.acid_pvc` | 0.6 |  | 가정 |
| `network.material.oxygen_stainless` | 0.3 |  | 가정 |
| `network.material.other_stainless` | 0.05 |  | 가정 |
| `network.area_by_medium.cooling_water` | ['제선', '제강', '압연', '발전'] |  | 가정 |
| `network.area_by_medium.steam` | ['발전', '압연', '제강'] |  | 가정 |
| `network.area_by_medium.byproduct_gas_co` | ['제선', '제강', '발전'] |  | 가정 |
| `network.area_by_medium.oxygen` | ['산소공장', '제강', '제선'] |  | 가정 |
| `network.area_by_medium.nitrogen` | ['산소공장', '제강', '압연'] |  | 가정 |
| `network.area_by_medium.pickling_acid_hf` | ['산세'] |  | 가정 |
| `network.area_by_medium.compressed_air` | ['제선', '제강', '압연', '산세'] |  | 가정 |
| `network.temp_c_by_medium.cooling_water` | [25, 60] | C | 가정 |
| `network.temp_c_by_medium.steam` | [100, 220] | C | 가정 |
| `network.temp_c_by_medium.byproduct_gas_co` | [30, 90] | C | 가정 |
| `network.temp_c_by_medium.oxygen` | [-10, 40] | C | 가정 |
| `network.temp_c_by_medium.nitrogen` | [-10, 40] | C | 가정 |
| `network.temp_c_by_medium.pickling_acid_hf` | [40, 85] | C | 가정 |
| `network.temp_c_by_medium.compressed_air` | [20, 60] | C | 가정 |
| `network.features_per_km.weld` | 85 | 1/km | 가정 |
| `network.features_per_km.support` | 125 | 1/km | 가정 |
| `network.features_per_km.elbow` | 15 | 1/km | 가정 |
| `network.features_per_km.tee` | 6 | 1/km | 가정 |
| `network.features_per_km.flange` | 10 | 1/km | 가정 |
| `network.features_per_km.valve_downstream` | 4 | 1/km | 가정 |
| `network.features_per_km.orifice_downstream` | 1 | 1/km | 가정 |
| `network.features_per_km.nozzle` | 3 | 1/km | 가정 |
| `network.features_per_km.dead_leg` | 0.5 | 1/km | 가정 |
| `network.pipe_sizes.nps_2.od_mm` | 60.3 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_2.wall_mm` | 3.91 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_4.od_mm` | 114.3 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_4.wall_mm` | 6.02 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_8.od_mm` | 219.1 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_8.wall_mm` | 8.18 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_12.od_mm` | 323.9 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_12.wall_mm` | 10.31 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `defects.age_ref_years` | 30 | year | 가정 |
| `defects.age_exponent` | 1.0 |  | 가정 |
| `defects.exposure_frac_range` | [0.1, 0.6] |  | 가정 |
| `defects.consequence_gain` | 0.5 |  | 가정 |
| `defects.external_corrosion.rate_per_km` | 6 | 1/km | 가정 |
| `defects.internal_pitting.rate_per_km` | 2 | 1/km | 가정 |
| `defects.internal_pitting.media` | ['cooling_water', 'steam', 'byproduct_gas_co', 'pickling_acid_hf'] |  | 가정 |
| `defects.flange_leak.p_per_flange` | 0.03 |  | 가정 |
| `defects.cui.temp_min_c` | -12 | C | [링크](https://www.fabrico.io/blog/corrosion-under-insulation/) |
| `defects.cui.temp_max_c` | 175 | C | [링크](https://www.fabrico.io/blog/corrosion-under-insulation/) |
| `defects.cui.peak_min_c` | 60 | C | [링크](https://www.fabrico.io/blog/corrosion-under-insulation/) |
| `defects.cui.peak_max_c` | 120 | C | [링크](https://www.fabrico.io/blog/corrosion-under-insulation/) |
| `defects.cui.location_weight.support` | 0.35 |  | [링크](https://inspectioneering.com/blog/2014-12-08/4286/what-is-corrosion-under-insulation-cui) |
| `defects.cui.location_weight.nozzle` | 0.25 |  | [링크](https://inspectioneering.com/blog/2014-12-08/4286/what-is-corrosion-under-insulation-cui) |
| `defects.cui.location_weight.dead_leg` | 0.25 |  | [링크](https://inspectioneering.com/blog/2014-12-08/4286/what-is-corrosion-under-insulation-cui) |
| `defects.cui.location_weight.straight` | 0.15 |  | 가정 |
| `defects.cui.rate_per_km` | 4 | 1/km | 가정 |
| `defects.cui.peak_factor` | 2.0 |  | 가정 |
| `defects.cui.external_sign_prob` | 0.4 |  | 가정 |
| `defects.fac.location_weight.elbow` | 0.4 |  | [링크](https://www.intechopen.com/chapters/39784) |
| `defects.fac.location_weight.tee` | 0.25 |  | [링크](https://www.intechopen.com/chapters/39784) |
| `defects.fac.location_weight.orifice` | 0.2 |  | [링크](https://www.intechopen.com/chapters/39784) |
| `defects.fac.location_weight.valve` | 0.15 |  | [링크](https://www.intechopen.com/chapters/39784) |
| `defects.fac.location_weight.straight` | 0.05 |  | 가정 |
| `defects.fac.rate_per_km` | 3 | 1/km | 가정 |
| `defects.fac.media` | ['cooling_water', 'steam'] |  | 가정 |
| `defects.fac.rate_factor` | 2.0 |  | 가정 |
| `defects.corrosion_rate.mean_mm_per_year` | 0.15 | mm/yr | 가정 |
| `defects.corrosion_rate.sigma_log` | 0.6 |  | 가정 |
| `defects.corrosion_rate.max_mm_per_year` | 1.5 | mm/yr | 가정 |
| `defects.crack.length_mean_mm` | 8.0 | mm | 가정 |
| `defects.crack.length_sigma_log` | 0.5 |  | 가정 |
| `defects.crack.depth_frac_mean` | 0.25 |  | 가정 |
| `defects.crack.depth_frac_max` | 0.8 |  | 가정 |
| `defects.crack.rate_per_km` | 1 | 1/km | 가정 |
| `defects.crack.critical_height_frac` | 0.4 |  | 가정 |
| `defects.crack.growth_mm_per_year` | 0.05 | mm/yr | 가정 |
| `defects.crack.location_weight.weld` | 0.6 |  | 가정 |
| `defects.crack.location_weight.elbow` | 0.3 |  | 가정 |
| `defects.crack.location_weight.straight` | 0.1 |  | 가정 |
| `risk.consequence.oxygen` | 5 |  | 가정 |
| `risk.consequence.pickling_acid_hf` | 5 |  | 가정 |
| `risk.consequence.byproduct_gas_co` | 5 |  | 가정 |
| `risk.consequence.steam` | 3 |  | 가정 |
| `risk.consequence.nitrogen` | 2 |  | 가정 |
| `risk.consequence.compressed_air` | 1 |  | 가정 |
| `risk.consequence.cooling_water` | 1 |  | 가정 |
| `ut.v_long` | 5920 | m/s | [링크](https://materialwelding.com/ultrasonic-velocity-chart/) |
| `ut.v_shear` | 3240 | m/s | [링크](https://materialwelding.com/ultrasonic-velocity-chart/) |
| `ut.temp_coeff_mps_per_c` | -0.7 | m/s/C | [링크](https://tractian.com/en/glossary/speed-of-sound) |
| `ut.probe_freq_mhz` | 5 | MHz | 가정 |
| `ut.sampling_mhz` | 100 | MHz | 가정 |
| `ut.angle_beam_angles_deg` | [45, 60, 70] | deg | 가정 |
| `ut.noise_std` | 0.02 |  | 가정 |
| `ut.grain_noise_std` | 0.01 |  | 가정 |
| `ut.n_samples` | 4096 |  | 가정 |
| `ut.interface_delay_us` | 1.0 | us | 가정 |
| `ut.pulse_sigma_us` | 0.08 | us | 가정 |
| `ut.interface_amp` | 1.5 |  | 가정 |
| `ut.backwall_amp` | 1.0 |  | 가정 |
| `ut.backwall_decay` | 0.6 |  | 가정 |
| `ut.atten_db_per_mm` | 0.02 | dB/mm | 가정 |
| `ut.temp_coeff_shear_mps_per_c` | -0.5 | m/s/C | 가정 |
| `ut.crack_amp_max` | 1.0 |  | 가정 |
| `ut.crack_h0_mm` | 1.0 | mm | 가정 |
| `ut.crack_threshold` | 0.15 |  | 가정 |
| `ut.crack_snr` | 5.0 |  | 가정 |
| `ut.clutter_amp` | 0.05 |  | 가정 |
| `ut.gate_halfwidth_us` | 0.5 | us | 가정 |
| `ut.temp_compensation` | measured |  | 가정 |
| `ut.max_inspection_interval_yr` | 10 | yr | 가정 |
| `ut.n_avg` | 16 |  | 가정 |
| `ut.prf_hz` | 100 | Hz | 가정 |
| `ut.avg_extra_time_s` | 0.15 | s | 가정 |
| `ut.pit.method` | learned |  | 가정 |
| `ut.pit.cfar_pfa` | 0.002 |  | 가정 |
| `ut.pit.cfar_k_margin` | 0.75 |  | 가정 |
| `ut.pit.dead_zone_us` | 0.4 | us | 가정 |
| `ut.pit.min_depth_mm` | 0.3 | mm | 가정 |
| `ut.pit.wall_tol_frac` | 0.1 |  | 가정 |
| `ut.pit.gate_k_margin` | 0.0 |  | 가정 |
| `ut.pit.rel_amp_min` | 0.1 |  | 가정 |
| `ut.pit.shadow_min_drop` | 0.05 |  | 가정 |
| `ut.pit.shadow_z` | 3.1 |  | 가정 |
| `ut.pit.dr_seed` | 2026 |  | 가정 |
| `ut.pit.dr_n_train` | 4000 |  | 가정 |
| `ut.pit.dr_n_calib` | 6000 |  | 가정 |
| `ut.pit.mlp_hidden` | 16 |  | 가정 |
| `ut.pit.mlp_l2` | 0.001 |  | 가정 |
| `ut.pit.mlp_iters` | 1500 |  | 가정 |
| `ut.pit.target_fa` | 0.005 |  | 가정 |
| `ut.pit.calib_strata` | 2 |  | 가정 |
| `ut.pit.dr_pit_prob` | 0.5 |  | 가정 |
| `ut.pit.dr_noise_scale_range` | [0.5, 4.0] |  | 가정 |
| `ut.pit.dr_coupling_range` | [0.2, 1.0] |  | 가정 |
| `ut.pit.dr_temp_range_c` | [-10, 220] | C | 가정 |
| `ut.pit.dr_temp_meas_error_max_c` | 20.0 | C | 가정 |
| `ut.pit.dr_n_avg_choices` | [1, 4, 16] |  | 가정 |
| `ut.dataset.wall_range_mm` | [3.0, 12.0] | mm | 가정 |
| `ut.dataset.pit_prob` | 0.3 |  | 가정 |
| `ut.dataset.pit_depth_frac_range` | [0.1, 0.6] |  | 가정 |
| `ut.dataset.pit_fraction_range` | [0.1, 0.5] |  | 가정 |
| `ut.dataset.crack_prob` | 0.3 |  | 가정 |
| `ut.dataset.crack_height_frac_range` | [0.05, 0.8] |  | 가정 |
| `ut.dataset.train_temp_range_c` | [10, 60] | C | 가정 |
| `ut.dataset.train_coupling_range` | [0.8, 1.0] |  | 가정 |
| `ut.dataset.shifted_temp_range_c` | [100, 175] | C | 가정 |
| `ut.dataset.shifted_coupling_range` | [0.3, 0.7] |  | 가정 |
| `ut.dataset.shifted_noise_scale` | 3.0 |  | 가정 |
| `ut.dataset.train_temp_meas_error_c` | 2.0 | C | 가정 |
| `ut.dataset.shifted_temp_meas_error_c` | 15.0 | C | 가정 |
| `camera.image_size` | 640 | px | 가정 |
| `camera.brightness_range` | [0.5, 1.5] |  | 가정 |
| `camera.dust_opacity_range` | [0.0, 0.4] |  | 가정 |
| `camera.steam_opacity_range` | [0.0, 0.5] |  | 가정 |
| `camera.negative_frac` | 0.4 |  | 가정 |
| `camera.pipe_width_frac_range` | [0.35, 0.7] |  | 가정 |
| `camera.tilt_deg_range` | [-15, 15] | deg | 가정 |
| `camera.blur_sigma_range` | [0.0, 2.0] | px | 가정 |
| `camera.noise_sigma_range` | [0.0, 0.04] |  | 가정 |
| `camera.view_window_pad` | 1.0 |  | 가정 |
| `camera.shifted_brightness_range` | [0.25, 0.6] |  | 가정 |
| `camera.shifted_dust_opacity_range` | [0.3, 0.7] |  | 가정 |
| `camera.shifted_steam_opacity_range` | [0.3, 0.8] |  | 가정 |
| `camera.shifted_blur_sigma_range` | [1.5, 3.5] | px | 가정 |
| `camera.shifted_noise_sigma_range` | [0.03, 0.08] |  | 가정 |
| `camera.min_defect_px` | 6 | px | 가정 |
| `strategy.cost_ut_point_krw` | 150000 | KRW | 가정 |
| `strategy.cost_scaffold_krw` | 2000000 | KRW | 가정 |
| `strategy.cost_drone_per_km_krw` | 500000 | KRW/km | 가정 |
| `strategy.cost_labor_hour_krw` | 50000 | KRW/h | 가정 |
| `strategy.cost_drone_contact_ut_extra_krw` | 100000 | KRW | 가정 |
| `strategy.elevated_ut_mode` | drone |  | 가정 |
| `strategy.cml_per_segment` | 2 |  | 가정 |
| `strategy.probe_footprint_m` | 0.3 | m | 가정 |
| `strategy.walk_km_per_h` | 1.0 | km/h | 가정 |
| `strategy.drone_km_per_h` | 5.0 | km/h | 가정 |
| `strategy.ut_hours_per_point` | 0.5 | h | 가정 |
| `strategy.scaffold_hours` | 8 | h | 가정 |
| `strategy.camera_false_flag_prob` | 0.03 |  | 가정 |
| `strategy.high_consequence_min` | 4 |  | 가정 |
| `strategy.risk_ut_consequence_min` | 4 |  | 가정 |
| `strategy.weld_sample_frac` | 0.05 |  | 가정 |
| `strategy.crack_ut_mode` | risk_ranked |  | 가정 |
| `strategy.crack_ut_budget_frac` | 0.3 |  | 가정 |
| `strategy.support_sample_frac` | 0.05 |  | 가정 |
| `strategy.human_elevated_factor` | 0.4 |  | 가정 |
| `strategy.pod.human.b0` | -2.0 |  | 가정 |
| `strategy.pod.human.b1` | 1.2 |  | 가정 |
| `strategy.pod.camera.b0` | -1.0 |  | 가정 |
| `strategy.pod.camera.b1` | 1.2 |  | 가정 |
| `strategy.pod.ut_straight.b0` | 0.5 |  | 가정 |
| `strategy.pod.ut_straight.b1` | 2.5 |  | 가정 |
| `strategy.pod.ut_angle.b0` | 0.0 |  | 가정 |
| `strategy.pod.ut_angle.b1` | 2.5 |  | 가정 |
| `onboard.target_fps` | 5 | fps | 가정 |
| `onboard.memory_limit_gb` | 2 | GB | 가정 |
| `onboard.bench_image_sizes` | [640, 320] | px | 가정 |
| `onboard.bench_threads` | [1, 2, 3, 4] |  | 가정 |
| `onboard.bench_n_images` | 12 |  | 가정 |
| `onboard.bench_n_ut` | 60 |  | 가정 |
| `eval.n_camera` | 300 |  | 가정 |
| `eval.n_ut` | 3000 |  | 가정 |
| `eval.camera_image_size` | 640 | px | 가정 |
| `eval.seg_hue_range_deg` | [5, 40] | deg | 가정 |
| `eval.seg_sat_min` | 0.35 |  | 가정 |
| `eval.seg_val_min` | 0.12 |  | 가정 |
| `eval.seg_min_pred_px` | 30 | px | 가정 |
| `eval.seg_hit_recall` | 0.3 |  | 가정 |
| `eval.thickness_tol_mm` | [0.1, 0.5] | mm | 가정 |
| `eval.n_ut_factor` | 1000 |  | 가정 |
| `eval.pit_narrow_dr` | {'dr_noise_scale_range': [0.5, 2.0], 'dr_coupling_range': [0.5, 1.0], 'dr_temp_range_c': [-10, 80], 'dr_temp_meas_error_max_c': 5.0} |  | 가정 |
| `eval.n_pit_dr_val` | 2000 |  | 가정 |
| `eval.pod_bootstrap` | 300 |  | 가정 |
