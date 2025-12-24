# GPT Realtime Voice Chat - Product Documentation

## Overview

GPT Realtime Voice Chat is a real-time voice conversation application powered by Azure OpenAI's GPT Realtime API. It enables natural, low-latency voice interactions with an AI assistant, similar to talking to a human.

---

## Architecture

```
┌─────────────────┐     WebSocket      ┌─────────────────┐     WebSocket      ┌─────────────────┐
│                 │  ←───────────────→ │                 │  ←───────────────→ │                 │
│  React Frontend │    (Audio/Text)    │  Flask Backend  │    (Audio/Text)    │  Azure OpenAI   │
│   (Browser)     │                    │  (Proxy Server) │                    │  Realtime API   │
│                 │                    │                 │                    │                 │
└─────────────────┘                    └─────────────────┘                    └─────────────────┘
       ↑                                       ↑                                      ↑
       │                                       │                                      │
  User speaks                          Routes messages                         Processes audio
  into microphone                      Handles auth                            Generates response
  Plays AI audio                       Tracks latency                          Streams audio back
```

### Components

1. **Frontend (React)**
   - Captures microphone audio using Web Audio API (ScriptProcessorNode)
   - Converts audio to PCM16 format (24kHz sample rate)
   - Streams audio to backend via WebSocket (base64 encoded)
   - **PCMPlayer class** handles audio playback with smart buffering
   - Handles interruption (barge-in) with smooth fade-out

2. **Backend (Flask + Flask-Sock)**
   - Acts as WebSocket proxy to Azure OpenAI
   - Handles authentication (API key injection)
   - Tracks and logs latency metrics
   - Serves configuration to frontend

3. **Azure OpenAI Realtime API**
   - Receives streaming audio input
   - Performs Voice Activity Detection (VAD)
   - Transcribes speech in real-time
   - Generates AI responses
   - Streams audio output back

---

## Audio Playback Architecture

### The Challenge

Azure OpenAI Realtime API streams audio in **irregular chunks**. The timing and size of chunks varies due to:
- Network jitter
- Server-side audio generation patterns
- WebSocket message batching

This irregularity causes audio breakups if chunks are played immediately as received.

### Solution: PCMPlayer Class

```javascript
class PCMPlayer {
  constructor(sampleRate = 24000) {
    this.sampleRate = sampleRate;
    this.accumulatedSamples = [];      // Buffer for incoming samples
    this.nextScheduledTime = 0;         // Next playback time
    this.SAMPLES_THRESHOLD = 12000;     // 500ms @ 24kHz
    this.FLUSH_TIMEOUT_MS = 150;        // Force flush after no data
  }
}
```

### How It Works

```
Chunks arrive irregularly → Accumulate in buffer → 
  ↓
When buffer has 500ms (12000 samples) OR 150ms timeout → Flush
  ↓
Schedule audio buffer at next available time → 
  ↓
Seamless playback with no gaps
```

### Key Features

| Feature | Implementation |
|---------|----------------|
| **Accumulation** | Collects samples until 500ms threshold |
| **Timeout Flush** | Forces playback after 150ms silence (end of response) |
| **Gap Prevention** | Schedules buffers sequentially with precise timing |
| **Smooth Stop** | 50ms fade-out on interruption (no clicks) |
| **Lazy Init** | Creates AudioContext only when needed |

### Audio Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Frontend Audio Pipeline                         │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  WebSocket Message                                                       │
│       │                                                                  │
│       ▼                                                                  │
│  ┌──────────────┐                                                        │
│  │ Base64 Decode │  →  Raw PCM16 bytes                                  │
│  └──────────────┘                                                        │
│       │                                                                  │
│       ▼                                                                  │
│  ┌──────────────┐                                                        │
│  │ Int16 → Float │  →  Float32Array (-1.0 to 1.0)                       │
│  └──────────────┘                                                        │
│       │                                                                  │
│       ▼                                                                  │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │                         PCMPlayer                                   │ │
│  │  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐ │ │
│  │  │ Accumulate      │ →  │ Threshold Check │ →  │ Schedule Audio  │ │ │
│  │  │ Samples         │    │ (500ms/150ms)   │    │ Buffer          │ │ │
│  │  └─────────────────┘    └─────────────────┘    └─────────────────┘ │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│       │                                                                  │
│       ▼                                                                  │
│  ┌──────────────┐                                                        │
│  │ AudioContext │  →  Speaker Output                                    │
│  └──────────────┘                                                        │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## How the Realtime API Works

