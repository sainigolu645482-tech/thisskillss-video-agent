# ThisSkills AutoClips AI

This is a **long-video-to-Shorts clipping tool**, not an AI story/video generator. Upload a video you own or have permission to edit. Gemini selects the number of strong, self-contained moments (no fixed clip count; 8–60 seconds each). FFmpeg cuts the original footage and preserves its original audio.

## Features

- Upload MP4, MOV, MKV, or WEBM from phone or computer.
- Gemini finds engaging moments, natural start/end points, a short hook, and subtitle text.
- Normal layout: vertical 9:16 with the complete original frame visible over a blurred background.
- Stream layout: optional facecam-above/gameplay-below stack, with adjustable facecam share (40–70%). Gemini attempts to detect the two source regions.
- Optional burned-in subtitles, individual MP4 downloads, and one ZIP containing all Shorts.
- No generated scenes and no AI voiceover.

## Free deployment on Streamlit Community Cloud

1. Open https://share.streamlit.io/ and sign in with GitHub.
2. Choose **Create app** → **Yup, I have an app**.
3. Select repository `sainigolu645482-tech/thisskillss-video-agent`, branch `main`, and main file path `app.py`.
4. Open **Advanced settings**. Set Python to **3.11**.
5. In **Secrets**, add this (replace the placeholder with your own Gemini API key):
   ```toml
   GEMINI_API_KEY = "PASTE_YOUR_GEMINI_API_KEY_HERE"
   ```
6. Click **Save**, then **Deploy**. Streamlit will show the app URL when deployment completes.

Keep the API key in Streamlit Secrets only. Never commit it to GitHub or share it in chat. Community Cloud is free, but compute, storage, upload, and Gemini API quotas/limits apply.

## Run locally

1. Install Python 3.11+ and FFmpeg with subtitle (libass) support.
2. Install dependencies: `pip install -r requirements.txt`
3. Set `GEMINI_API_KEY` as an environment variable.
4. Run: `streamlit run app.py`

## Important limitations

- The app supports both local video uploads and YouTube video URLs. YouTube downloads can still fail for videos whose formats are blocked or require YouTube authorization; use a video file you own or have permission to download.
- The stacked stream layout depends on Gemini correctly identifying distinct facecam and gameplay panels. It may not work for every overlay or moving-camera layout; use Auto 9:16 if detection fails.
- Subtitle timing and moment selection are AI-generated and should be reviewed before publishing.
- Large uploads need enough RAM, disk space, processing time, and Gemini API quota. Free quotas and hosting limits can apply. Gemini 503/UNAVAILABLE errors mean the model service is temporarily unavailable; the app now retries and tries alternate supported Flash models, but cannot override a Google-side outage or exhausted project quota.
