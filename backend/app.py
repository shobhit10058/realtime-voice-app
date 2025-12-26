"""
Flask Backend for GPT Realtime Voice Application
Acts as a WebSocket proxy since browsers can't send auth headers.
Includes latency tracking and logging.
Serves React frontend in production.
"""
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS
from flask_sock import Sock
import os
import sys
import json
import asyncio
import websockets
import threading
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

# Check if we're serving built React frontend
FRONTEND_BUILD_DIR = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'build')
HAS_FRONTEND_BUILD = os.path.exists(FRONTEND_BUILD_DIR)

app = Flask(__name__, static_folder=FRONTEND_BUILD_DIR if HAS_FRONTEND_BUILD else None)
CORS(app)
sock = Sock(app)

# Azure OpenAI Configuration
AZURE_RESOURCE = os.getenv('AZURE_RESOURCE', 'abhis-mi8y4vxk-eastus2')
AZURE_API_KEY = os.getenv('AZURE_OPEN_API_KEY')
DEPLOYMENT_NAME = os.getenv('DEPLOYMENT_NAME', 'gpt-realtime')

# Sarvam AI Configuration
SARVAM_API_KEY = os.getenv('SARVAM_API_KEY')
SARVAM_API_URL = "https://api.sarvam.ai/speech-to-text"

# WebSocket URLs
AZURE_ENDPOINT = f"https://{AZURE_RESOURCE}.cognitiveservices.azure.com"
WS_URL = f"wss://{AZURE_RESOURCE}.cognitiveservices.azure.com/openai/v1/realtime?model={DEPLOYMENT_NAME}"

# ============================================================================
# BOT CONFIGURATIONS
# ============================================================================

# Support Bot - User speaks first, general assistance
# SUPPORT_BOT_PROMPT = """SYSTEM_PROMPT = """You are a very busy person who answers in 1-2 sentences only. If you do not hear clear sound or there is noise in background. Tell the user in their language or prefer hindi if language not clear to move to quiet place always."""
SUPPORT_BOT_PROMPT = """You are a helpful support assistant, friendly and respectful.

## CRITICAL - Response Length:
- Keep responses SHORT and TO THE POINT
- Maximum 1-2 sentences for simple questions
- Maximum 2-3 sentences for complex topics
- NEVER give long explanations unless explicitly asked
- User will ask "tell me more" or "explain further" if they want details
- Avoid lists, bullet points, or multiple examples - just give ONE clear answer

## Your Personality:
- Warm, conversational, and natural
- Concise - get to the point quickly
- Use simple, clear language

## Language:
- Detect the user's language and respond in the same language
- If user speaks Hindi/Hinglish, respond in Hindi/Hinglish
- If user speaks English, respond in English
- If the language is unclear, DEFAULT TO HINDI

## CRITICAL - Voice Clarity:
- If the user's voice is unclear, ALWAYS ask them to repeat
- NEVER guess what the user said
- It's better to ask 10 times than to guess once incorrectly

## CRITICAL - Honesty:
- NEVER make up or guess answers
- If you don't know something, say "I don't know"
- Wrong information is worse than no information

## Key Rules:
1. SHORT ANSWERS ONLY
2. NEVER GUESS VOICE - Always ask to repeat if unclear
3. NEVER GUESS FACTS - Say "I don't know" if uncertain
4. Be conversational - You're speaking, not writing!
5. When interrupted, briefly repeat what was missed
"""

