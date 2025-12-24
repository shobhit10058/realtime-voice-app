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
   - Captures microphone audio using Web Audio API
   - Converts audio to PCM16 format (24kHz sample rate)
   - Streams audio to backend via WebSocket
   - Receives and plays AI audio responses
   - Handles interruption (barge-in)

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

### Audio Format

- **Sample Rate**: 24,000 Hz
- **Format**: PCM16 (16-bit signed integer)
- **Channels**: Mono

---

## Features Implemented

### 1. Real-Time Voice Conversation
- Continuous listening with VAD
- Natural conversation flow
- Multi-language support (English, Hindi, Hinglish)

### 2. Interruption Handling (Barge-In)
- User can interrupt AI mid-response
- AI audio stops immediately
- New user input is processed

### 3. Smart Audio Buffering
- Initial 500ms buffer for smooth playback
- Dynamic 200ms chunks after buffering
- Gap prevention with schedule-ahead timing

### 4. System Prompt Customization
- Configurable AI personality
- Response length control
- Honesty enforcement (no guessing)
- Voice clarity handling (ask to repeat)

### 5. Latency Tracking
- Comprehensive logging
- Real-time metrics
- Session-level tracking

---

## Best Practices

1. **Keep Responses Short**: Configure AI for concise answers to minimize streaming time.

2. **Handle Network Issues**: Implement reconnection logic for dropped connections.

3. **Buffer Audio**: Use initial buffering to prevent choppy playback.

4. **Log Latency**: Track metrics to identify performance issues.

5. **Test Interruption**: Ensure smooth user experience when interrupting AI.

---

## Limitations

1. **Azure-Specific Format**: Session configuration differs from OpenAI's standard format.

2. **Single Modality**: Azure currently supports either audio OR text output, not both simultaneously.

3. **Connection Dependency**: Requires stable WebSocket connection for real-time performance.

---

## Future Improvements

1. **AudioWorklet Migration**: Replace deprecated ScriptProcessor with AudioWorklet.

2. **Adaptive Buffering**: Dynamically adjust buffer size based on network conditions.

3. **Offline Detection**: Better handling of network disconnections.

4. **Multi-Speaker Support**: Speaker diarization for group conversations.

---

*Last Updated: December 24, 2025*

