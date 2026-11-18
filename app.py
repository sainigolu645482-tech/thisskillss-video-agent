import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="ThisSkills AutoClips AI", page_icon="✂️", layout="centered")
st.title("✂️ ThisSkills AutoClips AI")
st.caption("Upload a video. Gemini finds the strongest complete moments and turns them into Shorts.")

api_key = os.getenv("GEMINI_API_KEY", "").strip()
if not api_key:
    st.error("GEMINI_API_KEY is not configured. Add it to your environment/secrets before running.")
    st.stop()

uploaded = st.file_uploader("Upload your original video", type=["mp4", "mov", "mkv", "webm"])
if uploaded:
    st.video(uploaded)
    if st.button("Find engaging moments and create Shorts", type="primary", use_container_width=True):
        with st.spinner("Uploading video to Gemini and analyzing engaging moments..."):
            try:
                suffix = Path(uploaded.name).suffix or ".mp4"
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                    tmp.write(uploaded.getvalue())
                    source_path = Path(tmp.name)

                client = genai.Client(api_key=api_key)
                gemini_file = client.files.upload(file=str(source_path))
                while gemini_file.state.name == "PROCESSING":
                    import time
                    time.sleep(3)
                    gemini_file = client.files.get(name=gemini_file.name)
                if gemini_file.state.name == "FAILED":
                    raise RuntimeError("Gemini could not process this video. Try MP4 or a smaller file.")

                prompt = """
Analyze the entire uploaded video and identify ONLY genuinely engaging, self-contained moments
that could work as YouTube Shorts. Do not force a fixed number of clips. Return as many strong
moments as exist, and return an empty list if none are good. Each clip must be at most 60 seconds.
Choose natural boundaries: preserve the complete thought, question-answer, joke, reveal, or story;
never cut a sentence or important context. Avoid overlapping clips and near-duplicates.
Return ONLY JSON:
{"clips":[{"start":12.3,"end":47.8,"reason":"why this moment is engaging","hook":"short Hindi/English hook"}]}
Times are seconds from the start of the source video. Be precise and do not invent timestamps.
"""
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[gemini_file, prompt],
                    config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.2),
                )
                data = json.loads(response.text)
                clips = data.get("clips", [])
                duration = float(subprocess.check_output(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", str(source_path)], text=True
                ).strip())
                valid = []
                for clip in clips:
                    start, end = float(clip["start"]), float(clip["end"])
                    if 0 <= start < end <= duration and end - start <= 60:
                        valid.append({**clip, "start": start, "end": end})
                valid.sort(key=lambda x: x["start"])
                if not valid:
                    st.info("Gemini did not find any valid engaging moments in this video.")
                else:
                    output_dir = Path("output")
                    output_dir.mkdir(exist_ok=True)
                    st.success(f"Gemini selected {len(valid)} engaging moments.")
                    for i, clip in enumerate(valid, 1):
                        out = output_dir / f"short_{i:02d}.mp4"
                        length = clip["end"] - clip["start"]
                        vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
                        subprocess.run([
                            "ffmpeg", "-y", "-ss", str(clip["start"]), "-i", str(source_path),
                            "-t", str(length), "-vf", vf, "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "23", "-c:a", "aac", "-movflags", "+faststart", str(out)
                        ], check=True, capture_output=True, text=True)
                        st.markdown(f"**Short {i} · {length:.1f} sec**")
                        st.caption(f"{clip.get('reason', '')} · {clip.get('hook', '')}")
                        st.video(str(out))
                        st.download_button(f"Download Short {i}", out.read_bytes(),
                                            file_name=out.name, mime="video/mp4", key=f"download_{i}")
                client.files.delete(name=gemini_file.name)
                source_path.unlink(missing_ok=True)
            except Exception as exc:
                st.error(f"Processing failed: {exc}")
                st.caption("Check your Gemini API key, video format, and FFmpeg installation.")