# Hiring Bot - Bot speaks first, structured interview
HIRING_BOT_PROMPT = """You are a professional HR interviewer conducting a phone screening for skilled trade positions.

## YOUR ROLE:
You are interviewing candidates for the following positions:
- Plumber (Plumbing technician)
- Tailor (Darzi/Fashion tailor)
- Barber (Hair stylist/Naai)
- Electrician (Bijli mistri)
- Carpenter (Badhai/Furniture maker)

## INTERVIEW STRUCTURE - FOLLOW THIS EXACTLY:

You MUST ask these questions ONE BY ONE in order. DO NOT proceed to the next question until you get a clear answer.

### Question 1: Name
"Aapka shubh naam kya hai?" / "What is your name?"
- Wait for answer before proceeding

### Question 2: Position
"Aap kis position ke liye apply kar rahe hain - Plumber, Tailor, Barber, Electrician, ya Carpenter?"
- Wait for answer before proceeding

### Question 3: Experience
"Aapko is field mein kitne saal ka experience hai?"
- Wait for answer before proceeding

### Question 4: Current Location
"Aap abhi kahan rehte hain? Kis city mein?"
- Wait for answer before proceeding

### Question 5: Availability
"Aap kab se kaam shuru kar sakte hain?"
- Wait for answer before proceeding

### Question 6: Salary Expectation
"Aapki salary expectation kya hai? Monthly kitna chahiye?"
- Wait for answer before proceeding

### Question 7: Tools/Skills
Based on their position, ask relevant question:
- Plumber: "Aapko pipe fitting, leak repair, aur bathroom installation aata hai?"
- Tailor: "Aap kis type ki stitching mein expert hain - ladies, gents, ya dono?"
- Barber: "Aap haircut ke alawa shaving, facial, massage bhi karte hain?"
- Electrician: "Aapko wiring, switch board, aur AC installation aata hai?"
- Carpenter: "Aap furniture banate hain ya sirf repair karte hain?"

### Question 8: References
"Kya aap 2 references de sakte hain jo aapke kaam ki guarantee de sakein?"

## AFTER ALL QUESTIONS:
Thank them: "Bahut dhanyavaad! Aapki application submit ho gayi hai. Hum aapko 2-3 din mein call karenge."

## CRITICAL RULES:
1. Ask ONE question at a time - NEVER ask multiple questions together
2. WAIT for answer before asking next question
3. If answer is unclear, ask to repeat: "Sorry, zara dobara boliye?"
4. If they give incomplete answer, ask follow-up: "Aur kuch detail de sakte hain?"
5. Keep track of which questions are answered
6. Be warm and encouraging: "Bahut accha!", "Theek hai!"
7. Speak in Hindi/Hinglish primarily
8. Keep your responses SHORT - this is a phone call, not an essay
9. If they go off-topic, gently redirect: "Haan samjha, ab mujhe ye batayiye..."

## LANGUAGE:
- Primary: Hindi/Hinglish
- If candidate speaks English, respond in English
- Be natural and conversational

## GREETING (First message):
Start with: "Namaste! Main [Company] se bol raha hoon. Yeh ek hiring interview hai skilled workers ke liye. Kya aap abhi baat kar sakte hain?"
"""

# Common VAD and interruption settings
COMMON_VAD_CONFIG = {
    "type": "server_vad",
    "threshold": 0.95,
    "prefix_padding_ms": 600,
    "silence_duration_ms": 900,
    "create_response": True,
}

COMMON_INTERRUPTION_CONFIG = {
    "min_speech_duration_ms": 400,
    "debounce_ms": 300,
    "require_sustained_speech": True,
}

# Bot configurations dictionary
BOT_CONFIGS = {
    "support": {
        "name": "Support Bot",
        "description": "General support assistant - You speak first",
        "instructions": SUPPORT_BOT_PROMPT,
        "voice": "cedar",
        "bot_speaks_first": False,
        "greeting": None,
        "turn_detection": COMMON_VAD_CONFIG,
        "interruption_config": COMMON_INTERRUPTION_CONFIG,
    },
    "hiring": {
        "name": "Hiring Bot",
        "description": "HR interviewer for skilled trades - Bot speaks first",
        "instructions": HIRING_BOT_PROMPT,
        "voice": "cedar",
        "bot_speaks_first": True,
        "greeting": {
            "enabled": True,
            "prompt": "[Start the interview. Greet the candidate warmly and ask if they can talk now. Keep it brief - 1-2 sentences in Hindi/Hinglish.]",
            "delay_ms": 800,
        },
        "turn_detection": COMMON_VAD_CONFIG,
        "interruption_config": COMMON_INTERRUPTION_CONFIG,
    },
}

