import json
import os
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st
from google import genai
from google.genai import types

from clipper import export_short, make_analysis_proxy, normalize_clips, probe

st.set_page_config(page_title="ThisSkills AutoClips AI", page_icon="✂️", layout="wide")
st.markdown("""
<style>
.stApp {background:radial-gradient(ellipse at 50% -15%,#30205a 0%,#11101b 42%,#09090f 100%);color:#f7f4ff}
[data-testid="stHeader"]{background:transparent}
.block-container{max-width:1120px;padding-top:2rem;padding-bottom:3rem}
.hero{padding:30px 28px;border:1px solid #493778;border-radius:22px;background:linear-gradient(120deg,rgba(91,55,163,.32),rgba(24,22,39,.92));box-shadow:0 16px 50px rgba(0,0,0,.28);margin-bottom:24px}
.eyebrow{color:#c4a7ff;font-size:12px;letter-spacing:2px;font-weight:800;text-transform:uppercase}
.hero h1{font-size:clamp(28px,5vw,44px);line-height:1.1;margin:10px 0 8px;color:#fff}
.hero p{color:#c9c2dc;font-size:16px;margin:0}
.section-title{font-size:20px;font-weight:750;color:#fff;margin:18px 0 8px}
div[data-testid="stFileUploader"]{background:rgba(255,255,255,.035);border:1px solid #42365e;border-radius:16px;padding:14px}
div.stButton>button[kind="primary"],div.stDownloadButton>button{background:linear-gradient(90deg,#8055e8,#b14be7);color:white;border:0;border-radius:13px;min-height:48px;font-weight:750;box-shadow:0 7px 22px rgba(128,85,232,.22)}
[data-testid="stSidebar"]{background:#100e1b;border-right:1px solid #33264d}
[data-testid="stMetric"]{background:#211a32;border:1px solid #463365;padding:14px;border-radius:14px}
</style>
<div class="hero"><div class="eyebrow">AI-powered video clipping studio</div>
<h1>✂️ ThisSkills AutoClips AI</h1>
<p>Long videos ke sabse engaging moments ko original audio ke saath ready-to-post Shorts mein badlo.</p></div>
""", unsafe_allow_html=True)

api_key = os.getenv("GEMINI_API_KEY", "").strip()
if not api_key:
    try:
        api_key = str(st.secrets.get("GEMINI_API_KEY", "")).strip()
    except Exception:
        api_key = ""
if not api_key:
    st.error("GEMINI_API_KEY missing hai. Streamlit app ke Secrets mein API key add karo.")
    st.stop()

def generate_with_retry(client, contents, config):
    configured = os.getenv("GEMINI_MODEL", "gemini-3.8-flash").strip()
    models = []
    for model in (configured, "gemini-3.8-flash", "gemini-3.5-flash-lite"):
        if model and model not in models:
            models.append(model)
    errors = []
    for model in models:
        for attempt in range(2):
            try:
                st.caption(f"AI model: {model}")
                return client.models.generate_content(
                    model=model, contents=contents, config=config
                )
            except Exception as exc:
                msg = str(exc)
                upper = msg.upper()
                missing = "404" in upper or "NOT_FOUND" in upper
                transient = any(x in upper for x in (
                    "429", "500", "502", "503", "504", "UNAVAILABLE",
                    "RESOURCE_EXHAUSTED", "INTERNAL", "DEADLINE_EXCEEDED",
                    "TIMEOUT"
                ))
                errors.append(f"{model}: {msg[-450:]}")
                if not missing and not transient:
                    raise
                if transient and attempt == 0:
                    delay = 4 * (2 ** attempt)
                    st.warning(f"Google AI busy hai. {delay} sec baad retry...")
                    time.sleep(delay)
                    continue
                break
    raise RuntimeError(
        "Gemini ke backup models se bhi response nahi mila. "
        "503 ka matlab server busy; 429 ka matlab API quota/rate limit ho sakti hai. "
        + " | ".join(errors[-3:])
    )

def wait_for_gemini_file(client, remote):
    started = time.time()
    while str(getattr(remote.state, "name", remote.state)).upper().endswith("PROCESSING"):
        if time.time() - started > 1200:
            raise RuntimeError("Gemini video processing mein 20 minute se zyada lag gaye.")
        time.sleep(4)
        remote = client.files.get(name=remote.name)
    state = str(getattr(remote.state, "name", remote.state)).upper()
    if state.endswith("FAILED"):
        raise RuntimeError("Gemini video process nahi kar paya. Chhoti video try karo.")
    return remote

