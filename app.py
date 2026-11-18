import json, os, subprocess, tempfile, shutil, zipfile, time
from pathlib import Path
import streamlit as st
from google import genai
from google.genai import types

st.set_page_config(page_title="ThisSkills AutoClips AI", page_icon="✂️", layout="wide")
st.markdown("""
<style>
.stApp {background: radial-gradient(ellipse at 50% -15%, #30205a 0%, #11101b 42%, #09090f 100%); color:#f7f4ff;}
[data-testid="stHeader"] {background:transparent;}
.block-container {max-width:1120px; padding-top:2rem; padding-bottom:3rem;}
.hero {padding:30px 28px; border:1px solid #493778; border-radius:22px; background:linear-gradient(120deg,rgba(91,55,163,.32),rgba(24,22,39,.92)); box-shadow:0 16px 50px rgba(0,0,0,.28); margin-bottom:24px;}
.eyebrow {color:#c4a7ff; font-size:12px; letter-spacing:2px; font-weight:800; text-transform:uppercase;}
.hero h1 {font-size:clamp(28px,5vw,44px); line-height:1.1; margin:10px 0 8px; color:#fff;}
.hero p {color:#c9c2dc; font-size:16px; margin:0;}
.section-title {font-size:20px; font-weight:750; color:#fff; margin:18px 0 8px;}
.upload-hint {border:1px dashed #7657bd; border-radius:18px; padding:18px; background:rgba(87,59,145,.12); color:#d9d0ed; text-align:center; margin:8px 0 14px;}
div[data-testid="stFileUploader"] {background:rgba(255,255,255,.035); border:1px solid #42365e; border-radius:16px; padding:14px;}
div.stButton > button[kind="primary"], div.stDownloadButton > button {background:linear-gradient(90deg,#8055e8,#b14be7); color:white; border:0; border-radius:13px; min-height:48px; font-weight:750; box-shadow:0 7px 22px rgba(128,85,232,.22);}
div.stButton > button[kind="primary"]:hover, div.stDownloadButton > button:hover {border:1px solid #d8c4ff; color:white;}
[data-testid="stSidebar"] {background:#100e1b; border-right:1px solid #33264d;}
[data-testid="stSidebar"] h2 {color:#d7c5ff;}
[data-testid="stMetric"] {background:#211a32; border:1px solid #463365; padding:14px; border-radius:14px;}
.stAlert {border-radius:14px;}
hr {border-color:#34294b;}
</style>
<div class="hero">
  <div class="eyebrow">AI-powered video clipping studio</div>
  <h1>✂️ ThisSkills AutoClips AI</h1>
  <p>Long videos ke sabse engaging moments ko original audio ke saath ready-to-post Shorts mein badlo.</p>
</div>
""", unsafe_allow_html=True)
key=os.getenv("GEMINI_API_KEY","").strip()
if not key:
    try: key=st.secrets.get("GEMINI_API_KEY","").strip()
    except Exception: key=""
if not key:
    st.error("GEMINI_API_KEY missing hai. Secrets mein add karo.")
    st.stop()

def generate_with_retry(client, model, contents, config, attempts=2):
    """Try current Gemini models in order and retry transient server/quota errors."""
    candidates = []
    for name in (model, "gemini-3.8-flash", "gemini-3.5-flash-lite"):
        name = (name or "").strip()
        if name and name not in candidates:
            candidates.append(name)

    failures = []
    for model_index, candidate in enumerate(candidates):
        for attempt in range(attempts):
            try:
                st.info(f"Gemini model try ho raha hai: {candidate}")
                return client.models.generate_content(
                    model=candidate, contents=contents, config=config
                )
            except Exception as err:
                message = str(err)
                upper = message.upper()
                retryable = any(code in upper for code in (
                    "429", "500", "502", "503", "504",
                    "RESOURCE_EXHAUSTED", "UNAVAILABLE",
                    "INTERNAL", "DEADLINE_EXCEEDED",
                    "SERVICE UNAVAILABLE", "TIMEOUT"
                ))
                model_missing = ("404" in upper or "NOT_FOUND" in upper or
                                 "MODEL" in upper and "NOT FOUND" in upper)
                failures.append(f"{candidate}: {message[-500:]}")
                if not retryable and not model_missing:
                    raise
                if retryable and attempt < attempts - 1:
                    wait = 5 * (2 ** attempt)
                    st.warning(
                        f"{candidate} abhi busy/limited hai. {wait} second baad "
                        f"dobara try kar rahe hain..."
                    )
                    time.sleep(wait)
                    continue
                if model_index < len(candidates) - 1:
                    st.warning(
                        f"{candidate} available nahi hai. Ab next backup model "
                        f"try kar rahe hain..."
                    )
                break

    details = "\n".join(failures[-3:])
    raise RuntimeError(
        "Gemini ke sabhi available models se response nahi mila. "
        "Agar 503/UNAVAILABLE aa raha hai to Google server busy hai; "
        "thodi der baad dobara try karo. Agar 429/RESOURCE_EXHAUSTED hai "
        "to Gemini API quota/billing limit check karo. Details:\\n" + details
    )