# Default bot type
DEFAULT_BOT = "support"

def get_session_config(bot_type=None):
    """Get session configuration for a specific bot type"""
    if bot_type is None or bot_type not in BOT_CONFIGS:
        bot_type = DEFAULT_BOT
    
    bot = BOT_CONFIGS[bot_type]
    return {
        "bot_type": bot_type,
        "bot_name": bot["name"],
        "bot_description": bot["description"],
        "instructions": bot["instructions"],
        "output_modalities": ["audio"],
        "voice": bot["voice"],
        "bot_speaks_first": bot["bot_speaks_first"],
        "greeting": bot.get("greeting"),
        "turn_detection": bot["turn_detection"],
        "interruption_config": bot["interruption_config"],
    }

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(__file__), 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

# Create latency logger
latency_logger = logging.getLogger('latency')
latency_logger.setLevel(logging.INFO)

# File handler for latency logs
log_file = os.path.join(LOG_DIR, f'latency_{datetime.now().strftime("%Y%m%d")}.log')
file_handler = logging.FileHandler(log_file, encoding='utf-8')
file_handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
latency_logger.addHandler(file_handler)

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
latency_logger.addHandler(console_handler)


class LatencyTracker:
    """Tracks various latency metrics for GPT Realtime API"""
    
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.connection_start = None
        self.connection_established = None
        self.speech_detected_at = None
        self.speech_ended_at = None
        self.response_created_at = None
        self.first_audio_at = None
        self.first_text_at = None
        self.response_done_at = None
        self.audio_chunks_received = 0
        self.total_audio_bytes = 0
        self.request_count = 0
        
    def log_connection_start(self):
        self.connection_start = time.time()
        latency_logger.info(f"[{self.session_id}] CONNECTION_START")
        
    def log_connection_established(self):
        self.connection_established = time.time()
        if self.connection_start:
            latency_ms = (self.connection_established - self.connection_start) * 1000
            latency_logger.info(f"[{self.session_id}] CONNECTION_ESTABLISHED | latency={latency_ms:.2f}ms")
        
    def log_speech_detected(self):
        self.speech_detected_at = time.time()
        self.request_count += 1
        latency_logger.info(f"[{self.session_id}] SPEECH_DETECTED | request_num={self.request_count}")
        
    def log_speech_ended(self):
        self.speech_ended_at = time.time()
        if self.speech_detected_at:
            speech_duration = (self.speech_ended_at - self.speech_detected_at) * 1000
            latency_logger.info(f"[{self.session_id}] SPEECH_ENDED | speech_duration={speech_duration:.2f}ms")
    
    def log_response_created(self):
        self.response_created_at = time.time()
        self.first_audio_at = None
        self.first_text_at = None
        self.audio_chunks_received = 0
        self.total_audio_bytes = 0
        if self.speech_ended_at:
            processing_latency = (self.response_created_at - self.speech_ended_at) * 1000
            latency_logger.info(f"[{self.session_id}] RESPONSE_CREATED | processing_latency={processing_latency:.2f}ms")
            
    def log_first_audio(self, chunk_size: int = 0):
        if self.first_audio_at is None:
            self.first_audio_at = time.time()
            if self.speech_ended_at:
                ttfa = (self.first_audio_at - self.speech_ended_at) * 1000
                latency_logger.info(f"[{self.session_id}] FIRST_AUDIO | time_to_first_audio={ttfa:.2f}ms")
        self.audio_chunks_received += 1
        self.total_audio_bytes += chunk_size
        
    def log_first_text(self, text: str = ""):
        if self.first_text_at is None:
            self.first_text_at = time.time()
            if self.speech_ended_at:
                ttft = (self.first_text_at - self.speech_ended_at) * 1000
                latency_logger.info(f"[{self.session_id}] FIRST_TEXT | time_to_first_text={ttft:.2f}ms | preview={text[:50]}")
                
    def log_response_done(self):
        self.response_done_at = time.time()
        if self.speech_ended_at:
            total_latency = (self.response_done_at - self.speech_ended_at) * 1000
            e2e_latency = 0
            if self.speech_detected_at:
                e2e_latency = (self.response_done_at - self.speech_detected_at) * 1000
            
            latency_logger.info(
                f"[{self.session_id}] RESPONSE_DONE | "
                f"total_response_time={total_latency:.2f}ms | "
                f"end_to_end={e2e_latency:.2f}ms | "
                f"audio_chunks={self.audio_chunks_received} | "
                f"audio_bytes={self.total_audio_bytes}"
            )
            
    def log_error(self, error_msg: str):
        latency_logger.error(f"[{self.session_id}] ERROR | {error_msg}")
        
    def log_disconnect(self):
        if self.connection_established:
            session_duration = (time.time() - self.connection_established) * 1000
            latency_logger.info(
                f"[{self.session_id}] DISCONNECTED | "
                f"session_duration={session_duration:.2f}ms | "
                f"total_requests={self.request_count}"
            )


