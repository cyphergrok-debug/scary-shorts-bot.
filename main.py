import os
import re
import json
import asyncio
import subprocess
from pathlib import Path
from datetime import datetime, timedelta, timezone
from PIL import Image, ImageDraw, ImageFont
import edge_tts
from google import genai
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

API_KEY = os.environ["GEMINI_API_KEY"]
CLIENT_ID = os.environ["YOUTUBE_CLIENT_ID"]
CLIENT_SECRET = os.environ["YOUTUBE_CLIENT_SECRET"]
REFRESH_TOKEN = os.environ["YOUTUBE_REFRESH_TOKEN"]

OUT = Path("output")
OUT.mkdir(exist_ok=True)
client = genai.Client(api_key=API_KEY)


def make_story(number):
    prompt = f"""
Write one original, suspenseful 40-55 second horror story for YouTube Shorts.
Story number: {number}
Use a powerful opening hook, escalating suspense, and a creepy ending.
Keep it suitable for a general audience. No graphic gore.
Return ONLY valid JSON with these keys:
story (narration text), title (under 70 characters),
description (short description with relevant hashtags).
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash", contents=prompt
    )
    text = response.text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text).strip()
    data = json.loads(text)
    return data


def get_font(size):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def make_background(story, path):
    width, height = 1080, 1920
    img = Image.new("RGB", (width, height), (8, 8, 18))
    draw = ImageDraw.Draw(img)
    font = get_font(48)
    title_font = get_font(66)

    # Dark red atmospheric glow
    for y in range(height):
        shade = int(12 + 18 * y / height)
        draw.line((0, y, width, y), fill=(shade, 5, 12))

    draw.text((70, 100), "MIDNIGHT HORROR", font=get_font(36),
              fill=(220, 55, 65))
    title = story["title"]
    words = title.split()
    lines, line = [], ""
    for word in words:
        if draw.textlength(line + " " + word, font=title_font) > 900:
            lines.append(line)
            line = word
        else:
            line = (line + " " + word).strip()
    if line:
        lines.append(line)

    y = 260
    for line in lines[:4]:
        draw.text((70, y), line, font=title_font, fill=(255, 235, 235))
        y += 90

    narration = story["story"]
    words = narration.split()
    lines, line = [], ""
    for word in words:
        test = (line + " " + word).strip()
        if draw.textlength(test, font=font) > 920:
            lines.append(line)
            line = word
        else:
            line = test
    if line:
        lines.append(line)

    y += 100
    for line in lines:
        if y > 1740:
            break
        draw.text((70, y), line, font=font, fill=(225, 225, 235))
        y += 62

    img.save(path)


async def make_audio(text, path):
    voice = edge_tts.Communicate(
        text=text, voice="en-US-GuyNeural", rate="-5%"
    )
    await voice.save(str(path))


def render_video(image, audio, output):
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(image),
        "-i", str(audio), "-c:v", "libx264",
        "-tune", "stillimage", "-c:a", "aac",
        "-b:a", "128k", "-pix_fmt", "yuv420p",
        "-vf", "scale=1080:1920,format=yuv420p",
        "-shortest", "-movflags", "+faststart", str(output)
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def youtube_client():
    credentials = Credentials(
        token=None,
        refresh_token=REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.upload"],
    )
    credentials.refresh(Request())
    return build("youtube", "v3", credentials=credentials)


def upload_video(youtube, video, story, publish_time):
    body = {
        "snippet": {
            "title": story["title"][:100],
            "description": story["description"][:5000],
            "categoryId": "24",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt": publish_time,
            "selfDeclaredMadeForKids": False,
        },
    }
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=MediaFileUpload(
            str(video), mimetype="video/mp4", resumable=True
        ),
    )
    result = request.execute()
    print("Uploaded video ID:", result["id"])


def main():
    youtube = youtube_client()
    now = datetime.now(timezone.utc)
    # Schedule five uploads from tomorrow, three hours apart.
    first = (now + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )

    for i in range(5):
        print(f"Creating scary Short {i + 1}/5...")
        story = make_story(i + 1)
        image = OUT / f"background_{i}.png"
        audio = OUT / f"voice_{i}.mp3"
        video = OUT / f"short_{i}.mp4"

        make_background(story, image)
        asyncio.run(make_audio(story["story"], audio))
        render_video(image, audio, video)

        publish_time = (
            first + timedelta(hours=3 * i)
        ).isoformat().replace("+00:00", "Z")

        upload_video(youtube, video, story, publish_time)

    print("Finished creating and scheduling five Shorts.")


if __name__ == "__main__":
    main()
