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
| `network.pipe_sizes.nps_2.od_mm` | 60.3 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_2.wall_mm` | 3.91 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_4.od_mm` | 114.3 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_4.wall_mm` | 6.02 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_8.od_mm` | 219.1 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_8.wall_mm` | 8.18 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_12.od_mm` | 323.9 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `network.pipe_sizes.nps_12.wall_mm` | 10.31 | mm | [링크](https://www.engineeringtoolbox.com/steel-pipes-dimensions-d_43.html) |
| `defects.cui.temp_min_c` | -12 | C | [링크](https://www.fabrico.io/blog/corrosion-under-insulation/) |
| `defects.cui.temp_max_c` | 175 | C | [링크](https://www.fabrico.io/blog/corrosion-under-insulation/) |
| `defects.cui.peak_min_c` | 60 | C | [링크](https://www.fabrico.io/blog/corrosion-under-insulation/) |
| `defects.cui.peak_max_c` | 120 | C | [링크](https://www.fabrico.io/blog/corrosion-under-insulation/) |
| `defects.cui.location_weight.support` | 0.35 |  | [링크](https://inspectioneering.com/blog/2014-12-08/4286/what-is-corrosion-under-insulation-cui) |
| `defects.cui.location_weight.nozzle` | 0.25 |  | [링크](https://inspectioneering.com/blog/2014-12-08/4286/what-is-corrosion-under-insulation-cui) |
| `defects.cui.location_weight.dead_leg` | 0.25 |  | [링크](https://inspectioneering.com/blog/2014-12-08/4286/what-is-corrosion-under-insulation-cui) |
| `defects.cui.location_weight.straight` | 0.15 |  | 가정 |
| `defects.fac.location_weight.elbow` | 0.4 |  | [링크](https://www.intechopen.com/chapters/39784) |
| `defects.fac.location_weight.tee` | 0.25 |  | [링크](https://www.intechopen.com/chapters/39784) |
| `defects.fac.location_weight.orifice` | 0.2 |  | [링크](https://www.intechopen.com/chapters/39784) |
| `defects.fac.location_weight.valve` | 0.15 |  | [링크](https://www.intechopen.com/chapters/39784) |
| `defects.corrosion_rate.mean_mm_per_year` | 0.15 | mm/yr | 가정 |
| `defects.corrosion_rate.sigma_log` | 0.6 |  | 가정 |
| `defects.corrosion_rate.max_mm_per_year` | 1.5 | mm/yr | 가정 |
| `defects.crack.length_mean_mm` | 8.0 | mm | 가정 |
| `defects.crack.length_sigma_log` | 0.5 |  | 가정 |
| `defects.crack.depth_frac_mean` | 0.25 |  | 가정 |
| `defects.crack.depth_frac_max` | 0.8 |  | 가정 |
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
| `ut.max_inspection_interval_yr` | 10 | yr | 가정 |
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
| `camera.image_size` | 640 | px | 가정 |
| `camera.brightness_range` | [0.5, 1.5] |  | 가정 |
| `camera.dust_opacity_range` | [0.0, 0.4] |  | 가정 |
| `camera.steam_opacity_range` | [0.0, 0.5] |  | 가정 |
| `strategy.cost_ut_point_krw` | 150000 | KRW | 가정 |
| `strategy.cost_scaffold_krw` | 2000000 | KRW | 가정 |
| `strategy.cost_drone_per_km_krw` | 500000 | KRW/km | 가정 |
| `strategy.cost_labor_hour_krw` | 50000 | KRW/h | 가정 |
| `onboard.target_fps` | 5 | fps | 가정 |
| `onboard.memory_limit_gb` | 2 | GB | 가정 |