### Traditional vs Realtime Approach

| Aspect | Traditional (Speech-to-Text → LLM → TTS) | Realtime API |
|--------|------------------------------------------|--------------|
| **Latency** | High (3-5+ seconds) | Low (~200-500ms to first audio) |
| **Pipeline** | 3 separate API calls | Single WebSocket connection |
| **Streaming** | Limited | Full duplex streaming |
| **Interruption** | Not supported | Native support |
| **Context** | Audio context lost | Audio context preserved |

### Key Features of Realtime API

1. **Single WebSocket Connection**
   - Eliminates HTTP overhead
   - Persistent connection for entire conversation
   - Bi-directional real-time communication

2. **Server-Side Voice Activity Detection (VAD)**
   - Automatically detects when user starts/stops speaking
   - No manual "push-to-talk" required
   - Handles natural conversation flow

3. **Streaming Audio I/O**
   - Audio is processed as it arrives
   - Response generation starts before user finishes speaking
   - Audio output streams as it's generated

4. **Native Interruption Support**
   - User can interrupt AI mid-response
   - AI stops and listens to new input
   - Natural conversation dynamics

---

## Latency Analysis

### Metrics Tracked

| Metric | Description |
|--------|-------------|
| **Connection Latency** | Time to establish WebSocket connection to Azure |
| **Time to First Text (TTFT)** | Time from speech end to first text token |
| **Time to First Audio (TTFA)** | Time from speech end to first audio chunk |
| **Total Response Time** | Time from speech end to response complete |
| **End-to-End Latency** | Total time from speech start to response complete |

### Performance Report (Generated: 2025-12-24)

**Summary:**
- Total Sessions: 49
- Total Requests: 126

#### Connection Latency
| Metric | Value |
|--------|-------|
| Count | 49 connections |
| Min | 1,270 ms |
| Max | 7,313 ms |
| **Mean** | **1,990 ms** |
| Median | 1,496 ms |
| P90 | 3,337 ms |
| P95 | 4,441 ms |

*Note: Connection is a one-time cost per session.*

#### Time to First Audio (TTFA) ⚡
| Metric | Value |
|--------|-------|
| Count | 126 requests |
| Min | 0.94 ms |
| Max | 16,072 ms |
| **Mean** | **350 ms** |
| **Median** | **20.6 ms** |
| P90 | 842 ms |
| P95 | 1,718 ms |
| P99 | 2,152 ms |

**🟡 Rating: GOOD** - Users typically hear AI response within ~350ms of finishing speaking.

#### Time to First Text (TTFT)
| Metric | Value |
|--------|-------|
| Count | 118 requests |
| Min | 0.52 ms |
| Max | 2,152 ms |
| **Mean** | **165 ms** |
| **Median** | **15.4 ms** |
| P90 | 349 ms |
| P95 | 1,710 ms |

#### Total Response Time
| Metric | Value |
|--------|-------|
| Count | 151 responses |
| Min | 2 ms |
| Max | 30,336 ms |
| **Mean** | **7,027 ms (~7s)** |
| Median | 4,930 ms (~5s) |
| P90 | 18,812 ms |
| P95 | 23,780 ms |

*Response time depends on response length (more words = more time)*

#### End-to-End Latency
| Metric | Value |
|--------|-------|
| Count | 142 interactions |
| Min | 0.53 ms |
| Max | 30,461 ms |
| **Mean** | **8,411 ms (~8.4s)** |
| Median | 6,837 ms (~6.8s) |
| P90 | 22,043 ms |

*E2E includes: user speech time + processing + AI response*

#### Speech Duration
| Metric | Value |
|--------|-------|
| Count | 151 utterances |
| **Mean** | **1,802 ms (~1.8s)** |
| Median | 1,700 ms |
| P90 | 3,412 ms |

### Latency Breakdown

```
User speaks (avg ~1.8s)
    │
    ▼
Speech ends
    │ ← Processing latency (~0-80ms)
    ▼
Response created
    │ ← Time to first text (median: 15ms)
    ▼
First text token
    │ ← Time to first audio (median: 21ms)
    ▼
Audio streaming starts
    │ ← Audio generation (median: 5s depending on response length)
    ▼
Response complete
```

### Key Insights

1. **Fast Median TTFA (21ms)**: Half of all requests get first audio within 21ms - nearly instant response perception!

