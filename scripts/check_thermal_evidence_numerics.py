"""Independent 7.5--14 um numerical evidence; optional bounded official PDF snapshots.

No data generation, learning, model inference or field-accuracy claims. The
reference integrates B_nu over frequency with Gauss-Legendre quadrature, whereas
the implementation under examination uses B_lambda trapezoidal quadrature.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maek.thermal_radiometry import (
    BandRadiometry,
    gaussian_psf_radiance,
    planck_band_radiance,
)

BAND_UM = (7.5, 14.)
CASES_C = (-30., 0., 25., 80., 150.)
SEED = 20261108
SOURCES = (
    ("nist-planck-optical-metrology.pdf",
     "https://www.nist.gov/system/files/documents/iaao/SIM-Metrology-School-Optical-Metrology-Y-Ohno-2.pdf"),
    ("NIST.IR.8098.pdf", "https://nvlpubs.nist.gov/nistpubs/ir/2016/NIST.IR.8098.pdf"),
    ("NASA-20040086056.pdf", "https://ntrs.nasa.gov/api/citations/20040086056/downloads/20040086056.pdf"),
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def frequency_reference(temperatures_c, nodes=256):
    """Independent SI B_nu integral in Hz; no radiometry implementation calls.

    Uses exact SI h,c,k from NIST SP330 Section 2. Values are repeated explicitly
    instead of importing implementation constants. Output is W/(m2 sr).
    """
    h, c, k = 6.62607015e-34, 299792458., 1.380649e-23
    points, weights = np.polynomial.legendre.leggauss(nodes)
    minimum, maximum = c / (BAND_UM[1] * 1e-6), c / (BAND_UM[0] * 1e-6)
    frequency = (minimum + maximum) / 2 + points * (maximum - minimum) / 2
    temperature_k = np.asarray(temperatures_c, dtype=np.float64)[..., None] + 273.15
    spectral = (2 * h / c ** 2) * frequency ** 3 / np.expm1(h * frequency / (k * temperature_k))
    return np.sum(spectral * weights, axis=-1) * (maximum - minimum) / 2


def temperature_blur_for_comparison(temperature, sigma, truncate):
    """Old temperature-domain averaging with the same Gaussian kernel/boundaries."""
    radius = max(1, math.ceil(sigma * truncate))
    positions = np.arange(-radius, radius + 1, dtype=np.float64)
    kernel = np.exp(-.5 * (positions / sigma) ** 2)
    kernel /= kernel.sum()
    result = temperature.copy()
    for axis in (0, 1):
        padding = [(0, 0), (0, 0)]
        padding[axis] = (radius, radius)
        result = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="valid"),
                                     axis, np.pad(result, padding, mode="edge"))
    return result


def check_numerics():
    cases = np.array(CASES_C)
    probes = np.random.default_rng(SEED).uniform(min(CASES_C), max(CASES_C), 64)
    temperatures = np.concatenate((cases, probes))
    reference = frequency_reference(temperatures, 256)
    reference_half = frequency_reference(temperatures, 128)
    reference_difference = float(np.max(np.abs(reference - reference_half) / reference))
    quadrature = []
    for samples in (65, 129, 257, 513, 1025):
        computed = planck_band_radiance(temperatures, BAND_UM, samples)
        errors = np.abs(computed - reference) / reference
        quadrature.append({"wavelength_samples": samples,
                           "max_relative_error_69_probes": float(errors.max()),
                           "five_cases": [{"temperature_c": float(t), "reference_radiance_w_m2_sr": float(r),
                                           "computed_radiance_w_m2_sr": float(v), "relative_error": float(e)}
                                          for t, r, v, e in zip(cases, reference[:5], computed[:5], errors[:5])]})
    direct_default = planck_band_radiance(temperatures, BAND_UM, 257)
    lookup = []
    for samples in (257, 1025, 4097, 8193, 16385):
        camera = BandRadiometry(band_um=BAND_UM, wavelength_samples=257, temperature_samples=samples)
        forward = camera.radiance(temperatures)
        inverted = camera.temperature(reference)  # Independent radiance, not self-roundtrip.
        lookup.append({"temperature_samples": samples, "wavelength_samples": 257,
                       "temperature_grid_step_c": 680 / (samples - 1),
                       "max_forward_relative_error_69_probes": float(np.max(np.abs(forward - reference) / reference)),
                       "max_interpolation_only_relative_error": float(np.max(np.abs(forward - direct_default) / direct_default)),
                       "max_inverse_absolute_error_c_69_probes": float(np.max(np.abs(inverted - temperatures))),
                       "five_cases": [{"temperature_c": float(t), "inverted_reference_c": float(v),
                                       "inverse_absolute_error_c": float(abs(v - t))} for t, v in zip(cases, inverted[:5])]})
    default_quad = next(row for row in quadrature if row["wavelength_samples"] == 257)
    default_lookup = next(row for row in lookup if row["temperature_samples"] == 8193)
    camera = BandRadiometry(band_um=BAND_UM)
    edge = np.full((31, 41), 25., dtype=np.float64)
    edge[:, 20:] = 150.
    sigma, truncate = 1.2, 3.
    radiance_blurred = camera.temperature(gaussian_psf_radiance(camera.radiance(edge), sigma, truncate))
    temperature_blurred = temperature_blur_for_comparison(edge, sigma, truncate)
    difference = radiance_blurred - temperature_blurred
    gates = {"frequency_reference_128_vs_256_relative_error_le_1e_12": reference_difference <= 1e-12,
             "default_direct_quadrature_relative_error_le_1e_5": default_quad["max_relative_error_69_probes"] <= 1e-5,
             "default_forward_lookup_relative_error_le_1e_5": default_lookup["max_forward_relative_error_69_probes"] <= 1e-5,
             "default_inverse_error_le_0_003_c": default_lookup["max_inverse_absolute_error_c_69_probes"] <= .003,
             "quadrature_max_error_decreases_with_refinement": all(a["max_relative_error_69_probes"] > b["max_relative_error_69_probes"] for a, b in itertools.pairwise(quadrature)),
             "interpolation_only_error_decreases_with_refinement": all(a["max_interpolation_only_relative_error"] > b["max_interpolation_only_relative_error"] for a, b in itertools.pairwise(lookup)),
             "radiance_and_temperature_blur_are_distinct": float(np.max(np.abs(difference))) > 1.}
    return {"status": "passed" if all(gates.values()) else "failed", "gates": gates,
            "scope": "numerical consistency of ideal-band synthetic radiometry only",
            "band_um": list(BAND_UM), "temperature_cases_c": list(CASES_C), "seed": SEED,
            "additional_random_interior_probes": 64, "all_probe_temperatures_c": temperatures.tolist(),
            "reference": {"method": "B_nu frequency-domain Gauss-Legendre integral with exact SI h,c,k",
                          "nodes": 256, "crosscheck_nodes": 128,
                          "max_relative_difference": reference_difference,
                          "independent_of_implementation": "No implementation constants, B_lambda function, LUT, or inversion called by reference calculation"},
            "quadrature_convergence": quadrature, "lookup_convergence_at_257_wavelengths": lookup,
            "default_error_summary": {"max_direct_relative_band_error": default_quad["max_relative_error_69_probes"],
                                      "max_lookup_relative_band_error": default_lookup["max_forward_relative_error_69_probes"],
                                      "max_inverse_absolute_error_c": default_lookup["max_inverse_absolute_error_c_69_probes"]},
            "edge_blur_illustration": {"shape": [31, 41], "cold_c": 25., "hot_c": 150.,
                                       "hot_starts_at_column": 20, "sigma_px": sigma, "truncate": truncate,
                                       "max_absolute_difference_c": float(np.max(np.abs(difference))),
                                       "mean_absolute_difference_c": float(np.mean(np.abs(difference))),
                                       "radiance_blur_then_inverse_centerline_c": radiance_blurred[15].tolist(),
                                       "old_temperature_blur_centerline_c": temperature_blurred[15].tolist(),
                                       "interpretation": "Nonlinear radiance inversion changes the simulated edge profile. Neither output is measured ground truth or a sensor-accuracy result."},
            "source_hashes": {str(Path(__file__).resolve()): sha(__file__),
                              str(ROOT / "maek/thermal_radiometry.py"): sha(ROOT / "maek/thermal_radiometry.py")},
            "created_at_utc": datetime.now(UTC).isoformat(), "numpy_version": np.__version__,
            "limits": ["The 69 probes establish only these numerical checks, not a uniform analytical error bound over all inputs.",
                       "Reference convergence is a numerical agreement check, not experimental calibration uncertainty.",
                       "Flat 7.5–14 um response and Gaussian PSF are assumed, not measured camera response/MTF.",
                       "Inverse checks use interior temperatures; unsupported radiance is not silently clamped.",
                       "No model training, classifier accuracy, field validation, or defect observability is established."]}


def snapshot_sources(folder):
    """One bounded attempt/source; no partial PDFs or silent success on failure."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=False)
    max_bytes, timeout, deadline = 32 * 1024 * 1024, 15, 30

    def retrieve(source):
        name, url = source
        started = time.monotonic()
        record = {"file_name": name, "requested_url": url, "attempt_started_at_utc": datetime.now(UTC).isoformat(),
                  "status": "failed", "sha256": None, "bytes": 0, "local_path": None}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (source-archive verification)", "Accept": "application/pdf"})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                record.update(final_url=response.url, http_status=response.status,
                              content_type=response.headers.get("Content-Type"))
                declared_length = response.headers.get("Content-Length")
                if declared_length and int(declared_length) > max_bytes:
                    raise ValueError("Content-Length exceeds 32 MiB bound")
                chunks, total = [], 0
                while True:
                    if time.monotonic() - started > deadline:
                        raise TimeoutError("30-second source retrieval deadline exceeded")
                    block = response.read(min(65536, max_bytes + 1 - total))
                    if not block:
                        break
                    chunks.append(block); total += len(block)
                    if total > max_bytes:
                        raise ValueError("Response exceeds 32 MiB bound")
                payload = b"".join(chunks)
            if not payload.startswith(b"%PDF-") or b"%%EOF" not in payload[-2048:]:
                raise ValueError("Response lacks PDF signature or final EOF marker")
            if declared_length and len(payload) != int(declared_length):
                raise ValueError("Response length differs from declared Content-Length")
            path = folder / name
            with path.open("xb") as handle:
                handle.write(payload)
            record.update(status="downloaded", bytes=len(payload), sha256=sha(path),
                          local_path=str(path.resolve()), retrieved_at_utc=datetime.now(UTC).isoformat(),
                          validation="PDF signature, terminal EOF marker, declared byte length when supplied, and post-write SHA256",
                          review_scope="Snapshot acquired; not exhaustively read or independently authenticated beyond official HTTPS origin")
        except (OSError, ValueError, TimeoutError, urllib.error.URLError) as error:
            record["error"] = f"{type(error).__name__}: {error}"
            record["attempt_finished_at_utc"] = datetime.now(UTC).isoformat()
        record["elapsed_seconds"] = time.monotonic() - started
        return record

    with ThreadPoolExecutor(max_workers=3) as executor:
        records = list(executor.map(retrieve, SOURCES))
    manifest = {"created_at_utc": datetime.now(UTC).isoformat(), "sources": records,
                "downloaded_count": sum(r["status"] == "downloaded" for r in records),
                "failed_count": sum(r["status"] == "failed" for r in records),
                "bounds": {"attempts_per_source": 1, "socket_timeout_seconds": timeout,
                           "deadline_checked_between_reads_seconds": deadline, "max_bytes_per_source": max_bytes},
                "claim": "Only status=downloaded records represent full-file acquisition; failures are explicitly preserved, not called downloads."}
    (folder / "source-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="Fresh JSON file path")
    parser.add_argument("--snapshot-dir", type=Path, help="Optional fresh directory for official PDF snapshots")
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError(f"Refusing to overwrite evidence: {args.out}")
    result = check_numerics()
    if args.snapshot_dir:
        snapshots = snapshot_sources(args.snapshot_dir)
        result["source_snapshots"] = {"manifest": str((args.snapshot_dir / "source-manifest.json").resolve()),
                                      "downloaded_count": snapshots["downloaded_count"], "failed_count": snapshots["failed_count"]}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"status": result["status"], "default_error_summary": result["default_error_summary"],
                      "edge_blur_max_difference_c": result["edge_blur_illustration"]["max_absolute_difference_c"],
                      "source_snapshots": result.get("source_snapshots"), "out": str(args.out.resolve())}))
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
