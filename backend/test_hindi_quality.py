"""
Test Voice Agent Quality with Hindi Audio Samples
Uses existing audio files with various noise types and levels.

Tests:
- Clean audio vs noisy audio understanding
- Different noise types: traffic, mechanical, white, pink
- Different noise levels: 5, 10, 15 dB

Usage:
    python test_hindi_quality.py
"""

import os
import sys
import base64
import asyncio
import wave
import json
import subprocess
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional, Dict
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

SAMPLE_RATE = 24000

# Base path for audio files
AUDIO_BASE_PATH = os.path.join(os.path.dirname(__file__), '..', '..', 'all_denoised_output', '0_original_normalized')

# Noise types to test (blue-collar environment scenarios)
NOISE_TYPES = {
    'clean': 'No background noise',
    'traffic_noise': 'Road/vehicle noise (delivery drivers, outdoor workers)',
    'mechanical_noise': 'Factory/construction machinery',
    'white_noise': 'General ambient noise',
    'pink_noise': 'Low frequency rumble',
}

NOISE_LEVELS = [5, 10, 15]  # dB levels


@dataclass
class TestResult:
    sample_id: int
    noise_type: str
    noise_level: Optional[int]
    audio_file: str
    ai_response: str
    transcription: str
    response_length: int
    asked_to_repeat: bool
    mentioned_noise: bool
    latency_ms: float


async def test_audio_file(audio_file: str, sample_id: int, noise_type: str, noise_level: Optional[int] = None) -> Optional[TestResult]:
    """Test a single audio file with the voice agent"""
    
    from openai import AsyncOpenAI
    import time
    
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://abhis-mi8y4vxk-eastus2.cognitiveservices.azure.com")
    deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-realtime")
    api_key = os.getenv("AZURE_OPEN_API_KEY")
    
    if not api_key:
        print("Error: AZURE_OPEN_API_KEY not set")
        return None
    
    if not os.path.exists(audio_file):
        print(f"  File not found: {audio_file}")
        return None
    
    base_url = endpoint.replace("https://", "wss://").rstrip("/") + "/openai/v1"
    
    # Convert to PCM if needed
    temp_wav = f"temp_test_{sample_id}.wav"
    subprocess.run([
        'ffmpeg', '-y', '-i', audio_file,
        '-acodec', 'pcm_s16le', '-ar', str(SAMPLE_RATE), '-ac', '1',
        temp_wav
    ], capture_output=True)
    
    with wave.open(temp_wav, 'rb') as wav:
        audio_data = wav.readframes(wav.getnframes())
    
    os.remove(temp_wav)
    
    client = AsyncOpenAI(websocket_base_url=base_url, api_key=api_key)
    
    response_text = ""
    transcription = ""
    start_time = time.time()
    
    try:
        async with client.realtime.connect(model=deployment_name) as connection:
            # Configure session with our prompt
            await connection.session.update(session={
                "type": "realtime",
                "instructions": """You are a helpful assistant. 
                If you can't understand clearly due to noise, ask user to repeat.
                If there's background noise but you understand, briefly mention it.
                Keep responses short. Respond in Hindi if user speaks Hindi.""",
                "output_modalities": ["text"],
            })
            
            # Send audio in chunks
            chunk_size = 4800
            for i in range(0, len(audio_data), chunk_size):
                chunk = audio_data[i:i + chunk_size]
                audio_base64 = base64.b64encode(chunk).decode('utf-8')
                await connection.input_audio_buffer.append(audio=audio_base64)
                await asyncio.sleep(0.02)
            
            await connection.input_audio_buffer.commit()
            await connection.response.create()
            
            # Collect response
            async for event in connection:
                if event.type == "response.output_text.delta":
                    response_text += event.delta
                elif event.type == "conversation.item.input_audio_transcription.completed":
                    transcription = event.transcript if hasattr(event, 'transcript') else ""
                elif event.type == "response.done":
                    break
                elif event.type == "error":
                    print(f"  Error: {event.error.message}")
                    break
            
            latency = (time.time() - start_time) * 1000
            
    except Exception as e:
        print(f"  Connection error: {e}")
        return None
    
    # Analyze response
    response_lower = response_text.lower()
    
    repeat_phrases = ["repeat", "say again", "didn't hear", "couldn't hear",
                      "not clear", "dobara", "phir se", "clear nahi", "samajh nahi"]
    asked_to_repeat = any(p in response_lower for p in repeat_phrases)
    
    noise_phrases = ["noise", "noisy", "background", "shor", "awaaz"]
    mentioned_noise = any(p in response_lower for p in noise_phrases)
    
    return TestResult(
        sample_id=sample_id,
        noise_type=noise_type,
        noise_level=noise_level,
        audio_file=os.path.basename(audio_file),
        ai_response=response_text,
        transcription=transcription,
        response_length=len(response_text),
        asked_to_repeat=asked_to_repeat,
        mentioned_noise=mentioned_noise,
        latency_ms=latency,
    )