2. **Mean vs Median Gap**: The mean (350ms) is much higher than median (21ms) due to occasional slow responses, but typical experience is fast.

3. **Response Length Drives Total Time**: Average 7s total response time reflects AI speaking time, not latency.

4. **Connection Once Per Session**: The ~2s connection cost is amortized across the entire conversation.

5. **Interruption Working**: Quick response times (2ms) indicate successful handling of interrupted responses.

---

## Configuration

### Session Settings

```python
SESSION_CONFIG = {
    "type": "realtime",
    "instructions": SYSTEM_PROMPT,  # AI personality and rules
}
```

### VAD Settings (Server-Side)

```python
turn_detection = {
    "type": "server_vad",
    "threshold": 0.5,           # Voice detection sensitivity
    "prefix_padding_ms": 300,   # Audio before speech detection
    "silence_duration_ms": 500, # Silence before considering speech ended
    "create_response": True,    # Auto-create response after speech
}
```

### PCMPlayer Settings (Frontend)

```javascript
const SAMPLE_RATE = 24000;           // Must match Azure output
const SAMPLES_THRESHOLD = 12000;     // 500ms buffer before playback
const FLUSH_TIMEOUT_MS = 150;        // Force flush after no new data
const FADE_OUT_DURATION = 0.05;      // 50ms fade for smooth stop
```

### Audio Format

- **Sample Rate**: 24,000 Hz
- **Format**: PCM16 (16-bit signed integer)
- **Channels**: Mono
- **Encoding**: Base64 over WebSocket

---

## Features Implemented

### 1. Real-Time Voice Conversation
- Continuous listening with VAD
- Natural conversation flow
- Multi-language support (English, Hindi, Hinglish)

### 2. Interruption Handling (Barge-In)
- User can interrupt AI mid-response
- **Smooth fade-out** (50ms) prevents audio clicks
- Server VAD detects speech and initiates new response
- No explicit `response.cancel` needed (lets server handle naturally)

### 3. PCMPlayer Audio Engine
- **Accumulation-based buffering**: Collects audio samples until 500ms worth
- **Smart flush timeout**: Flushes remaining audio after 150ms of no new data (handles irregular chunks)
- **Seamless scheduling**: Uses Web Audio API `AudioBufferSourceNode` with precise timing
- **Smooth interruption**: 50ms fade-out on stop (no audio clicks)
- **Self-managing lifecycle**: Encapsulated class handles AudioContext creation/destruction

### 4. System Prompt Customization
- Configurable AI personality (sarcastic, helpful, etc.)
- Response length control (1-2 sentence concise answers)
- **Honesty enforcement**: Never guesses facts, says "I don't know"
- **Voice clarity handling**: Asks user to repeat if audio unclear
- Multi-language support: English, Hindi, Hinglish

### 5. Latency Tracking
- Comprehensive logging
- Real-time metrics
- Session-level tracking

---

## Best Practices

1. **Keep Responses Short**: Configure AI for concise 1-2 sentence answers to minimize streaming time.

2. **Handle Network Issues**: Implement reconnection logic for dropped connections.

3. **Accumulate Before Playing**: Buffer 500ms of audio before starting playback to handle irregular chunks.

4. **Use Timeout Flush**: Force-flush remaining samples after 150ms to ensure end-of-response audio plays.

5. **Smooth Interruption**: Use fade-out (not abrupt stop) when user interrupts to avoid clicks.

6. **Log Latency**: Track TTFA, TTFT, and E2E metrics to identify performance issues.

7. **Test Edge Cases**: Test with slow networks, interruptions, and long responses.

---

## Limitations

1. **Azure-Specific Format**: Session configuration differs from OpenAI's standard format.

2. **Single Modality**: Azure currently supports either audio OR text output, not both simultaneously.

3. **Connection Dependency**: Requires stable WebSocket connection for real-time performance.

---

## Future Improvements

1. **AudioWorklet Migration**: Replace deprecated ScriptProcessorNode with AudioWorklet for input capture.

2. **Adaptive Buffering**: Dynamically adjust accumulation threshold based on network conditions.

3. **WebRTC Integration**: Consider LiveKit or similar for lower latency and better NAT traversal.

4. **Offline Detection**: Better handling of network disconnections with auto-reconnect.

5. **Multi-Speaker Support**: Speaker diarization for group conversations.

6. **Opus Codec**: Consider requesting Opus-encoded audio from Azure for smaller payloads.

---

*Last Updated: December 25, 2025*

