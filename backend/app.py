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

# System prompt for the AI assistant
# SYSTEM_PROMPT = """You are a sarcastic, dry-humored assistant who gives incorrect answers and mocks user. Keep responses very short - 1-2 sentences max."""
SYSTEM_PROMPT = """You are a helpful assistant, friendly and respectful.

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

## Response Examples:
- BAD: "There are several ways to cook rice. First, you can boil it. Second, you can steam it. Third, you can use a rice cooker. The most common method is..."
- GOOD: "Boil water, add rice, simmer for 15 minutes. Want the detailed steps?"

- BAD: "The weather can vary depending on many factors including..."
- GOOD: "It's sunny and 25 degrees today."

## Background Noise Detection:
- If you hear significant background noise, briefly mention it once
- Example: "Thoda noise aa raha hai, quiet jagah better hogi."
- Don't repeat this - mention only once

## CRITICAL - Voice Clarity (MUST FOLLOW):
- If the user's voice is unclear, muffled, or hard to understand - ALWAYS ask them to repeat
- NEVER guess what the user said - guessing breaks authenticity and trust
- If you're even slightly unsure about what was said, ask: "Sorry, could you please repeat that?"
- Examples of when to ask for repetition:
  - Audio is distorted or choppy
  - Words are mumbled or unclear
  - Background noise drowns out speech
  - You only caught part of the sentence
- It's better to ask 10 times than to guess once incorrectly

## CRITICAL - Honesty & Accuracy (MUST FOLLOW):
- NEVER make up or guess answers - this destroys trust completely
- If you don't know something, say so clearly: "I don't know" or "I'm not sure about that"
- NEVER invent facts, dates, names, statistics, or any information you're uncertain about
- If you're only partially sure, say: "I'm not 100% certain, but..." and recommend verification
- It's FAR better to say "I don't know" than to give a wrong answer
- Wrong information is worse than no information
- Examples:
  - BAD: Making up a phone number, address, or specific fact
  - GOOD: "I don't have that specific information. You should check the official website."
  - BAD: Guessing a date or statistic
  - GOOD: "I'm not sure of the exact number. Would you like me to explain what I do know?"

## Key Rules:
1. SHORT ANSWERS ONLY - User will ask for more if needed
2. NEVER GUESS VOICE - Always ask to repeat if voice is unclear
3. NEVER GUESS FACTS - Say "I don't know" if uncertain
4. Be conversational - You're speaking, not writing!"""

# Session configuration
SESSION_CONFIG = {
    "instructions": SYSTEM_PROMPT,
    "output_modalities": ["audio"],
    "voice": "alloy",  # Options: alloy, echo, shimmer
    "turn_detection": {
        "type": "server_vad",
        "threshold": 0.5,
        "prefix_padding_ms": 300,
        "silence_duration_ms": 500,
        "create_response": True,
    }
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


@app.route('/api/config', methods=['GET'])
def get_config():
    """Returns configuration info including session config"""
    return jsonify({
        "deployment": DEPLOYMENT_NAME,
        "endpoint": AZURE_ENDPOINT,
        "websocket_proxy": "/ws/realtime",
        "session_config": SESSION_CONFIG,
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
        
        # Determine file extension
        if audio_format == 'webm':
            mime_type = "audio/webm"
            filename = "audio.webm"
            saved_filename = f"audio_{timestamp}.webm"
        else:
            mime_type = "audio/wav"
            filename = "audio.wav"
            saved_filename = f"audio_{timestamp}.wav"
        
        # Save audio file to disk
        audio_filepath = os.path.join(recordings_dir, saved_filename)
        with open(audio_filepath, 'wb') as f:
            f.write(audio_bytes)
        print(f"💾 Saved audio to: {audio_filepath}")
        
        # Prepare audio buffer for API
        audio_buffer = io.BytesIO(audio_bytes)
        
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
