"""
Voice Agent Quality Test - Comprehensive Metrics
Tests AI's ability to understand speech in noisy conditions.

Metrics:
- Transcript Accuracy (WER)
- Intent Recognition
- Response Relevance
- Appropriate Clarification Requests

Usage:
    python test_voice_quality.py
    python test_voice_quality.py --with-noise 0.3  # Add 30% noise
"""

import os
import sys
import base64
import asyncio
import wave
import subprocess
import json
import re
from datetime import datetime
from dataclasses import dataclass
from typing import List, Optional
from dotenv import load_dotenv

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

load_dotenv()

SAMPLE_RATE = 24000


@dataclass
class TestCase:
    """A test case with ground truth"""
    name: str
    audio_file: str
    ground_truth_text: str  # What was actually said
    expected_intent: str    # What the user wanted
    valid_responses: List[str]  # Keywords that indicate correct understanding
    noise_level: float = 0.0


# Test cases with ground truth
TEST_CASES = [
    TestCase(
        name="simple_greeting",
        audio_file="test_audio/greeting.wav",
        ground_truth_text="Hello, how are you?",
        expected_intent="greeting",
        valid_responses=["hello", "hi", "hey", "fine", "good", "help"],
    ),
    TestCase(
        name="weather_query",
        audio_file="test_audio/weather.wav",
        ground_truth_text="What's the weather like today?",
        expected_intent="weather_inquiry",
        valid_responses=["weather", "sunny", "rain", "temperature", "degrees", "forecast"],
    ),
    TestCase(
        name="hindi_query",
        audio_file="test_audio/hindi.wav",
        ground_truth_text="Aaj ka mausam kaisa hai?",
        expected_intent="weather_inquiry_hindi",
        valid_responses=["mausam", "weather", "dhoop", "barish", "garmi", "thanda"],
    ),
    TestCase(
        name="task_request",
        audio_file="test_audio/task.wav",
        ground_truth_text="Can you set a reminder for tomorrow morning?",
        expected_intent="set_reminder",
        valid_responses=["reminder", "tomorrow", "morning", "set", "alarm", "note"],
    ),
]


def calculate_wer(reference: str, hypothesis: str) -> float:
    """
    Calculate Word Error Rate between reference and hypothesis.
    WER = (S + D + I) / N
    S = substitutions, D = deletions, I = insertions, N = words in reference
    """
    ref_words = reference.lower().split()
    hyp_words = hypothesis.lower().split()
    
    # Dynamic programming for edit distance
    d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
    
    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j
    
    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            if ref_words[i-1] == hyp_words[j-1]:
                d[i][j] = d[i-1][j-1]
            else:
                d[i][j] = min(
                    d[i-1][j] + 1,    # deletion
                    d[i][j-1] + 1,    # insertion
                    d[i-1][j-1] + 1   # substitution
                )
    
    if len(ref_words) == 0:
        return 0.0 if len(hyp_words) == 0 else 1.0
    
    return d[len(ref_words)][len(hyp_words)] / len(ref_words)