def download_youtube(url, folder):
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    allowed = host in {
        "youtube.com", "www.youtube.com", "m.youtube.com",
        "youtu.be", "www.youtu.be"
    }
    if parsed.scheme not in ("http", "https") or not allowed:
        raise RuntimeError("Valid YouTube ya youtu.be link paste karo.")
    from yt_dlp import YoutubeDL
    options = {
        "format": "bv*[height<=1080]+ba/b[height<=1080]/best",
        "outtmpl": str(folder / "source.%(ext)s"),
        "merge_output_format": "mp4",
        "noplaylist": True, "quiet": True, "no_warnings": True,
        "retries": 3, "extractor_retries": 3, "fragment_retries": 3,
        "js_runtimes": {"deno": {}},
    }
    try:
        with YoutubeDL(options) as ydl:
            ydl.download([url.strip()])
    except Exception as first:
        for stale in folder.glob("source.*"):
            try:
                stale.unlink()
            except OSError:
                pass
        options["format"] = "best"
        try:
            with YoutubeDL(options) as ydl:
                ydl.download([url.strip()])
        except Exception as second:
            raise RuntimeError(
                "YouTube se video download nahi hui. Kuch videos par YouTube 403/authorization block lagata hai. "
                "Aisi video ko upload option se bhejo. Details: " + str(second)[-500:]
            ) from first
    files = [p for p in folder.glob("source.*") if p.suffix.lower() in
             {".mp4", ".mkv", ".webm", ".mov"}]
    if not files:
        raise RuntimeError("YouTube download ke baad video file nahi mili.")
    return max(files, key=lambda p: p.stat().st_size)

with st.sidebar:
    st.header("⚙️ Shorts settings")
    layout = st.radio("Video layout", ["Auto 9:16", "Facecam upar + gameplay niche"])
    facecam_share = st.slider("Facecam ka screen hissa", 40, 70, 55, 5)
    burn_subtitles = st.checkbox("Hindi/English subtitles video par lagao", True)
    st.caption("AI clips ki count khud decide karega. Har Short 8–60 sec.")

st.markdown('<div class="section-title">🎬 1. Apni long video choose karo</div>', unsafe_allow_html=True)
source_type = st.radio("Video kahan se leni hai?", ["Phone/computer se upload", "YouTube link"], horizontal=True)
uploaded = None
youtube_url = ""
if source_type == "Phone/computer se upload":
    uploaded = st.file_uploader(
        "⬆️ Video upload karo · MP4, MOV, MKV, WEBM",
        type=["mp4", "mov", "mkv", "webm"]
    )
    if uploaded:
        st.success(f"Ready: {uploaded.name} · {uploaded.size / (1024*1024):.1f} MB")
else:
    youtube_url = st.text_input(
        "YouTube video URL",
        placeholder="https://www.youtube.com/watch?v=..."
    )
    st.caption("Sirf public video ya aisi video use karo jise download karne ki permission tumhare paas hai.")

