"""
Test Voice Agent Quality with Noisy Audio
Tests how well the AI handles various background noise scenarios
typical of blue-collar work environments.

Usage:
    python test_noisy_audio.py                    # Test with sample files
    python test_noisy_audio.py path/to/audio.mp3  # Test specific file
    python test_noisy_audio.py --generate-noisy   # Generate noisy test files
"""

import os
import sys
import base64
import asyncio
import wave
import subprocess
import json
from datetime import datetime
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

SAMPLE_RATE = 24000
CHANNELS = 1

# Test scenarios for blue-collar environments
NOISE_SCENARIOS = [
    {
        "name": "construction_site",
        "description": "Heavy machinery, drilling, hammering",
        "noise_type": "pink",  # Low frequency rumble
        "noise_level": 0.3,
    },
    {
        "name": "traffic_noise",
        "description": "Road traffic, honking, vehicles",
        "noise_type": "brown",  # Low frequency
        "noise_level": 0.25,
    },
    {
        "name": "factory_floor",
        "description": "Machine hum, conveyor belts",
        "noise_type": "white",
        "noise_level": 0.2,
    },
    {
        "name": "outdoor_wind",
        "description": "Wind noise, outdoor environment",
        "noise_type": "pink",
        "noise_level": 0.35,
    },
    {
        "name": "crowd_noise",
        "description": "Multiple people talking, market",
        "noise_type": "pink",
        "noise_level": 0.4,
    },
]


