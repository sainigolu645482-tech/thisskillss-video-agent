# ThisSkills AutoClips AI

This is a **long-video-to-Shorts clipping tool**, not an AI story/video generator. Upload a video you own or have permission to edit. Gemini selects the number of strong, self-contained moments (no fixed clip count; 8–60 seconds each). FFmpeg cuts the original footage and preserves its original audio.

## Features

- Upload MP4, MOV, MKV, or WEBM from phone or computer.
- Gemini finds engaging moments, natural start/end points, a short hook, and subtitle text.
- Normal layout: vertical 9:16 with the complete original frame visible over a blurred background, avoiding a hard center crop.
- Stream layout: optional facecam-above/gameplay-below stack, with an adjustable facecam share (40–70%). Gemini attempts to detect the two source regions.
- Optional burned-in subtitles, individual MP4 downloads, and one ZIP containing all Shorts.
- No generated scenes and no AI voiceover.

## Run locally

1. Install Python 3.10+ and FFmpeg. FFmpeg should include the `subtitles` filter (libass).
2. Install dependencies: `pip install -r requirements.txt`
3. Set `GEMINI_API_KEY` as an environment variable.
4. Run: `streamlit run app.py`
5. Open the Streamlit URL on your phone or computer and upload your video.

## Important limitations

- The current workflow accepts uploaded video files. It does **not** download arbitrary YouTube URLs; upload the original file you own or are authorized to use.
- The stacked stream layout depends on Gemini correctly identifying distinct facecam and gameplay panels. It may not work for every overlay or moving-camera layout; use Auto 9:16 if detection fails.
- Subtitle timing and moment selection are AI-generated and should be reviewed before publishing.
- Large uploads need enough RAM, disk space, processing time, and Gemini API quota. Free API quotas and hosting limits can apply.
- This repository change is the application code; a public hosted app still needs a hosting service and configured `GEMINI_API_KEY` secret.
