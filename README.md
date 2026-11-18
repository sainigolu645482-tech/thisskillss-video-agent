# ThisSkills AutoClips AI

Upload a video you own or have permission to edit. Gemini analyzes the full video and selects a variable number of self-contained engaging moments (maximum 60 seconds each). FFmpeg exports each selection as a vertical 9:16 MP4.

## Run locally

1. Install Python 3.10+ and FFmpeg.
2. Install dependencies: `pip install -r requirements.txt`
3. Set your Gemini API key as an environment variable named `GEMINI_API_KEY`.
4. Run: `streamlit run app.py`
5. Open the Streamlit URL on your phone or computer and upload an MP4/MOV/MKV/WEBM video.

## Notes

- The upload workflow does not download videos from YouTube. Upload the original video file that you own or are authorized to use.
- Gemini chooses the number of clips; there is no fixed clip count. Clips are capped at 60 seconds and invalid timestamps are discarded.
- FFmpeg must be installed on the machine running the app.
- Large videos need sufficient memory, disk space, processing time, and Gemini API quota. Free quotas and hosting limits may apply.
- Current first milestone exports vertical clips. Burned-in subtitles, progress tracking, and hosted mobile-friendly deployment are follow-up improvements.