# Store active trackers
active_trackers = {}


@app.route('/api/bots', methods=['GET'])
def get_bots():
    """Returns list of available bots"""
    bots = []
    for bot_id, bot_config in BOT_CONFIGS.items():
        bots.append({
            "id": bot_id,
            "name": bot_config["name"],
            "description": bot_config["description"],
            "bot_speaks_first": bot_config["bot_speaks_first"],
        })
    return jsonify({"bots": bots, "default": DEFAULT_BOT})


@app.route('/api/config', methods=['GET'])
def get_config():
    """Returns configuration info including session config for a specific bot"""
    bot_type = request.args.get('bot', DEFAULT_BOT)
    session_config = get_session_config(bot_type)
    
    return jsonify({
        "deployment": DEPLOYMENT_NAME,
        "endpoint": AZURE_ENDPOINT,
        "websocket_proxy": "/ws/realtime",
        "session_config": session_config,
    })


@app.route('/api/latency-stats', methods=['GET'])
def get_latency_stats():
    """Returns recent latency statistics from log file"""
    try:
        stats = []
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-100:]  # Last 100 lines
                for line in lines:
                    if 'FIRST_AUDIO' in line or 'RESPONSE_DONE' in line:
                        stats.append(line.strip())
        return jsonify({"stats": stats, "log_file": log_file})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "healthy"})


@app.route('/api/sarvam/test', methods=['GET'])
def test_sarvam():
    """Test Sarvam API connectivity"""
    import requests
    
    if not SARVAM_API_KEY:
        return jsonify({"error": "SARVAM_API_KEY not configured", "success": False})
    
    # Just check if we can reach the API
    headers = {"api-subscription-key": SARVAM_API_KEY}
    
    try:
        # Try to access the API (will fail without audio but shows connectivity)
        response = requests.post(
            SARVAM_API_URL,
            headers=headers,
            data={"model": "saarika:v2", "language_code": "hi-IN"},
            timeout=10
        )
        return jsonify({
            "status_code": response.status_code,
            "response": response.text[:500] if response.text else "Empty response",
            "api_key_set": True,
            "endpoint": SARVAM_API_URL
        })
    except Exception as e:
        return jsonify({"error": str(e), "success": False})