def run(args):
    p=subprocess.run(args,capture_output=True,text=True)
    if p.returncode: raise RuntimeError((p.stderr or p.stdout)[-1500:])
    return p.stdout.strip()

def probe(path):
    d=json.loads(run(["ffprobe","-v","error","-show_entries","format=duration:stream=width,height","-of","json",str(path)]))
    v=next(s for s in d["streams"] if s.get("width") and s.get("height"))
    return float(d["format"]["duration"]),int(v["width"]),int(v["height"])

def box_filter(box,w,h):
    if not isinstance(box,dict): return None
    try:
        x=max(0,min(1,float(box["x"]))); y=max(0,min(1,float(box["y"])))
        bw=max(.05,min(1-x,float(box["w"]))); bh=max(.05,min(1-y,float(box["h"])))
        cw=max(2,int(w*bw)//2*2); ch=max(2,int(h*bh)//2*2)
        return f"crop={cw}:{ch}:{int(w*x)}:{int(h*y)}"
    except (KeyError,ValueError,TypeError): return None

def make_srt(captions,path,duration):
    rows=[]
    for n,c in enumerate(captions or [],1):
        try:
            a=max(0,int(float(c["start"])*1000)); b=min(int(duration*1000),int(float(c["end"])*1000))
            if b<=a: continue
            def stamp(v):
                h,v=divmod(v,3600000); m,v=divmod(v,60000); s,ms=divmod(v,1000)
                return f"{h:02}:{m:02}:{s:02},{ms:03}"
            rows += [str(n),stamp(a)+" --> "+stamp(b),str(c["text"]).strip(),""]
        except (KeyError,ValueError,TypeError): pass
    if not rows: return False
    path.write_text("\n".join(rows),encoding="utf-8"); return True

def export(src,out,c,size,stack,share,burn,folder,n):
    w,h=size; length=c["end"]-c["start"]; srt=folder/f"cap{n}.srt"
    has=make_srt(c.get("captions",[]),srt,length) if burn else False
    if stack:
        cam=box_filter(c.get("facecam_bbox"),w,h); game=box_filter(c.get("gameplay_bbox"),w,h)
        if not cam or not game: raise RuntimeError("Facecam/gameplay detect nahi hua. Auto 9:16 layout try karo.")
        top=int(1920*share/100); low=1920-top
        graph=f"[0:v]{cam},scale=1080:{top}:force_original_aspect_ratio=decrease,pad=1080:{top}:(ow-iw)/2:(oh-ih)/2:black[c];[0:v]{game},scale=1080:{low}:force_original_aspect_ratio=decrease,pad=1080:{low}:(ow-iw)/2:(oh-ih)/2:black[g];[c][g]vstack[v]"
        if has:
            sp=str(srt).replace("\\","/").replace(":","\\:")
            graph+=f";[v]subtitles='{sp}':force_style='FontName=Arial,FontSize=18,Outline=2,Alignment=2,MarginV=50'[out]"
        else: graph+=";[v]null[out]"
        args=["ffmpeg","-y","-ss",str(c["start"]),"-i",str(src),"-t",str(length),"-filter_complex",graph,"-map","[out]","-map","0:a?"]
    else:
        graph=("[0:v]split[bg][fg];[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
               "crop=1080:1920,boxblur=22:10[blur];[fg]scale=1080:1920:force_original_aspect_ratio=decrease[front];"
               "[blur][front]overlay=(W-w)/2:(H-h)/2[v]")
        if has:
            sp=str(srt).replace("\\","/").replace(":","\\:")
            graph+=f";[v]subtitles='{sp}':force_style='FontName=Arial,FontSize=18,Outline=2,Alignment=2,MarginV=50'[vout]"
        else:
            graph+=";[v]null[vout]"
        args=["ffmpeg","-y","-ss",str(c["start"]),"-i",str(src),"-t",str(length),"-filter_complex",graph,"-map","[vout]","-map","0:a?"]
    run(args+["-c:v","libx264","-preset","veryfast","-crf","23","-c:a","aac","-movflags","+faststart",str(out)])

with st.sidebar:
    st.header("⚙️ Shorts settings")
    st.caption("Apne Shorts ka look choose karo.")
    layout=st.radio("Layout",["Auto 9:16","Facecam upar + gameplay niche"])
    share=st.slider("Facecam ka screen hissa",40,70,55,5)
    burn=st.checkbox("Subtitles video par lagao",True)

st.markdown('<div class="section-title">🎬 1. Apni long video choose karo</div>', unsafe_allow_html=True)
st.markdown("**YouTube link paste karo**")
video_url=st.text_input("YouTube video URL",placeholder="https://www.youtube.com/watch?v=...")
st.caption("Ya phir neeche phone se video upload karo.")
video=st.file_uploader("⬆️ Video upload karo · MP4, MOV, MKV, WEBM",type=["mp4","mov","mkv","webm"])
if video:
    st.success(f"Uploaded: {video.name} · {video.size / (1024*1024):.1f} MB")
if video_url.strip():
    st.info("YouTube link ready hai. Public video ya aisa video use karo jise download karne ki permission tumhare paas ho.")
if (video or video_url.strip()) and st.button("✨  Generate engaging Shorts",type="primary",use_container_width=True):
    folder=Path(tempfile.mkdtemp()); client=None; remote=None
    try:
        if video:
            src=folder/(Path(video.name).stem+(Path(video.name).suffix or ".mp4"))
            src.write_bytes(video.getvalue())
        else:
            from urllib.parse import urlparse
            from yt_dlp import YoutubeDL
            parsed=urlparse(video_url.strip())
            host=(parsed.hostname or "").lower()
            allowed=host in {"youtube.com","www.youtube.com","m.youtube.com","youtu.be","www.youtu.be"}
            if parsed.scheme not in {"http","https"} or not allowed:
                raise RuntimeError("Abhi sirf valid YouTube ya youtu.be link supported hai.")
            st.info("YouTube video download ho rahi hai... thoda wait karo.")
            # Try a high-quality video+audio combination, then fall back to any
            # single-file format available for this particular YouTube video.
            base_opts={"outtmpl":str(folder/"source.%(ext)s"),
                       "merge_output_format":"mp4","noplaylist":True,
                       "quiet":True,"no_warnings":True,
                       "retries":3,"extractor_retries":3,"fragment_retries":3,
                       "js_runtimes":{"deno":{}}}
            download_error=None
            download_attempts=[
                # YouTube's web_safari client can expose HLS formats that avoid
                # some of the newer GVS PO-token restrictions.
                {"format":"best","extractor_args":{"youtube":{"player_client":["web_safari"]}}},
                {"format":"bv*[height<=1080]+ba/b[height<=1080]/best"},
                {"format":"best"},
            ]
            for attempt_opts in download_attempts:
                try:
                    with YoutubeDL({**base_opts,**attempt_opts}) as ydl:
                        ydl.download([video_url.strip()])
                    download_error=None
                    break
                except Exception as err:
                    download_error=err
                    for stale in folder.glob("source.*"):
                        try: stale.unlink()
                        except OSError: pass
            if download_error:
                raise RuntimeError("YouTube ke available formats download nahi ho paaye. Dusra public link try karo. Details: "+str(download_error)[-700:])
            candidates=[p for p in folder.glob("source.*") if p.suffix.lower() in {".mp4",".mkv",".webm",".mov"}]
            if not candidates:
                raise RuntimeError("YouTube se video file nahi mili. Link public hai ya nahi check karo.")
            src=max(candidates,key=lambda p:p.stat().st_size)
        duration,w,h=probe(src)
        if duration<10: raise RuntimeError("Kam se kam 10 second ki video chahiye.")
        client=genai.Client(api_key=key)
        with st.spinner("Gemini video analyze kar raha hai..."):
            remote=client.files.upload(file=str(src))
            while getattr(remote.state,"name",str(remote.state))=="PROCESSING":
                time.sleep(3); remote=client.files.get(name=remote.name)
            if getattr(remote.state,"name",str(remote.state))=="FAILED": raise RuntimeError("Gemini video process nahi kar paya.")
            prompt=f"""
Find only strong, self-contained engaging moments from this whole video. Do not force a count.
Each clip must be 8-60 seconds. Preserve full sentences, jokes, reactions and context; no mid-sentence cuts.
Return spoken subtitle chunks with accurate timestamps relative to each clip start.
For gaming streams with separate facecam and gameplay panels, return normalized source-frame rectangles
facecam_bbox and gameplay_bbox as x,y,w,h between 0 and 1. If unsure or not a stream, set both null.
Return JSON only:
{{"clips":[{{"start":12.3,"end":47.8,"reason":"why engaging","hook":"short hook",
"captions":[{{"start":0,"end":2.5,"text":"spoken words"}}],
"facecam_bbox":{{"x":0.1,"y":0,"w":0.4,"h":0.3}},
"gameplay_bbox":{{"x":0,"y":0.3,"w":1,"h":0.7}}}}]}}
Clip start/end are absolute source seconds. Captions are relative seconds. Do not invent timestamps.
Video duration {duration:.2f} seconds.
"""
            response=generate_with_retry(
                client,
                os.getenv("GEMINI_MODEL","gemini-3.8-flash"),
                [remote,prompt],
                types.GenerateContentConfig(response_mime_type="application/json",temperature=.2)
            )
            data=json.loads(response.text)
        clips=[]
        for c in data.get("clips",[]):
            try:
                a=float(c["start"]); b=float(c["end"])
                if 0<=a<b<=duration and 8<=b-a<=60 and (not clips or a>=clips[-1]["end"]):
                    c["start"]=a; c["end"]=b; clips.append(c)
            except (KeyError,ValueError,TypeError): pass
        if not clips: st.warning("Koi valid engaging moment nahi mila."); st.stop()
        outdir=folder/"shorts"; outdir.mkdir(); results=[]; bar=st.progress(0)
        for i,c in enumerate(clips,1):
            out=outdir/f"short_{i:02}.mp4"
            export(src,out,c,(w,h),layout=="Facecam upar + gameplay niche",share,burn,folder,i)
            results.append((out,c)); bar.progress(int(i/len(clips)*100))
        archive=folder/"ThisSkills_AutoClips.zip"
        with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
            for out,c in results: z.write(out,out.name)
        st.success(f"🎉 {len(results)} Shorts ready!")
        st.markdown('<div class="section-title">📱 2. Your ready Shorts</div>', unsafe_allow_html=True)
        st.download_button("Saare Shorts ZIP mein download karo",archive.read_bytes(),file_name="ThisSkills_AutoClips.zip",mime="application/zip",type="primary")
        for i,(out,c) in enumerate(results,1):
            with st.container(border=True):
                st.subheader(f"🎞️ Short {i} · {c['end']-c['start']:.1f} sec")
                st.caption(str(c.get("reason",""))+" · "+str(c.get("hook","")))
                st.video(str(out))
                st.download_button(f"⬇️ Download Short {i}",out.read_bytes(),file_name=out.name,mime="video/mp4",key=f"dl{i}")
    except Exception as e:
        st.error(f"Processing error: {e}")
        st.caption("Gemini API quota/key, FFmpeg, video size aur internet check karo.")
    finally:
        if client and remote:
            try: client.files.delete(name=remote.name)
            except Exception: pass
        shutil.rmtree(folder,ignore_errors=True)

st.divider()
st.caption("Gemini moment detection · FFmpeg editing · Original audio · No generated scenes or AI voiceover")
