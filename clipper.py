"""Video probing, subtitle preparation and FFmpeg rendering helpers."""
import json
import subprocess
from pathlib import Path


def run(args):
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode:
        detail = (proc.stderr or proc.stdout or "FFmpeg command failed")[-2500:]
        raise RuntimeError(detail)
    return proc.stdout.strip()


def probe(path):
    raw = run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,width,height:stream_tags=rotate:stream_side_data=rotation",
        "-of", "json", str(path)
    ])
    data = json.loads(raw)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video" and s.get("width") and s.get("height")), None)
    if not video:
        raise RuntimeError("Video stream nahi mila. MP4/MOV/WEBM file try karo.")
    duration = float(data.get("format", {}).get("duration") or 0)
    width, height = int(video["width"]), int(video["height"])
    rotation = 0
    try:
        rotation = int(float(video.get("tags", {}).get("rotate", 0))) % 360
        for item in video.get("side_data_list", []):
            if "rotation" in item:
                rotation = int(float(item["rotation"])) % 360
    except (TypeError, ValueError):
        rotation = 0
    if rotation in (90, 270):
        width, height = height, width
    if duration <= 0:
        raise RuntimeError("Video duration read nahi ho payi.")
    return duration, width, height


def make_analysis_proxy(source, output):
    """Create a smaller, low-frame-rate copy for faster/cheaper Gemini analysis."""
    run([
        "ffmpeg", "-y", "-i", str(source),
        "-vf", "fps=2,scale='min(1280,iw)':-2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
        "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
        str(output)
    ])
    return output if Path(output).exists() and Path(output).stat().st_size else source


def normalize_clips(raw_clips, duration):
    valid = []
    for item in raw_clips or []:
        if not isinstance(item, dict):
            continue
        try:
            start, end = float(item["start"]), float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if start < 0 or end <= start or end > duration + 0.15:
            continue
        start = max(0.0, start)
        end = min(float(duration), end)
        if not 8 <= end - start <= 60:
            continue
        item = dict(item)
        item["start"], item["end"] = start, end
        item["captions"] = item.get("captions") if isinstance(item.get("captions"), list) else []
        valid.append(item)
    valid.sort(key=lambda x: x["start"])
    # Overlapping suggestions often create near-duplicate Shorts. Keep the stronger
    # first suggestion and skip a later clip that substantially overlaps it.
    selected = []
    for item in valid:
        if selected and item["start"] < selected[-1]["end"] - 1.0:
            continue
        selected.append(item)
    return selected


def _safe_crop(box, width, height):
    if not isinstance(box, dict):
        return None
    try:
        x = max(0.0, min(0.98, float(box["x"])))
        y = max(0.0, min(0.98, float(box["y"])))
        bw = max(0.02, min(1.0 - x, float(box["w"])))
        bh = max(0.02, min(1.0 - y, float(box["h"])))
        px = int(width * x)
        py = int(height * y)
        cw = max(2, min(width - px, int(width * bw)))
        ch = max(2, min(height - py, int(height * bh)))
        px -= px % 2
        py -= py % 2
        cw -= cw % 2
        ch -= ch % 2
        if cw < 2 or ch < 2:
            return None
        return f"crop={cw}:{ch}:{px}:{py}"
    except (KeyError, TypeError, ValueError):
        return None


def _subtitle_filter(srt_path):
    path = str(Path(srt_path).resolve()).replace("\\", "/")
    path = path.replace(":", r"\:").replace("'", r"\'")
    return (
        f"subtitles='{path}':force_style="
        "'FontName=Noto Sans Devanagari,FontSize=18,Outline=2,"
        "Shadow=1,Alignment=2,MarginV=100'"
    )


def make_srt(captions, path, duration):
    rows = []

    def stamp(ms):
        hours, rem = divmod(ms, 3600000)
        minutes, rem = divmod(rem, 60000)
        seconds, millis = divmod(rem, 1000)
        return f"{hours:02}:{minutes:02}:{seconds:02},{millis:03}"

    for number, caption in enumerate(captions or [], 1):
        try:
            start = max(0, int(float(caption["start"]) * 1000))
            end = min(int(float(duration) * 1000), int(float(caption["end"]) * 1000))
            text = str(caption.get("text", "")).strip()
            if end <= start or not text:
                continue
            rows.extend([str(number), f"{stamp(start)} --> {stamp(end)}", text, ""])
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        return False
    Path(path).write_text("\n".join(rows), encoding="utf-8")
    return True


def export_short(source, output, clip, source_size, stacked=False,
                 facecam_share=55, burn_subtitles=True, work_dir=None, number=1):
    width, height = source_size
    start, end = float(clip["start"]), float(clip["end"])
    length = end - start
    work_dir = Path(work_dir or Path(output).parent)
    srt = work_dir / f"captions_{number}.srt"
    has_subtitles = burn_subtitles and make_srt(clip.get("captions", []), srt, length)
    filters = []
    if stacked:
        face = _safe_crop(clip.get("facecam_bbox"), width, height)
        game = _safe_crop(clip.get("gameplay_bbox"), width, height)
        if face and game:
            top = max(500, min(1300, int(1920 * int(facecam_share) / 100)))
            bottom = 1920 - top
            graph = (
                f"[0:v]{face},scale=1080:{top}:force_original_aspect_ratio=decrease,"
                f"pad=1080:{top}:(ow-iw)/2:(oh-ih)/2:black[cam];"
                f"[0:v]{game},scale=1080:{bottom}:force_original_aspect_ratio=decrease,"
                f"pad=1080:{bottom}:(ow-iw)/2:(oh-ih)/2:black[game];"
                "[cam][game]vstack=inputs=2[base]"
            )
            if has_subtitles:
                graph += f";[base]{_subtitle_filter(srt)}[vout]"
            else:
                graph += ";[base]null[vout]"
            filters = ["-filter_complex", graph, "-map", "[vout]"]
        else:
            stacked = False

    if not stacked:
        graph = (
            "[0:v]split=2[bg][fg];"
            "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=22:10[blur];"
            "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[front];"
            "[blur][front]overlay=(W-w)/2:(H-h)/2[base]"
        )
        if has_subtitles:
            graph += f";[base]{_subtitle_filter(srt)}[vout]"
        else:
            graph += ";[base]null[vout]"
        filters = ["-filter_complex", graph, "-map", "[vout]"]

    run([
        "ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", str(source),
        "-t", f"{length:.3f}", *filters, "-map", "0:a?",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(output)
    ])
    if not Path(output).exists() or Path(output).stat().st_size == 0:
        raise RuntimeError(f"Short {number} export nahi ho paya.")
    return output
