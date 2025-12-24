# Latency Metrics System Documentation

## Overview

The latency metrics system tracks and analyzes performance metrics for the GPT Realtime Voice application. It consists of two main components:

1. **LatencyTracker** (`app.py`) - Real-time logging of latency events
2. **LatencyAnalyzer** (`analyze_latency.py`) - Post-hoc analysis and reporting

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Latency Metrics Pipeline                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐   │
│  │  LatencyTracker  │ →  │   Log Files      │ →  │ LatencyAnalyzer  │   │
│  │  (app.py)        │    │   (.log)         │    │ (analyze.py)     │   │
│  └──────────────────┘    └──────────────────┘    └──────────────────┘   │
│         │                        │                        │              │
│         ▼                        ▼                        ▼              │
│  Real-time tracking      Persistent storage       Statistical analysis  │
│  during sessions         with timestamps          and reporting          │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Part 1: LatencyTracker (Backend)

### Location
`realtime-voice-app/backend/app.py` (lines 142-232)

### Purpose
Tracks timing of key events during a voice conversation session and logs them for later analysis.

### Class Structure

```python
class LatencyTracker:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.connection_start = None        # WebSocket connection initiated
        self.connection_established = None  # Azure responded
        self.speech_detected_at = None      # User started speaking
        self.speech_ended_at = None         # User stopped speaking
        self.response_created_at = None     # AI started generating
        self.first_audio_at = None          # First audio chunk received
        self.first_text_at = None           # First text token received
        self.response_done_at = None        # Response complete
        self.audio_chunks_received = 0      # Count of audio chunks
        self.total_audio_bytes = 0          # Total bytes of audio
        self.request_count = 0              # Number of user utterances
```

### Tracked Events

| Method | Event | Logged Metrics |
|--------|-------|----------------|
| `log_connection_start()` | WebSocket init | Timestamp |
| `log_connection_established()` | Azure connected | `latency` (connection time) |
| `log_speech_detected()` | User starts speaking | `request_num` |
| `log_speech_ended()` | User stops speaking | `speech_duration` |
| `log_response_created()` | AI response starts | `processing_latency` |
| `log_first_audio()` | First audio chunk | `time_to_first_audio` (TTFA) |
| `log_first_text()` | First text token | `time_to_first_text` (TTFT) |
| `log_response_done()` | Response complete | `total_response_time`, `end_to_end` |
| `log_disconnect()` | Session ends | `session_duration`, `total_requests` |
| `log_error()` | Error occurred | Error message |

### Event Timeline

```
User clicks "Start"
    │
    ▼
log_connection_start()
    │ ← Connection Latency
    ▼
log_connection_established()
    │
    ▼
[User speaks...]
    │
    ▼
log_speech_detected()
    │ ← Speech Duration
    ▼
log_speech_ended()
    │ ← Processing Latency
    ▼
log_response_created()
    │ ← Time to First Text (TTFT)
    ▼
log_first_text()
    │ ← Time to First Audio (TTFA)
    ▼
log_first_audio()
    │ ← Audio Streaming
    ▼
log_response_done()
    │
    ▼
[Repeat for next utterance...]
    │
    ▼
log_disconnect()
```

### Log Format

Logs are written to `logs/latency_YYYYMMDD.log`:

```
2025-12-25 10:30:45,123 - [session_1735123845000] CONNECTION_START
2025-12-25 10:30:46,456 - [session_1735123845000] CONNECTION_ESTABLISHED | latency=1333.00ms
2025-12-25 10:30:48,789 - [session_1735123845000] SPEECH_DETECTED | request_num=1
2025-12-25 10:30:50,012 - [session_1735123845000] SPEECH_ENDED | speech_duration=1223.00ms
2025-12-25 10:30:50,089 - [session_1735123845000] RESPONSE_CREATED | processing_latency=77.00ms
2025-12-25 10:30:50,104 - [session_1735123845000] FIRST_TEXT | time_to_first_text=92.00ms | preview=Hello! How can I...
2025-12-25 10:30:50,156 - [session_1735123845000] FIRST_AUDIO | time_to_first_audio=144.00ms
2025-12-25 10:30:53,234 - [session_1735123845000] RESPONSE_DONE | total_response_time=3222.00ms | end_to_end=4445.00ms | audio_chunks=47 | audio_bytes=94000
```

