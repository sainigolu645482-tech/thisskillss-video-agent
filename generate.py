import asyncio
import json
import os
import re
import time
from pathlib import Path

import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont
import edge_tts
from moviepy.editor import AudioFileClip, ImageClip, concatenate_audioclips, concatenate_videoclips

W, H = 1080, 1920
OUT = Path("output")
OUT.mkdir(exist_ok=True)

API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
TOPIC = os.environ.get("VIDEO_TOPIC", "Claude Code ke 3 powerful features").strip()
MODEL = "gemini-flash-latest"
VOICE = "hi-IN-MadhurNeural"

def ask_gemini():
    if not API_KEY:
        raise RuntimeError("GEMINI_API_KEY secret missing. Add it in GitHub repository Actions secrets.")
    prompt = f"""
Create an original Hindi YouTube Short for the channel Thisskillss.
Topic: {TOPIC}
Audience: Indian beginners interested in AI and technology.
Return ONLY valid JSON with this exact shape:
{{
  "title": "short catchy Hindi title, max 65 characters",
  "description": "2 short Hindi sentences",
  "hashtags": ["#AI", "#HindiTech", "#Thisskillss"],
  "scenes": [
    {{"screen_text": "short on-screen Hindi line, max 8 words", "voiceover": "spoken Hindi narration for this scene, 1-2 sentences"}}
  ]
}}
Requirements:
- 6 scenes exactly, including a strong hook first and a natural subscribe/follow CTA last.
- Total voiceover around 85 to 115 Hindi words.
- Clear, useful, beginner-friendly, no fake statistics or unsupported claims.
- Use natural conversational Hindi, not formal textbook language.
- Screen text should be very short and readable on a phone.
- Each scene voiceover must make sense when read aloud.
"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "responseMimeType": "application/json"}
    }
    headers = {"Content-Type": "application/json", "X-goog-api-key": API_KEY}
    retryable_statuses = {429, 500, 502, 503, 504}
    response = None
    for attempt in range(5):
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=90)
            if response.status_code in retryable_statuses:
                if attempt == 4:
                    response.raise_for_status()
                wait_seconds = min(60, 8 * (2 ** attempt))
                print(f"Gemini is temporarily unavailable (HTTP {response.status_code}). Retrying in {wait_seconds}s...")
                time.sleep(wait_seconds)
                continue
            response.raise_for_status()
            break
        except requests.exceptions.RequestException as exc:
            status = exc.response.status_code if exc.response is not None else None
            if attempt == 4 or (status is not None and status not in retryable_statuses):
                raise
            wait_seconds = min(60, 8 * (2 ** attempt))
            print(f"Gemini request failed ({status or type(exc).__name__}). Retrying in {wait_seconds}s...")
            time.sleep(wait_seconds)
    data = response.json()
    raw = data["candidates"][0]["content"]["parts"][0]["text"]
    result = json.loads(raw)
    scenes = result.get("scenes", [])
    if len(scenes) < 4:
        raise RuntimeError("Gemini returned too few scenes. Run the workflow again.")
    result["scenes"] = scenes[:6]
    return result

def font(size, bold=False):
    candidates = [
        "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Bold.ttf" if bold else "/usr/share/fonts/truetype/noto/NotoSansDevanagari-Regular.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()

def wrap_text(draw, text, selected_font, max_width):
    words = str(text).split()
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if draw.textbbox((0, 0), trial, font=selected_font)[2] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines

def make_scene_image(screen_text, index, total):
    top = np.array((12 + index * 7, 20, 48 + index * 9), dtype=np.float32)
    bottom = np.array((36, 18 + index * 5, 66 + index * 4), dtype=np.float32)
    blend = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    rows = (top[None, None, :] * (1 - blend) + bottom[None, None, :] * blend).astype(np.uint8)
    pixels = np.repeat(rows, W, axis=1)
    image = Image.fromarray(pixels, "RGB")

    draw = ImageDraw.Draw(image, "RGBA")
    draw.ellipse((760, 180, 1220, 640), fill=(40, 180, 220, 32))
    draw.ellipse((-220, 1280, 360, 1860), fill=(150, 90, 240, 30))
    draw.rounded_rectangle((70, 105, 1010, 1815), radius=48, outline=(255,255,255,38), width=3)
    draw.text((110, 155), "THISSKILLSS  •  AI IN HINDI", font=font(34, True), fill=(170, 220, 255, 255))
    draw.rounded_rectangle((110, 245, 300, 258), radius=6, fill=(70, 220, 210, 255))

    title_font = font(82, True)
    lines = wrap_text(draw, screen_text, title_font, 820)
    line_heights = []
    for line in lines:
        box = draw.textbbox((0, 0), line, font=title_font, stroke_width=1)
        line_heights.append(box[3] - box[1])
    total_h = sum(line_heights) + max(0, len(lines)-1) * 30
    y = (H - total_h) // 2 - 40
    for line, line_h in zip(lines, line_heights):
        box = draw.textbbox((0, 0), line, font=title_font, stroke_width=1)
        x = (W - (box[2] - box[0])) // 2
        draw.text((x, y), line, font=title_font, fill=(255,255,255,255), stroke_width=1, stroke_fill=(0,0,0,80))
        y += line_h + 30

    footer = f"SCENE {index + 1:02d} / {total:02d}"
    draw.text((110, 1690), footer, font=font(30, True), fill=(170, 190, 220, 230))
    draw.text((110, 1750), "FOLLOW FOR MORE AI TIPS", font=font(28, True), fill=(100, 230, 210, 255))
    return image

async def make_voice(text, path):
    communicator = edge_tts.Communicate(text=text, voice=VOICE, rate="+4%")
    await communicator.save(str(path))

def main():
    print(f"Generating a Short about: {TOPIC}")
    script = ask_gemini()
    scenes = script["scenes"]
    audio_paths = []
    audio_clips = []
    video_clips = []

    for i, scene in enumerate(scenes):
        narration = str(scene.get("voiceover", "")).strip()
        screen_text = str(scene.get("screen_text", "")).strip()
        if not narration or not screen_text:
            continue
        audio_path = OUT / f"voice_{i+1:02d}.mp3"
        asyncio.run(make_voice(narration, audio_path))
        audio_paths.append(audio_path)
        audio = AudioFileClip(str(audio_path))
        audio_clips.append(audio)
        duration = max(1.8, audio.duration + 0.15)

        frame = make_scene_image(screen_text, i, len(scenes))
        frame_path = OUT / f"scene_{i+1:02d}.jpg"
        frame.save(frame_path, quality=92)
        clip = ImageClip(np.array(frame)).set_duration(duration)
        clip = clip.resize(lambda t: 1.0 + 0.025 * (t / max(duration, 0.1)))
        clip = clip.crop(x_center=W/2, y_center=H/2, width=W, height=H)
        video_clips.append(clip)

    if not audio_clips or not video_clips:
        raise RuntimeError("No valid scenes were generated.")

    final_audio = concatenate_audioclips(audio_clips)
    final_video = concatenate_videoclips(video_clips, method="compose").set_audio(final_audio)
    mp4_path = OUT / "thisskillss_short.mp4"
    final_video.write_videofile(
        str(mp4_path), fps=24, codec="libx264", audio_codec="aac",
        preset="ultrafast", threads=2, logger="bar"
    )

    thumbnail = make_scene_image(script.get("title", "AI TIPS IN HINDI"), 0, len(scenes))
    thumbnail.save(OUT / "thumbnail.jpg", quality=92)

    hashtags = " ".join(script.get("hashtags", []))
    (OUT / "caption.txt").write_text(
        f"{script.get('title','Thisskillss Short')}\n\n{script.get('description','')}\n\n{hashtags}\n",
        encoding="utf-8"
    )
    (OUT / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    final_video.close()
    final_audio.close()
    for clip in audio_clips:
        clip.close()
    print(f"SUCCESS: {mp4_path} and thumbnail/caption are ready.")

if __name__ == "__main__":
    main()