ready = bool(uploaded) if source_type.startswith("Phone") else bool(youtube_url.strip())
if st.button("✨ Generate engaging Shorts", type="primary", use_container_width=True, disabled=not ready):
    work = Path(tempfile.mkdtemp(prefix="autoclips_"))
    client = None
    remote = None
    try:
        with st.spinner("Video prepare ho rahi hai..."):
            if uploaded:
                suffix = Path(uploaded.name).suffix.lower() or ".mp4"
                source = work / ("original" + suffix)
                source.write_bytes(uploaded.getbuffer())
            else:
                source = download_youtube(youtube_url, work)

            duration, width, height = probe(source)
            if duration < 10:
                raise RuntimeError("Kam se kam 10 second ki video chahiye.")
            st.info(f"Video ready · {duration/60:.1f} min · {width}×{height}")

            analysis_file = work / "analysis.mp4"
            try:
                analysis_file = make_analysis_proxy(source, analysis_file)
            except Exception:
                analysis_file = source

        client = genai.Client(api_key=api_key)
        with st.spinner("Gemini video ke engaging moments dhoondh raha hai..."):
            remote = client.files.upload(file=str(analysis_file))
            remote = wait_for_gemini_file(client, remote)
            prompt = f"""
You are an expert short-form video editor. Analyze the COMPLETE video and find only genuinely engaging,
self-contained moments. Decide the number of clips yourself; do not force a fixed count.
Each clip must be 8 to 60 seconds. Choose natural beginnings and endings, preserve complete sentences,
jokes, reactions and necessary context. Avoid intros, silence, repeated moments and mid-sentence cuts.
All start/end timestamps must be absolute seconds on the ORIGINAL video timeline.
Captions are optional short spoken-word chunks; their timestamps must be relative to the clip start.
For a gaming stream with visible facecam and gameplay panels, return normalized source-frame bounding
boxes (x,y,w,h between 0 and 1) for both. If uncertain, use null for both.
Return valid JSON only in this exact shape:
{{"clips":[{{"start":12.0,"end":42.0,"reason":"why this moment is engaging",
"hook":"short opening hook","captions":[{{"start":0.0,"end":2.0,"text":"spoken words"}}],
"facecam_bbox":{{"x":0.1,"y":0.0,"w":0.4,"h":0.3}},
"gameplay_bbox":{{"x":0.0,"y":0.3,"w":1.0,"h":0.7}}}}]}}
If not a gaming stream, set facecam_bbox and gameplay_bbox to null.
Video duration: {duration:.2f} seconds. Never invent timestamps outside the video.
"""
            response = generate_with_retry(
                client, [remote, prompt],
                types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.2
                )
            )
            result = json.loads(response.text or "{}")
            clips = normalize_clips(result.get("clips", []), duration)

        if not clips:
            st.warning("Is video mein AI ko koi valid 8–60 sec engaging moment nahi mila. Dusri video try karo.")
            st.stop()

        output_dir = work / "shorts"
        output_dir.mkdir()
        completed = []
        progress = st.progress(0)
        status = st.empty()
        for index, clip in enumerate(clips, 1):
            output = output_dir / f"short_{index:02}.mp4"
            wants_stack = layout == "Facecam upar + gameplay niche"
            has_boxes = isinstance(clip.get("facecam_bbox"), dict) and isinstance(clip.get("gameplay_bbox"), dict)
            if wants_stack and not has_boxes:
                st.warning(f"Short {index}: facecam/gameplay detect nahi hua, Auto 9:16 layout use kiya.")
            export_short(
                source, output, clip, (width, height),
                stacked=wants_stack and has_boxes,
                facecam_share=facecam_share,
                burn_subtitles=burn_subtitles,
                work_dir=work,
                number=index
            )
            completed.append((output, clip))
            progress.progress(int(index / len(clips) * 100))
            status.caption(f"{index}/{len(clips)} Shorts export ho gaye...")

        archive = work / "ThisSkills_AutoClips.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
            for output, _ in completed:
                bundle.write(output, output.name)

        st.success(f"🎉 {len(completed)} Shorts ready!")
        st.download_button(
            "⬇️ Saare Shorts ZIP mein download karo",
            archive.read_bytes(),
            file_name="ThisSkills_AutoClips.zip",
            mime="application/zip",
            type="primary",
            use_container_width=True
        )
        for index, (output, clip) in enumerate(completed, 1):
            with st.container(border=True):
                st.subheader(f"🎞️ Short {index} · {clip['end']-clip['start']:.1f} sec")
                st.caption(str(clip.get("reason", "")) + " · " + str(clip.get("hook", "")))
                st.video(str(output))
                st.download_button(
                    f"⬇️ Download Short {index}",
                    output.read_bytes(),
                    file_name=output.name,
                    mime="video/mp4",
                    key=f"download_{index}"
                )
    except Exception as error:
        st.error(f"Processing error: {error}")
        st.caption("Agar Gemini 503 de to Google server busy ho sakta hai; 429 par API quota/rate limit check karo.")
    finally:
        if client and remote:
            try:
                client.files.delete(name=remote.name)
            except Exception:
                pass
        shutil.rmtree(work, ignore_errors=True)

st.divider()
st.caption("Gemini moment detection · FFmpeg editing · Original video/audio · Auto 9:16 or streamer split · ZIP export")