### Integration Points

The tracker is called from the WebSocket handler in `app.py`:

```python
# On Azure message received
if msg_type == 'session.created':
    tracker.log_connection_established()
elif msg_type == 'input_audio_buffer.speech_started':
    tracker.log_speech_detected()
elif msg_type == 'input_audio_buffer.speech_stopped':
    tracker.log_speech_ended()
elif msg_type == 'response.created':
    tracker.log_response_created()
elif msg_type == 'response.audio.delta':
    tracker.log_first_audio(len(audio_data))
elif msg_type == 'response.audio_transcript.delta':
    tracker.log_first_text(text)
elif msg_type == 'response.done':
    tracker.log_response_done()
```

---

## Part 2: LatencyAnalyzer (Analysis Script)

### Location
`realtime-voice-app/backend/analyze_latency.py`

### Purpose
Parses log files and generates statistical analysis with performance assessments.

### Usage

```bash
# Analyze today's logs
python analyze_latency.py

# Analyze specific log file
python analyze_latency.py logs/latency_20251225.log

# Analyze all historical logs
python analyze_latency.py --all

# Export as JSON
python analyze_latency.py --json

# Export as CSV
python analyze_latency.py --csv
```

### Class Structure

```python
class LatencyAnalyzer:
    def __init__(self):
        self.sessions = defaultdict(...)  # Per-session data
        self.metrics = {
            'connection_latency': [],      # Time to connect to Azure
            'time_to_first_audio': [],     # TTFA values
            'time_to_first_text': [],      # TTFT values
            'total_response_time': [],     # Full response duration
            'end_to_end': [],              # Speech start to response end
            'speech_duration': [],         # How long user spoke
        }
```

### Parsing Logic

The analyzer uses regex to extract metrics from log lines:

```python
def _parse_line(self, line: str):
    # Extract session ID: [session_1735123845000]
    session_match = re.search(r'\[(session_\d+)\]', line)
    
    # Extract metric values: latency=1333.00ms
    pattern = rf'{metric_name}=(\d+\.?\d*)ms'
    match = re.search(pattern, line)
```

### Statistical Calculations

For each metric, the analyzer calculates:

| Statistic | Description |
|-----------|-------------|
| **Count** | Number of data points |
| **Min** | Minimum value |
| **Max** | Maximum value |
| **Mean** | Average value |
| **Median** | 50th percentile |
| **Std Dev** | Standard deviation |
| **P90** | 90th percentile (10% slower than this) |
| **P95** | 95th percentile |
| **P99** | 99th percentile |

### Performance Assessment

The script rates TTFA performance:

| Rating | TTFA Range | Indicator |
|--------|------------|-----------|
| 🟢 EXCELLENT | < 300ms | Users perceive instant response |
| 🟡 GOOD | 300-500ms | Acceptable conversational delay |
| 🟠 ACCEPTABLE | 500-800ms | Noticeable but tolerable |
| 🔴 NEEDS IMPROVEMENT | > 800ms | Poor user experience |

### Output Formats

#### Console Report

```
======================================================================
   GPT REALTIME LATENCY ANALYSIS REPORT
   Generated: 2025-12-25 10:45:00
======================================================================

SUMMARY
----------------------------------------
   Total Sessions:    49
   Total Requests:    126

Time to First Audio (TTFA)
----------------------------------------
   Count:      126
   Min:        0.94 ms
   Max:        16072 ms
   Mean:       350 ms
   Median:     20.6 ms
   P90:        842 ms
   P95:        1718 ms

PERFORMANCE ASSESSMENT
----------------------------------------
   🟡 Time to First Audio: GOOD
      Average TTFA of 350ms
```