@app.route('/api/sarvam/transcribe', methods=['POST'])
def sarvam_transcribe():
    """
    Transcribe audio using Sarvam AI Saarika 2.5 model.
    Accepts webm audio from MediaRecorder or PCM audio.
    Saves audio files and transcripts to sarvam_recordings folder.
    """
    import requests
    import base64
    import io
    import subprocess
    import tempfile
    
    # Create recordings folder if it doesn't exist
    recordings_dir = os.path.join(os.path.dirname(__file__), 'sarvam_recordings')
    os.makedirs(recordings_dir, exist_ok=True)
    
    try:
        if not SARVAM_API_KEY:
            return jsonify({"error": "SARVAM_API_KEY not configured"}), 500
        
        data = request.get_json()
        if not data or 'audio' not in data:
            return jsonify({"error": "No audio data provided"}), 400
        
        # Decode base64 audio
        audio_base64 = data['audio']
        audio_bytes = base64.b64decode(audio_base64)
        
        # Get format from request (webm from MediaRecorder, or pcm)
        audio_format = data.get('format', 'webm')
        
        # Get language from request or use auto-detect
        language_code = data.get('language_code', 'auto')
        # Map 'auto' to 'unknown' for Sarvam API
        if language_code == 'auto':
            language_code = 'unknown'
        
        # Generate timestamp for unique filenames
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        
        # Save original audio file to disk
        if audio_format == 'webm':
            saved_filename = f"audio_{timestamp}.webm"
        else:
            saved_filename = f"audio_{timestamp}.wav"
        
        audio_filepath = os.path.join(recordings_dir, saved_filename)
        with open(audio_filepath, 'wb') as f:
            f.write(audio_bytes)
        print(f"💾 Saved original audio to: {audio_filepath}")
        
        # Convert webm to wav for Sarvam API (webm not supported)
        if audio_format == 'webm':
            try:
                wav_filename = f"audio_{timestamp}.wav"
                wav_filepath = os.path.join(recordings_dir, wav_filename)
                
                # Run ffmpeg conversion
                result = subprocess.run([
                    'ffmpeg', '-y', '-i', audio_filepath,
                    '-ar', '16000', '-ac', '1', '-f', 'wav', wav_filepath
                ], capture_output=True, timeout=30)
                
                if result.returncode == 0 and os.path.exists(wav_filepath):
                    with open(wav_filepath, 'rb') as f:
                        audio_buffer = io.BytesIO(f.read())
                    mime_type = "audio/wav"
                    filename = "audio.wav"
                    print(f"✅ Converted to WAV: {wav_filepath}, size={audio_buffer.getbuffer().nbytes} bytes")
                else:
                    print(f"⚠️ ffmpeg conversion failed: {result.stderr.decode()}")
                    audio_buffer = io.BytesIO(audio_bytes)
                    mime_type = "audio/webm"
                    filename = "audio.webm"
            except Exception as e:
                print(f"⚠️ ffmpeg error: {e}, using webm directly")
                audio_buffer = io.BytesIO(audio_bytes)
                mime_type = "audio/webm"
                filename = "audio.webm"
        else:
            audio_buffer = io.BytesIO(audio_bytes)
            mime_type = "audio/wav"
            filename = "audio.wav"
        
        # Call Sarvam AI API
        headers = {
            "api-subscription-key": SARVAM_API_KEY
        }
        
        files = {
            "file": (filename, audio_buffer, mime_type)
        }
        
        form_data = {
            "model": "saarika:v2.5",
            "language_code": language_code
        }
        
        # Ensure buffer is at the beginning before sending
        audio_buffer.seek(0)
        print(f"📤 Sending to Sarvam API: mime={mime_type}, language={language_code}, size={len(audio_bytes)} bytes")
        
        response = requests.post(
            SARVAM_API_URL,
            headers=headers,
            files=files,
            data=form_data,
            timeout=30
        )
        
        print(f"📥 Sarvam API response: {response.status_code}")
        
        transcript = ''
        language_detected = language_code
        error_msg = None
        
        if response.status_code == 200:
            result = response.json()
            print(f"📋 Sarvam full response: {result}")
            
            # Try different field names that Sarvam API might use
            transcript = result.get('transcript') or result.get('text') or result.get('transcription') or ''
            language_detected = result.get('language_code') or result.get('language') or language_code
            
            print(f"✅ Sarvam transcript: {transcript[:100] if transcript else '(empty)'}...")
        else:
            error_msg = f"Sarvam API error: {response.status_code} - {response.text}"
            print(f"❌ {error_msg}")
        
        # Save transcript to file (same name as audio but .txt)
        transcript_filename = saved_filename.rsplit('.', 1)[0] + '_transcript.txt'
        transcript_filepath = os.path.join(recordings_dir, transcript_filename)
        with open(transcript_filepath, 'w', encoding='utf-8') as f:
            f.write(f"Audio File: {saved_filename}\n")
            f.write(f"Timestamp: {timestamp}\n")
            f.write(f"Language: {language_detected}\n")
            f.write(f"Audio Size: {len(audio_bytes)} bytes\n")
            f.write(f"API Status: {response.status_code}\n")
            f.write("-" * 50 + "\n")
            if transcript:
                f.write(f"Transcript:\n{transcript}\n")
            elif error_msg:
                f.write(f"Error:\n{error_msg}\n")
            else:
                f.write("Transcript: (empty - no speech detected)\n")
        print(f"📝 Saved transcript to: {transcript_filepath}")
        
        if response.status_code == 200:
            return jsonify({
                "transcript": transcript,
                "language": language_detected,
                "success": True,
                "audio_file": saved_filename,
                "transcript_file": transcript_filename
            })
        else:
            return jsonify({"error": error_msg, "success": False}), response.status_code
            
    except Exception as e:
        error_msg = f"Sarvam transcription error: {str(e)}"
        print(f"❌ {error_msg}")
        return jsonify({"error": error_msg, "success": False}), 500