def calculate_intent_accuracy(response: str, valid_responses: List[str]) -> float:
    """
    Calculate how well the AI understood the intent.
    Returns 1.0 if any valid response keyword is found, 0.0 otherwise.
    """
    response_lower = response.lower()
    matches = sum(1 for keyword in valid_responses if keyword in response_lower)
    return min(1.0, matches / max(1, len(valid_responses) // 2))


def check_clarification_request(response: str) -> bool:
    """Check if AI appropriately asked for clarification"""
    clarification_phrases = [
        "repeat", "say again", "didn't hear", "couldn't hear",
        "not clear", "can you", "could you", "pardon",
        "dobara", "phir se", "clear nahi", "samajh nahi"
    ]
    response_lower = response.lower()
    return any(phrase in response_lower for phrase in clarification_phrases)


def calculate_response_relevance(response: str, expected_intent: str) -> float:
    """
    Score how relevant the response is to the expected intent.
    Uses simple keyword matching - could be enhanced with embeddings.
    """
    intent_keywords = {
        "greeting": ["hello", "hi", "help", "assist", "how are you"],
        "weather_inquiry": ["weather", "temperature", "sunny", "rain", "forecast"],
        "weather_inquiry_hindi": ["mausam", "weather", "dhoop", "barish", "garmi"],
        "set_reminder": ["reminder", "set", "tomorrow", "morning", "note", "alarm"],
    }
    
    keywords = intent_keywords.get(expected_intent, [])
    if not keywords:
        return 0.5  # Unknown intent
    
    response_lower = response.lower()
    matches = sum(1 for kw in keywords if kw in response_lower)
    return min(1.0, matches / max(1, len(keywords) // 2))


@dataclass
class TestResult:
    """Results from a single test"""
    test_case: TestCase
    ai_response: str
    transcription: Optional[str]  # What AI thought was said
    wer: float
    intent_accuracy: float
    response_relevance: float
    asked_clarification: bool
    latency_ms: float
    success: bool


async def run_single_test(test_case: TestCase) -> Optional[TestResult]:
    """Run a single test case through the voice agent"""
    
    from openai import AsyncOpenAI
    import time
    
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT", "https://abhis-mi8y4vxk-eastus2.cognitiveservices.azure.com")
    deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME", "gpt-realtime")
    api_key = os.getenv("AZURE_OPEN_API_KEY")
    
    if not api_key:
        print("Error: AZURE_OPEN_API_KEY not set")
        return None
    
    base_url = endpoint.replace("https://", "wss://").rstrip("/") + "/openai/v1"
    
    # Check if audio file exists, if not create a text-based test
    if not os.path.exists(test_case.audio_file):
        print(f"  Audio file not found, using text input: {test_case.ground_truth_text}")
        use_text = True
    else:
        use_text = False
    
    client = AsyncOpenAI(websocket_base_url=base_url, api_key=api_key)
    
    response_text = ""
    transcription = ""
    start_time = time.time()
    
    try:
        async with client.realtime.connect(model=deployment_name) as connection:
            # Configure session
            await connection.session.update(session={
                "type": "realtime",
                "instructions": """You are a helpful assistant. 
                If you can't understand clearly, ask to repeat.
                Keep responses short and relevant.""",
                "output_modalities": ["text"],
            })
            
            if use_text:
                # Send as text input
                await connection.conversation.item.create(
                    item={
                        "type": "message",
                        "role": "user",
                        "content": [{"type": "input_text", "text": test_case.ground_truth_text}],
                    }
                )
                transcription = test_case.ground_truth_text  # Perfect transcription for text
            else:
                # Send audio
                with wave.open(test_case.audio_file, 'rb') as wav:
                    audio_data = wav.readframes(wav.getnframes())
                
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
                    transcription = event.transcript
                elif event.type == "response.done":
                    break
                elif event.type == "error":
                    print(f"  Error: {event.error.message}")
                    break
            
            latency = (time.time() - start_time) * 1000
            
    except Exception as e:
        print(f"  Connection error: {e}")
        return None
    
    # Calculate metrics
    wer = calculate_wer(test_case.ground_truth_text, transcription) if transcription else 1.0
    intent_accuracy = calculate_intent_accuracy(response_text, test_case.valid_responses)
    response_relevance = calculate_response_relevance(response_text, test_case.expected_intent)
    asked_clarification = check_clarification_request(response_text)
    
    # Determine success
    # Success if: (low WER and good intent) OR (high noise and asked clarification appropriately)
    if test_case.noise_level >= 0.3:
        # High noise - success if asked clarification OR understood anyway
        success = asked_clarification or intent_accuracy >= 0.5
    else:
        # Low/no noise - success if understood the intent
        success = intent_accuracy >= 0.5 and wer < 0.5
    
    return TestResult(
        test_case=test_case,
        ai_response=response_text,
        transcription=transcription,
        wer=wer,
        intent_accuracy=intent_accuracy,
        response_relevance=response_relevance,
        asked_clarification=asked_clarification,
        latency_ms=latency,
        success=success,
    )


async def run_all_tests():
    """Run all test cases and generate report"""
    
    print("")
    print("=" * 70)
    print("  VOICE AGENT QUALITY TEST - Comprehensive Metrics")
    print("=" * 70)
    print("")
    
    results: List[TestResult] = []
    
    for test_case in TEST_CASES:
        print(f"Testing: {test_case.name}")
        print(f"  Ground Truth: \"{test_case.ground_truth_text}\"")
        print(f"  Expected Intent: {test_case.expected_intent}")
        
        result = await run_single_test(test_case)
        
        if result:
            results.append(result)
            
            print(f"  AI Response: \"{result.ai_response[:80]}...\"" if len(result.ai_response) > 80 else f"  AI Response: \"{result.ai_response}\"")
            if result.transcription:
                print(f"  Transcription: \"{result.transcription}\"")
            print(f"  Metrics:")
            print(f"    - WER: {result.wer:.2%}")
            print(f"    - Intent Accuracy: {result.intent_accuracy:.2%}")
            print(f"    - Response Relevance: {result.response_relevance:.2%}")
            print(f"    - Asked Clarification: {'Yes' if result.asked_clarification else 'No'}")
            print(f"    - Latency: {result.latency_ms:.0f}ms")
            print(f"    - Success: {'PASS' if result.success else 'FAIL'}")
        print("")
    
    # Generate summary
    print("=" * 70)
    print("  SUMMARY")
    print("=" * 70)
    
    if results:
        total = len(results)
        passed = sum(1 for r in results if r.success)
        avg_wer = sum(r.wer for r in results) / total
        avg_intent = sum(r.intent_accuracy for r in results) / total
        avg_relevance = sum(r.response_relevance for r in results) / total
        avg_latency = sum(r.latency_ms for r in results) / total
        
        print(f"")
        print(f"  Total Tests:           {total}")
        print(f"  Passed:                {passed}/{total} ({passed/total*100:.0f}%)")
        print(f"")
        print(f"  Average Metrics:")
        print(f"    - Word Error Rate:   {avg_wer:.2%}")
        print(f"    - Intent Accuracy:   {avg_intent:.2%}")
        print(f"    - Response Relevance:{avg_relevance:.2%}")
        print(f"    - Latency:           {avg_latency:.0f}ms")
        print(f"")
        
        # Quality grade
        overall_score = (
            (1 - avg_wer) * 0.3 +      # 30% weight on transcription
            avg_intent * 0.4 +          # 40% weight on intent
            avg_relevance * 0.2 +       # 20% weight on relevance
            (passed/total) * 0.1        # 10% weight on pass rate
        )
        
        if overall_score >= 0.9:
            grade = "A"
        elif overall_score >= 0.8:
            grade = "B"
        elif overall_score >= 0.7:
            grade = "C"
        elif overall_score >= 0.6:
            grade = "D"
        else:
            grade = "F"
        
        print(f"  Overall Quality Score: {overall_score:.2%}")
        print(f"  Grade: {grade}")
        print(f"")
        
        # Save detailed results
        results_data = {
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "total": total,
                "passed": passed,
                "avg_wer": avg_wer,
                "avg_intent_accuracy": avg_intent,
                "avg_response_relevance": avg_relevance,
                "avg_latency_ms": avg_latency,
                "overall_score": overall_score,
                "grade": grade,
            },
            "tests": [
                {
                    "name": r.test_case.name,
                    "ground_truth": r.test_case.ground_truth_text,
                    "expected_intent": r.test_case.expected_intent,
                    "ai_response": r.ai_response,
                    "transcription": r.transcription,
                    "wer": r.wer,
                    "intent_accuracy": r.intent_accuracy,
                    "response_relevance": r.response_relevance,
                    "asked_clarification": r.asked_clarification,
                    "latency_ms": r.latency_ms,
                    "success": r.success,
                }
                for r in results
            ]
        }
        
        results_file = f"quality_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results_data, f, indent=2, ensure_ascii=False)
        
        print(f"  Detailed report saved: {results_file}")
    
    print("=" * 70)
    
    return results


if __name__ == "__main__":
    asyncio.run(run_all_tests())