def generate_noisy_audio(input_file: str, output_dir: str = "test_audio"):
    """Generate test audio files with various noise levels using ffmpeg"""
    
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Generating noisy audio files from: {input_file}")
    print("=" * 50)
    
    for scenario in NOISE_SCENARIOS:
        output_file = os.path.join(output_dir, f"{scenario['name']}.wav")
        noise_level = scenario['noise_level']
        
        # Generate noise and mix with original audio using ffmpeg
        # This creates realistic background noise scenarios
        
        cmd = [
            'ffmpeg', '-y',
            '-i', input_file,
            '-filter_complex',
            f"anoisesrc=d=60:c=pink:a={noise_level}[noise];"
            f"[0:a][noise]amix=inputs=2:duration=first:weights=1 {noise_level},"
            f"aresample={SAMPLE_RATE},aformat=sample_fmts=s16:channel_layouts=mono",
            output_file
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            print(f"  Created: {scenario['name']}.wav ({scenario['description']})")
        except subprocess.CalledProcessError as e:
            print(f"  Failed: {scenario['name']} - {e.stderr.decode()[:100]}")
        except FileNotFoundError:
            print("  Error: ffmpeg not found. Install ffmpeg to generate noisy audio.")
            return
    
    print("")
    print(f"Test files created in: {output_dir}/")


async def test_audio_with_agent(audio_file: str, question: str = None):
    """Send audio to the realtime API and evaluate response"""
    
    from openai import AsyncOpenAI
    
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://abhis-mi8y4vxk-eastus2.cognitiveservices.azure.com")
    deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-realtime")
    api_key = os.getenv("AZURE_OPEN_API_KEY")
    
    if not api_key:
        print("Error: AZURE_OPEN_API_KEY not set")
        return None
    
    base_url = endpoint.replace("https://", "wss://").rstrip("/") + "/openai/v1"
    
    # Load audio file
    if not os.path.exists(audio_file):
        print(f"File not found: {audio_file}")
        return None
    
    # Convert to PCM if needed
    if audio_file.endswith('.mp3'):
        temp_wav = "temp_test_pcm.wav"
        subprocess.run([
            'ffmpeg', '-y', '-i', audio_file,
            '-acodec', 'pcm_s16le', '-ar', str(SAMPLE_RATE), '-ac', '1',
            temp_wav
        ], capture_output=True)
        audio_file = temp_wav
    
    with wave.open(audio_file, 'rb') as wav:
        audio_data = wav.readframes(wav.getnframes())
    
    print(f"Testing: {os.path.basename(audio_file)}")
    print(f"Audio length: {len(audio_data) / SAMPLE_RATE / 2:.1f} seconds")
    
    client = AsyncOpenAI(websocket_base_url=base_url, api_key=api_key)
    
    result = {
        "file": audio_file,
        "response_text": "",
        "asked_to_repeat": False,
        "mentioned_noise": False,
        "understood_query": False,
    }
    
    try:
        async with client.realtime.connect(model=deployment_name) as connection:
            # Configure session
            await connection.session.update(session={
                "type": "realtime",
                "instructions": """You are a helpful assistant. 
                If you can't understand clearly due to noise, ask user to repeat.
                If there's background noise but you understand, briefly mention it.
                Keep responses short.""",
                "output_modalities": ["text"],
            })
            
            # Send audio in chunks
            chunk_size = 4800  # 100ms chunks
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                audio_base64 = base64.b64encode(chunk).decode('utf-8')
                await connection.input_audio_buffer.append(audio=audio_base64)
                await asyncio.sleep(0.05)
            
            # Commit and request response
            await connection.input_audio_buffer.commit()
            await connection.response.create()
            
            # Collect response
            async for event in connection:
                if event.type == "response.output_text.delta":
                    result["response_text"] += event.delta
                elif event.type == "response.done":
                    break
                elif event.type == "error":
                    print(f"Error: {event.error.message}")
                    break
            
            # Analyze response
            response_lower = result["response_text"].lower()
            
            # Check if AI asked to repeat
            repeat_phrases = [
                "repeat", "say again", "didn't hear", "couldn't hear",
                "not clear", "dobara", "phir se", "clear nahi"
            ]
            result["asked_to_repeat"] = any(p in response_lower for p in repeat_phrases)
            
            # Check if AI mentioned noise
            noise_phrases = ["noise", "noisy", "loud", "background", "shor"]
            result["mentioned_noise"] = any(p in response_lower for p in noise_phrases)
            
            # Check if AI understood (gave a substantive response)
            result["understood_query"] = len(result["response_text"]) > 20 and not result["asked_to_repeat"]
            
    except Exception as e:
        print(f"Connection error: {e}")
        result["error"] = str(e)
    
    return result


async def run_quality_tests(audio_dir: str = "test_audio"):
    """Run quality tests on all audio files in directory"""
    
    print("")
    print("=" * 60)
    print("  VOICE AGENT QUALITY TEST - Noisy Audio Scenarios")
    print("=" * 60)
    print("")
    
    results = []
    
    # Test each scenario
    for scenario in NOISE_SCENARIOS:
        audio_file = os.path.join(audio_dir, f"{scenario['name']}.wav")
        
        if not os.path.exists(audio_file):
            print(f"Skipping {scenario['name']}: file not found")
            continue
        
        print(f"\nTesting: {scenario['name']}")
        print(f"  Scenario: {scenario['description']}")
        print(f"  Noise Level: {scenario['noise_level'] * 100:.0f}%")
        
        result = await test_audio_with_agent(audio_file)
        if result:
            result["scenario"] = scenario
            results.append(result)
            
            print(f"  Response: {result['response_text'][:100]}...")
            print(f"  Asked to repeat: {'Yes' if result['asked_to_repeat'] else 'No'}")
            print(f"  Mentioned noise: {'Yes' if result['mentioned_noise'] else 'No'}")
            print(f"  Understood: {'Yes' if result['understood_query'] else 'No'}")
    
    # Summary
    print("")
    print("=" * 60)
    print("  SUMMARY")
    print("=" * 60)
    
    if results:
        total = len(results)
        asked_repeat = sum(1 for r in results if r.get("asked_to_repeat"))
        mentioned_noise = sum(1 for r in results if r.get("mentioned_noise"))
        understood = sum(1 for r in results if r.get("understood_query"))
        
        print(f"  Total Tests:        {total}")
        print(f"  Asked to Repeat:    {asked_repeat}/{total} ({asked_repeat/total*100:.0f}%)")
        print(f"  Mentioned Noise:    {mentioned_noise}/{total} ({mentioned_noise/total*100:.0f}%)")
        print(f"  Understood Query:   {understood}/{total} ({understood/total*100:.0f}%)")
        
        # Quality score
        # Good: Ask to repeat when noise is high, understand when noise is low
        quality_score = 0
        for r in results:
            noise_level = r["scenario"]["noise_level"]
            if noise_level >= 0.3:  # High noise
                if r["asked_to_repeat"] or r["mentioned_noise"]:
                    quality_score += 1
            else:  # Low noise
                if r["understood_query"]:
                    quality_score += 1
        
        print(f"  Quality Score:      {quality_score}/{total} ({quality_score/total*100:.0f}%)")
    
    # Save results
    results_file = f"test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {results_file}")
    
    return results


def main():
    if len(sys.argv) > 1:
        if sys.argv[1] == '--generate-noisy':
            # Generate noisy test files from a clean audio
            if len(sys.argv) > 2:
                input_file = sys.argv[2]
            else:
                input_file = "../../sample_voice_with_bg_noise.mp3"
            generate_noisy_audio(input_file)
        else:
            # Test specific file
            asyncio.run(test_audio_with_agent(sys.argv[1]))
    else:
        # Run full quality test suite
        asyncio.run(run_quality_tests())


if __name__ == "__main__":
    main()