# Serve React frontend (for production/Replit deployment)
if HAS_FRONTEND_BUILD:
    @app.route('/')
    def serve_index():
        return send_from_directory(FRONTEND_BUILD_DIR, 'index.html')
    
    @app.route('/<path:path>')
    def serve_static(path):
        # Try to serve the file, fallback to index.html for SPA routing
        if os.path.exists(os.path.join(FRONTEND_BUILD_DIR, path)):
            return send_from_directory(FRONTEND_BUILD_DIR, path)
        return send_from_directory(FRONTEND_BUILD_DIR, 'index.html')


@sock.route('/ws/realtime')
def realtime_proxy(ws):
    """
    WebSocket proxy to Azure OpenAI Realtime API.
    Browser connects here, we forward to Azure with proper auth.
    """
    session_id = f"session_{int(time.time() * 1000)}"
    tracker = LatencyTracker(session_id)
    active_trackers[session_id] = tracker
    
    print(f"🔗 Client connected: {session_id}")
    tracker.log_connection_start()
    
    async def run_proxy():
        azure_ws_url = WS_URL
        headers = {"api-key": AZURE_API_KEY}
        
        print(f"🔗 Connecting to Azure: {azure_ws_url}")
        
        try:
            async with websockets.connect(
                azure_ws_url,
                additional_headers=headers,
                subprotocols=["realtime", "openai-beta.realtime-v1"]
            ) as azure_ws:
                tracker.log_connection_established()
                print(f"✅ Connected to Azure OpenAI!")
                
                async def forward_to_azure():
                    """Forward messages from browser to Azure"""
                    try:
                        while True:
                            try:
                                message = ws.receive(timeout=0.1)
                                if message:
                                    # Track outgoing messages
                                    try:
                                        data = json.loads(message)
                                        if data.get('type') == 'input_audio_buffer.commit':
                                            # Audio buffer committed, response expected soon
                                            pass
                                    except:
                                        pass
                                    await azure_ws.send(message)
                            except Exception:
                                await asyncio.sleep(0.01)
                    except Exception as e:
                        print(f"Forward to Azure error: {e}")
                
                async def forward_to_browser():
                    """Forward messages from Azure to browser with latency tracking"""
                    try:
                        async for message in azure_ws:
                            try:
                                # Parse and track events
                                data = json.loads(message)
                                event_type = data.get('type', '')
                                
                                # Debug: Log all event types received from Azure
                                print(f"📨 Azure event: {event_type}")
                                
                                # Track different event types
                                if event_type == 'input_audio_buffer.speech_started':
                                    tracker.log_speech_detected()
                                    
                                elif event_type == 'input_audio_buffer.speech_stopped':
                                    tracker.log_speech_ended()
                                    
                                elif event_type == 'response.created':
                                    tracker.log_response_created()
                                    
                                elif event_type == 'response.output_audio.delta':
                                    delta = data.get('delta', '')
                                    chunk_size = len(delta) if delta else 0
                                    tracker.log_first_audio(chunk_size)
                                    
                                elif event_type == 'response.output_audio_transcript.delta':
                                    delta = data.get('delta', '')
                                    tracker.log_first_text(delta)
                                    
                                elif event_type == 'response.done':
                                    tracker.log_response_done()
                                    
                                elif event_type == 'error':
                                    error_msg = data.get('error', {}).get('message', 'Unknown error')
                                    tracker.log_error(error_msg)
                                    print(f"❌ Azure ERROR: {error_msg}")
                                    print(f"   Full error: {json.dumps(data, indent=2)}")
                                    
                            except json.JSONDecodeError:
                                pass
                            
                            try:
                                ws.send(message)
                            except Exception as e:
                                print(f"Send to browser error: {e}")
                                break
                    except Exception as e:
                        print(f"Forward to browser error: {e}")
                
                await asyncio.gather(
                    forward_to_azure(),
                    forward_to_browser(),
                    return_exceptions=True
                )
                
        except Exception as e:
            tracker.log_error(str(e))
            print(f"❌ Azure connection error: {e}")
            try:
                ws.send(json.dumps({
                    "type": "error",
                    "error": {"message": str(e)}
                }))
            except:
                pass
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_proxy())
    finally:
        loop.close()
    
    tracker.log_disconnect()
    del active_trackers[session_id]
    print(f"🔌 Client disconnected: {session_id}")


