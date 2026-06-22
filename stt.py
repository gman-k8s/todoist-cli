#!/usr/bin/env python3
import sys
import os

_dir = os.path.dirname(os.path.abspath(__file__))
_venv_py = os.path.join(_dir, ".venv", "bin", "python3")

if not os.path.exists(_venv_py):
    sys.exit("Error: .venv not found. Run ./setup-venv.sh to install dependencies.")

if os.path.realpath(sys.executable) != os.path.realpath(_venv_py):
    os.execv(_venv_py, [_venv_py] + sys.argv)

import argparse
from dotenv import load_dotenv
from google import genai

load_dotenv(os.path.join(_dir, ".env"))

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
if not GOOGLE_API_KEY:
    sys.exit("Error: GOOGLE_API_KEY not set in .env")

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash-lite")

_STT_PROMPT = (
    "Transcribe this audio exactly as spoken in the original language. "
    "Return ONLY the transcribed text. No quotes, no explanation, no formatting."
)


def transcribe(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    mime_map = {
        ".ogg": "audio/ogg",
        ".oga": "audio/ogg",
        ".wav": "audio/wav",
        ".mp3": "audio/mpeg",
        ".m4a": "audio/mp4",
        ".webm": "audio/webm",
        ".opus": "audio/ogg",
    }
    mime_type = mime_map.get(ext, "audio/ogg")

    with open(file_path, "rb") as f:
        audio_data = f.read()

    client = genai.Client(api_key=GOOGLE_API_KEY)
    audio_part = genai.types.Part.from_bytes(data=audio_data, mime_type=mime_type)
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=[_STT_PROMPT, audio_part],
    )
    return response.text.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Transcribe audio via Gemini.")
    parser.add_argument("file", help="Path to audio file")
    args = parser.parse_args()

    if not os.path.isfile(args.file):
        sys.exit(f"Error: file not found: {args.file}")

    print(transcribe(args.file))


if __name__ == "__main__":
    main()
