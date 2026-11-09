"""Encode recorded Unity frames with the same pipe/evidence labels as the live UI."""
from __future__ import annotations

import argparse
import json
import subprocess
import textwrap
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont


def overlay(image: Image.Image, frame: dict) -> Image.Image:
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")
    scale = image.width / 960
    font_path = Path("C:/Windows/Fonts/malgun.ttf")
    font = ImageFont.truetype(str(font_path), round(18 * scale))
    small = ImageFont.truetype(str(font_path), round(14 * scale))
    draw.rectangle((0, 0, image.width, round((164 if frame.get("processContext") else 114) * scale)), fill=(8, 20, 30, 225))
    draw.text((20 * scale, 10 * scale), "MAEK  |  드론 배관 검사 시연", font=font,
              fill=(245, 250, 255))
    draw.text((20 * scale, 43 * scale), frame["status"][:90], font=small,
              fill=(240, 245, 248))
    draw.text((20 * scale, 78 * scale), frame["scope"], font=small, fill=(132, 214, 220))
    if frame.get("processContext"):
        context = "\n".join(textwrap.wrap(frame["processContext"], width=70)[:2])
        draw.text((20 * scale, 102 * scale), context, font=small, fill=(230, 240, 245))
        draw.text((20 * scale, 143 * scale), frame.get("workerContext", frame.get("numericalScope", "")),
                  font=small, fill=(255, 210, 140))
    for pin in frame.get("pins", []):
        x, y = pin["u"] * image.width, pin["v"] * image.height
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=(255, 142, 45),
                     outline=(255, 255, 255), width=2)
        tx = max(8, min(x + 16, image.width - 280 * scale))
        ty = max((170 if frame.get("processContext") else 120) * scale, min(y + 12, image.height - 60 * scale))
        draw.line((x, y, tx, ty), fill=(255, 186, 80), width=2)
        draw.rectangle((tx - 4, ty - 4, tx + 270 * scale, ty + 52 * scale),
                       fill=(8, 20, 30, 225))
        draw.text((tx, ty), pin["pipeId"] + "\n" + pin["label"], font=small,
                  fill=(255, 220, 165))
    draw.text((20 * scale, image.height - 28 * scale),
              f'{frame["time"]:05.1f}s  ·  {frame["stage"]}', font=small,
              fill=(255, 255, 255), stroke_width=1, stroke_fill=(0, 0, 0))
    return image


def encode(folder: Path, output: Path) -> dict:
    settings = json.loads((folder / "recording.json").read_text(encoding="utf-8-sig"))
    if not 1 <= settings["fps"] <= 60:
        raise ValueError("Recording fps must be in 1..60")
    frames = [json.loads(line) for line in (folder / "frames.jsonl").read_text(
        encoding="utf-8-sig").splitlines() if line.strip()]
    if not frames or [f["frame"] for f in frames] != list(range(len(frames))):
        raise ValueError("Recording has missing or unordered frame metadata")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError(f"Choose a fresh output path: {output}")
    writer = imageio_ffmpeg.write_frames(
        str(output), (settings["width"], settings["height"]), fps=settings["fps"],
        codec="libx264", quality=7, macro_block_size=2, output_params=["-movflags", "+faststart"],
    )
    writer.send(None)
    try:
        for frame in frames:
            with Image.open(folder / f'{frame["frame"]:06d}.png') as source:
                if source.size != (settings["width"], settings["height"]):
                    raise ValueError("Frame dimensions differ from recording settings")
                image = overlay(source, frame)
            writer.send(image.tobytes())
            if frame["frame"] in (0, len(frames) // 2, len(frames) - 1) or (
                frame.get("pins") and not (output.parent / "evidence_preview.png").exists()
            ):
                image.save(output.parent / ("evidence_preview.png" if frame.get("pins")
                                           else f'preview_{frame["frame"]:06d}.png'))
    finally:
        writer.close()
    check = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(output),
                            "-f", "null", "-"], capture_output=True, text=True, check=True)
    if check.stderr.strip():
        raise RuntimeError("Video decoder reported errors: " + check.stderr)
    result = {"status": "PASS", "frames": len(frames),
              "duration_s": len(frames) / settings["fps"], "fps": settings["fps"],
              "dimensions": [settings["width"], settings["height"]],
              "file": str(output.resolve()), "bytes": output.stat().st_size,
              "decoded_without_errors": not check.stderr.strip(),
              "frames_with_result_labels": sum(bool(f.get("pins")) for f in frames)}
    (output.parent / "video_report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(encode(args.folder, args.output), indent=2))