#### JSON Export (`--json`)

```json
{
  "generated_at": "2025-12-25T10:45:00",
  "summary": {
    "total_sessions": 49,
    "total_requests": 126
  },
  "metrics": {
    "time_to_first_audio": {
      "raw_values": [0.94, 15.2, 21.5, ...],
      "statistics": {
        "count": 126,
        "min": 0.94,
        "max": 16072,
        "mean": 350,
        "median": 20.6,
        "p90": 842,
        "p95": 1718
      }
    }
  }
}
```

#### CSV Export (`--csv`)

```csv
Metric,Count,Min,Max,Mean,Median,StdDev,P90,P95,P99
connection_latency,49,1270,7313,1990,1496,892,3337,4441,None
time_to_first_audio,126,0.94,16072,350,20.6,1234,842,1718,2152
time_to_first_text,118,0.52,2152,165,15.4,456,349,1710,None
```

---

## Key Metrics Explained

### 1. Connection Latency
- **What**: Time to establish WebSocket connection to Azure
- **When**: One-time cost per session
- **Good value**: < 2000ms
- **Impact**: Only affects first response of session

### 2. Time to First Audio (TTFA) ⭐
- **What**: Time from user stops speaking to first audio chunk arrives
- **Why important**: Primary measure of perceived responsiveness
- **Good value**: < 300ms (excellent), < 500ms (good)
- **Impact**: Users perceive AI as "fast" or "slow"

### 3. Time to First Text (TTFT)
- **What**: Time from speech end to first transcript token
- **Why important**: Indicates server processing speed
- **Good value**: < 200ms
- **Note**: Usually slightly faster than TTFA

### 4. Total Response Time
- **What**: Time from speech end to response complete
- **Why important**: Shows full response duration
- **Depends on**: Response length (more words = longer time)
- **Note**: Not a latency issue if first audio is fast

### 5. End-to-End Latency
- **What**: Time from speech start to response complete
- **Includes**: User speaking + processing + AI speaking
- **Note**: Naturally longer; includes user's speech duration

### 6. Speech Duration
- **What**: How long user spoke
- **Useful for**: Understanding typical utterance lengths
- **Note**: Longer speech = potentially more context for AI

---

## File Locations

```
realtime-voice-app/
├── backend/
│   ├── app.py                    # LatencyTracker class
│   ├── analyze_latency.py        # LatencyAnalyzer script
│   └── logs/
│       ├── latency_20251224.log  # Daily log files
│       ├── latency_20251225.log
│       ├── metrics_20251225.csv  # Exported CSV
│       ├── metrics_20251225.json # Exported JSON
│       └── report_20251225_104500.txt  # Generated reports
```

---

## API Endpoint

The backend also exposes a REST endpoint for real-time stats:

```
GET /api/latency-stats
```

Response:
```json
{
  "stats": [
    "[session_xxx] FIRST_AUDIO | time_to_first_audio=123.45ms",
    "[session_xxx] RESPONSE_DONE | total_response_time=3456.78ms | ..."
  ],
  "log_file": "logs/latency_20251225.log"
}
```

---

## Best Practices

1. **Run analysis regularly** - Check performance trends daily
2. **Monitor P95/P99** - High percentiles show worst-case experience
3. **Compare mean vs median** - Large gap indicates outliers
4. **Track by region** - Network distance affects latency
5. **Archive logs** - Keep historical data for trend analysis

---

## Troubleshooting

### High Connection Latency
- Check network route to Azure region
- Consider closer Azure region
- Verify firewall/proxy settings

### High TTFA
- Network issues (check P95 vs mean)
- Azure service congestion (check status page)
- Large audio buffers (check chunk sizes)

### Missing Metrics
- Ensure all event handlers call tracker methods
- Check log file permissions
- Verify date in log filename matches today

---

*Last Updated: December 25, 2025*