if __name__ == '__main__':
    # Get port from environment (Replit sets this)
    port = int(os.environ.get('PORT', 5000))
    
    print("")
    print("🚀 Realtime Voice Backend (WebSocket Proxy)")
    print("=" * 50)
    print(f"   Resource:    {AZURE_RESOURCE}")
    print(f"   Deployment:  {DEPLOYMENT_NAME}")
    print(f"   Azure WS:    {WS_URL}")
    print(f"   Azure Key:   {'✅ Set' if AZURE_API_KEY else '❌ Not set'}")
    print(f"   Sarvam Key:  {'✅ Set' if SARVAM_API_KEY else '❌ Not set'}")
    print(f"   Log File:    {log_file}")
    print(f"   Frontend:    {'✅ Serving built React app' if HAS_FRONTEND_BUILD else '❌ Not found (run npm build)'}")
    print(f"   Port:        {port}")
    print("=" * 50)
    print("")
    print("📡 Endpoints:")
    print("   GET  /api/config           - Get configuration")
    print("   GET  /api/latency-stats    - Get latency statistics")
    print("   POST /api/sarvam/transcribe - Sarvam AI transcription")
    print("   WS   /ws/realtime          - WebSocket proxy to Azure")
    if HAS_FRONTEND_BUILD:
        print("   GET  /                  - React frontend")
    print("")
    print("📊 Latency Metrics Tracked:")
    print("   - Connection time")
    print("   - Time to first audio (TTFA)")
    print("   - Time to first text (TTFT)")
    print("   - End-to-end latency")
    print("   - Response duration")
    print("")
    
    # Use production server if not in debug mode
    debug_mode = os.environ.get('DEBUG', 'true').lower() == 'true'
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