async def run_quality_tests():
    """Run comprehensive quality tests"""
    
    print("")
    print("=" * 70)
    print("  HINDI VOICE AGENT QUALITY TEST")
    print("  Testing with real noisy audio samples")
    print("=" * 70)
    print("")
    
    results: List[TestResult] = []
    
    # Test each sample
    for sample_id in range(1, 6):  # 5 samples
        print(f"\n{'='*50}")
        print(f"SAMPLE {sample_id}")
        print(f"{'='*50}")
        
        # Test clean version first
        clean_file = os.path.join(AUDIO_BASE_PATH, f'hindi_sample_{sample_id}_clean.wav')
        print(f"\nTesting: CLEAN")
        result = await test_audio_file(clean_file, sample_id, 'clean')
        if result:
            results.append(result)
            print(f"  Response: {result.ai_response[:80]}..." if len(result.ai_response) > 80 else f"  Response: {result.ai_response}")
            print(f"  Transcription: {result.transcription[:80]}..." if len(result.transcription) > 80 else f"  Transcription: {result.transcription}")
            print(f"  Latency: {result.latency_ms:.0f}ms")
        
        # Test with different noise types and levels
        for noise_type in ['traffic_noise', 'mechanical_noise']:  # Focus on blue-collar scenarios
            for noise_level in [10, 15]:  # Medium and high noise
                noisy_file = os.path.join(AUDIO_BASE_PATH, f'hindi_sample_{sample_id}_{noise_type}_{noise_level}.wav')
                
                print(f"\nTesting: {noise_type} @ {noise_level}dB")
                result = await test_audio_file(noisy_file, sample_id, noise_type, noise_level)
                if result:
                    results.append(result)
                    print(f"  Response: {result.ai_response[:60]}..." if len(result.ai_response) > 60 else f"  Response: {result.ai_response}")
                    print(f"  Asked to repeat: {'Yes' if result.asked_to_repeat else 'No'}")
                    print(f"  Mentioned noise: {'Yes' if result.mentioned_noise else 'No'}")
                    print(f"  Latency: {result.latency_ms:.0f}ms")
    
    # Generate summary
    print("")
    print("=" * 70)
    print("  SUMMARY REPORT")
    print("=" * 70)
    
    if results:
        # Group by noise type
        by_noise_type: Dict[str, List[TestResult]] = {}
        for r in results:
            key = f"{r.noise_type}_{r.noise_level}" if r.noise_level else r.noise_type
            if key not in by_noise_type:
                by_noise_type[key] = []
            by_noise_type[key].append(r)
        
        print(f"\n{'Condition':<30} {'Tests':<8} {'Avg Latency':<12} {'Asked Repeat':<14} {'Noted Noise'}")
        print("-" * 80)
        
        for condition, condition_results in sorted(by_noise_type.items()):
            count = len(condition_results)
            avg_latency = sum(r.latency_ms for r in condition_results) / count
            asked_repeat_pct = sum(1 for r in condition_results if r.asked_to_repeat) / count * 100
            mentioned_noise_pct = sum(1 for r in condition_results if r.mentioned_noise) / count * 100
            
            print(f"{condition:<30} {count:<8} {avg_latency:.0f}ms{'':<6} {asked_repeat_pct:.0f}%{'':<11} {mentioned_noise_pct:.0f}%")
        
        # Overall metrics
        total = len(results)
        clean_results = [r for r in results if r.noise_type == 'clean']
        noisy_results = [r for r in results if r.noise_type != 'clean']
        
        print(f"\n{'='*50}")
        print("QUALITY METRICS")
        print(f"{'='*50}")
        
        if clean_results:
            avg_clean_response = sum(r.response_length for r in clean_results) / len(clean_results)
            print(f"Clean Audio - Avg Response Length: {avg_clean_response:.0f} chars")
        
        if noisy_results:
            asked_repeat_noisy = sum(1 for r in noisy_results if r.asked_to_repeat) / len(noisy_results) * 100
            mentioned_noise_noisy = sum(1 for r in noisy_results if r.mentioned_noise) / len(noisy_results) * 100
            avg_noisy_latency = sum(r.latency_ms for r in noisy_results) / len(noisy_results)
            
            print(f"Noisy Audio - Asked to Repeat: {asked_repeat_noisy:.1f}%")
            print(f"Noisy Audio - Mentioned Noise: {mentioned_noise_noisy:.1f}%")
            print(f"Noisy Audio - Avg Latency: {avg_noisy_latency:.0f}ms")
        
        # Quality assessment
        print(f"\n{'='*50}")
        print("ASSESSMENT")
        print(f"{'='*50}")
        
        # Good quality if model understands most queries (doesn't ask to repeat too often)
        # But should ask when truly unclear
        high_noise_results = [r for r in results if r.noise_level and r.noise_level >= 15]
        if high_noise_results:
            high_noise_repeat = sum(1 for r in high_noise_results if r.asked_to_repeat) / len(high_noise_results) * 100
            if high_noise_repeat < 30:
                print(f"Model handles high noise well - only asked to repeat {high_noise_repeat:.0f}% of time")
            else:
                print(f"Model struggles with high noise - asked to repeat {high_noise_repeat:.0f}% of time")
        
        # Save detailed results
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "total_tests": total,
            "results": [
                {
                    "sample_id": r.sample_id,
                    "noise_type": r.noise_type,
                    "noise_level": r.noise_level,
                    "audio_file": r.audio_file,
                    "ai_response": r.ai_response,
                    "transcription": r.transcription,
                    "response_length": r.response_length,
                    "asked_to_repeat": r.asked_to_repeat,
                    "mentioned_noise": r.mentioned_noise,
                    "latency_ms": r.latency_ms,
                }
                for r in results
            ]
        }
        
        results_file = f"hindi_quality_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results_data, f, indent=2, ensure_ascii=False)
        
        print(f"\nDetailed report saved: {results_file}")
    
    print("=" * 70)
    
    return results


if __name__ == "__main__":
    asyncio.run(run_quality_tests())

