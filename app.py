import os
import requests
import sys
import time
from uuid import uuid4

from flask import Flask, request, send_from_directory, Response
import openai
from twilio.twiml.voice_response import VoiceResponse


# ENV variables
USE_NGROK = str(os.environ.get("USE_NGROK", "False")).lower()
WERKZEUG_RUN_MAIN = str(os.environ.get("WERKZEUG_RUN_MAIN", "False")).lower()
ELEVEN_LABS_KEY = os.environ["ELEVEN_LABS_KEY"]
ELEVEN_LABS_VOICE_ID = os.environ["ELEVEN_LABS_VOICE_ID"]
OPEN_AI_KEY = os.environ["OPEN_AI_KEY"]
TWILIO_ACT_SID = os.environ["TWILIO_ACT_SID"]
TWILIO_AUTH_KEY = os.environ["TWILIO_AUTH_KEY"]

# Set OpenAI Key
openai.api_key = OPEN_AI_KEY


# Setting up ngrok
# ------------------------------------------------------------------------------------------------
def init_webhooks(base_url):
    # Update inbound traffic via APIs to use the public-facing ngrok URL
    pass


def create_app():
    
    app = Flask(__name__)

    # Initialize our ngrok settings into Flask
    app.config.from_mapping(
        BASE_URL="http://localhost:5000",
        USE_NGROK=USE_NGROK == "true" and WERKZEUG_RUN_MAIN != "true"
    )

    print(app.config.get("ENV") == "development")
    print(app.config["USE_NGROK"])
    if app.config.get("ENV") == "development" and app.config["USE_NGROK"]:
        # pyngrok will only be installed, and should only ever be initialized, in a dev environment
        from pyngrok import ngrok

        # Get the dev server port (defaults to 5000 for Flask, can be overridden with `--port`
        # when starting the server
        port = sys.argv[sys.argv.index("--port") + 1] if "--port" in sys.argv else 5000

        # Open a ngrok tunnel to the dev server
        public_url = ngrok.connect(port).public_url
        print(f" * ngrok tunnel \"{public_url}\" -> \"http://127.0.0.1:{port}\"")

        # Update any base URLs or webhooks to use the public ngrok URL
        app.config["BASE_URL"] = public_url
        init_webhooks(public_url)

    return app


app = create_app()


# End points
# ------------------------------------------------------------------------------------------------
@app.route("/")
def index():
    return "<p>Hello, Welcome! This is Mike's AI bot</p>"


@app.route("/incoming_call", methods=["POST"])
def handle_call():
    response = VoiceResponse()
    intro = text_to_speech("Hey, whats up?")

    response.play(intro)
    response.record(
        action="/process_audio",
        recording_status_callback_event="completed",
        recording_format="mp3",
        timeout=1,
        play_beep=False,
    )

    return Response(str(response), 200, mimetype="application/xml")


@app.route("/process_audio", methods=["POST"])
def process_audio():
    recording_url = request.values.get("RecordingUrl")
    transcribed_text = transcribe_audio(recording_url)
    gpt3_response = get_gpt3_response(transcribed_text)
    tts_audio_url = text_to_speech(gpt3_response)

    response = VoiceResponse()
    response.play(tts_audio_url)
    response.record(
        action="/process_audio",
        recording_status_callback_event="completed",
        recording_format="mp3",
        timeout=1,
        play_beep=False,
    )

    return Response(str(response), 200, mimetype="application/xml")


@app.route("/audio/<path:file_name>")
def serve_audio(file_name):
    return send_from_directory("static/audio", file_name)


# Methods to deal with audio
# ------------------------------------------------------------------------------------------------
def transcribe_audio(recording_url):
    
    time.sleep(1)
    audio_response = requests.get(recording_url)
    audio_file_name = f"{str(uuid4())}.mp3"

    with open(audio_file_name, "wb") as audio_file:
        audio_file.write(audio_response.content)

    whisper_url = "https://api.openai.com/v1/audio/transcriptions"
    headers = {"Authorization": f"Bearer {OPEN_AI_KEY}"}

    with open(audio_file_name, "rb") as audio_file:
        files = {"file": audio_file}
        data = {"model": "whisper-1"}
        response = requests.post(whisper_url, headers=headers, data=data, files=files)

    os.remove(audio_file_name)

    if response.status_code == 200:
        transcribed_text = response.json()["text"]
        return transcribed_text
    
    else:
        print("Whisper API response:", response.json())
        raise Exception(f"Whisper ASR API request failed with status code: {response.status_code}")


def text_to_speech(text):
    api_url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_LABS_VOICE_ID}"

    headers = {
        "accept": "audio/mpeg",
        "xi-api-key": f"{ELEVEN_LABS_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"text": text, "voice_settings": {"stability": 0.75, "similarity_boost": 0.9}}
    response = requests.post(api_url, headers=headers, json=payload)

    if response.status_code == 200:
        file_name = f"tts_{hash(text)}.mp3"
        audio_directory = "static/audio"
        os.makedirs(audio_directory, exist_ok=True)
        audio_path = os.path.join(audio_directory, file_name)

        with open(audio_path, "wb") as f:
            f.write(response.content)

        tts_audio_url = f"/audio/{file_name}"
        return tts_audio_url

    else:
        print("Eleven Labs TTS API response:", response.json())
        raise Exception(
            f"Eleven Labs TTS API request failed with status code: {response.status_code}"
        )


# Methods to deal with GPT API
# ------------------------------------------------------------------------------------------------
def get_gpt3_response(transcribed_text):
    
    prompt = f"{transcribed_text}"
    personality = "You are a BMW enthusiast from Miami who absolutely loves the 4-series"

    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {
                "role": "user",
                "content": f"{personality} responding to the following prompt {prompt}",
            }
        ],
        max_tokens=50,
        stop=None,
        temperature=0.5,
    )

    if response.choices:
        gpt3_response = response.choices[0].message.content.strip()
        return gpt3_response

    else:
        raise Exception("GPT-3 API request failed.")
