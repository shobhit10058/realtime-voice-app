import React, { useState, useRef, useCallback, useEffect } from 'react';
import './App.css';

// Audio configuration for gpt-realtime
const SAMPLE_RATE = 24000;
const BUFFER_THRESHOLD = 4800; // Buffer 200ms of audio before playing (24000 * 0.2)

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [status, setStatus] = useState('Click to start voice chat');
  const [transcript, setTranscript] = useState('');
  const [aiResponse, setAiResponse] = useState('');
  const [logs, setLogs] = useState([]);

  const wsRef = useRef(null);
  const audioContextRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const processorRef = useRef(null);
  
  // Improved audio buffering
  const audioBufferRef = useRef([]);  // Accumulates samples
  const nextPlayTimeRef = useRef(0);  // Tracks when next audio should start
  const isStreamingRef = useRef(false);

  const addLog = useCallback((message, type = 'info') => {
    const timestamp = new Date().toLocaleTimeString();
    setLogs(prev => [...prev.slice(-50), { message, type, timestamp }]);
    console.log(`[${type.toUpperCase()}] ${message}`);
  }, []);

  // Convert Float32Array to Int16 PCM
  const floatTo16BitPCM = (float32Array) => {
    const int16Array = new Int16Array(float32Array.length);
    for (let i = 0; i < float32Array.length; i++) {
      const s = Math.max(-1, Math.min(1, float32Array[i]));
      int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
    }
    return int16Array;
  };

  // Convert Int16 PCM to Float32Array for playback
  const int16ToFloat32 = (int16Array) => {
    const float32Array = new Float32Array(int16Array.length);
    for (let i = 0; i < int16Array.length; i++) {
      float32Array[i] = int16Array[i] / (int16Array[i] < 0 ? 0x8000 : 0x7FFF);
    }
    return float32Array;
  };

  // Schedule audio chunk for seamless playback
  const scheduleAudioChunk = useCallback((floatData) => {
    if (!audioContextRef.current || floatData.length === 0) return;
    
    const ctx = audioContextRef.current;
    const buffer = ctx.createBuffer(1, floatData.length, SAMPLE_RATE);
    buffer.getChannelData(0).set(floatData);
    
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    
    // Schedule to play right after the previous chunk
    const currentTime = ctx.currentTime;
    const startTime = Math.max(currentTime, nextPlayTimeRef.current);
    
    source.start(startTime);
    nextPlayTimeRef.current = startTime + buffer.duration;
    
    // Update speaking state
    if (!isStreamingRef.current) {
      isStreamingRef.current = true;
      setIsSpeaking(true);
    }
    
    // Detect when audio ends
    source.onended = () => {
      if (ctx.currentTime >= nextPlayTimeRef.current - 0.05) {
        // No more audio scheduled
        setTimeout(() => {
          if (ctx.currentTime >= nextPlayTimeRef.current - 0.05) {
            isStreamingRef.current = false;
            setIsSpeaking(false);
          }
        }, 100);
      }
    };
  }, []);

  // Process incoming audio - buffer then play
  const processAudioChunk = useCallback((base64Audio) => {
    // Decode base64 to PCM
    const binaryString = atob(base64Audio);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    const int16Data = new Int16Array(bytes.buffer);
    const floatData = int16ToFloat32(int16Data);
    
    // Add to buffer
    audioBufferRef.current.push(...floatData);
    
    // Play when we have enough buffered (smooth playback)
    if (audioBufferRef.current.length >= BUFFER_THRESHOLD) {
      const chunk = new Float32Array(audioBufferRef.current.splice(0, audioBufferRef.current.length));
      scheduleAudioChunk(chunk);
    }
  }, [scheduleAudioChunk]);

  // Flush remaining audio buffer
  const flushAudioBuffer = useCallback(() => {
    if (audioBufferRef.current.length > 0) {
      const chunk = new Float32Array(audioBufferRef.current.splice(0, audioBufferRef.current.length));
      scheduleAudioChunk(chunk);
    }
  }, [scheduleAudioChunk]);

  // Reset audio state for new response
  const resetAudioState = useCallback(() => {
    audioBufferRef.current = [];
    if (audioContextRef.current) {
      nextPlayTimeRef.current = audioContextRef.current.currentTime;
    }
  }, []);

  // Handle incoming WebSocket messages
  const handleMessage = useCallback((event) => {
    try {
      const data = JSON.parse(event.data);
      
      switch (data.type) {
        case 'session.created':
          addLog('Session created!', 'success');
          break;
          
        case 'session.updated':
          addLog('Session configured', 'success');
          setIsListening(true);
          setStatus('Listening... Speak now!');
          break;
          
        case 'input_audio_buffer.speech_started':
          addLog('Speech detected...', 'info');
          setTranscript('(Listening...)');
          setAiResponse('');
          break;
          
        case 'input_audio_buffer.speech_stopped':
          addLog('Processing...', 'info');
          setTranscript('(Processing...)');
          break;
          
        case 'conversation.item.input_audio_transcription.completed':
          if (data.transcript) {
            setTranscript(data.transcript);
            addLog(`You: ${data.transcript}`, 'info');
          }
          break;
          
        case 'response.output_audio.delta':
          // Process audio chunk with buffering for smooth playback
          if (data.delta) {
            processAudioChunk(data.delta);
          }
          break;
          
        case 'response.output_audio_transcript.delta':
          if (data.delta) {
            setAiResponse(prev => prev + data.delta);
          }
          break;
          
        case 'response.output_audio_transcript.done':
          if (data.transcript) {
            setAiResponse(data.transcript);
            addLog(`AI: ${data.transcript.substring(0, 50)}...`, 'success');
          }
          break;
          
        case 'response.done':
          // Flush any remaining audio in buffer
          flushAudioBuffer();
          addLog('Response complete', 'info');
          break;
          
        case 'response.created':
          // Reset audio state for new response
          resetAudioState();
          break;
          
        case 'error':
          addLog(`Error: ${data.error?.message || 'Unknown error'}`, 'error');
          break;
          
        default:
          // console.log('Event:', data.type);
          break;
      }
    } catch (e) {
      console.error('Failed to parse message:', e);
    }
  }, [addLog, processAudioChunk, flushAudioBuffer, resetAudioState]);

  // Start the voice session
  const startSession = useCallback(async () => {
    try {
      setStatus('Getting configuration...');
      addLog('Fetching config from backend...', 'info');

      // Get config from backend
      const configResponse = await fetch('/api/config');
      if (!configResponse.ok) throw new Error('Failed to get config');
      const config = await configResponse.json();
      
      addLog(`Connecting to ${config.deployment}...`, 'info');
      setStatus('Connecting...');

      // Create AudioContext
      audioContextRef.current = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: SAMPLE_RATE
      });

      // Get microphone
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          sampleRate: SAMPLE_RATE,
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
        }
      });
      mediaStreamRef.current = stream;
      addLog('Microphone access granted', 'success');

      // Connect via WebSocket proxy on our backend
      // The backend handles Azure authentication for us
      const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
      
      // Detect environment:
      // - Production/Replit: Use same host (frontend served by backend)
      // - Local dev: React on :3000, backend on :5000
      const isLocalDev = window.location.port === '3000';
      const wsHost = isLocalDev 
        ? `${window.location.hostname}:5000`  // Local dev: connect to backend port
        : window.location.host;                // Production: same host
      
      const wsUrl = `${wsProtocol}//${wsHost}/ws/realtime`;
      addLog(`Connecting via proxy: ${wsUrl}`, 'info');
      
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        addLog('WebSocket connected!', 'success');
        setIsConnected(true);
        setStatus('Configuring session...');

        // Configure session using config from backend
        const sessionConfig = config.session_config || {};
        const sessionUpdate = {
          type: 'session.update',
          session: {
            modalities: ['text', 'audio'],
            instructions: sessionConfig.instructions || 'You are a helpful voice assistant.',
            voice: sessionConfig.voice || 'alloy',
            input_audio_format: 'pcm16',
            output_audio_format: 'pcm16',
            turn_detection: sessionConfig.turn_detection || {
              type: 'server_vad',
              threshold: 0.5,
              prefix_padding_ms: 300,
              silence_duration_ms: 500,
              create_response: true,
            }
          }
        };
        console.log('Session config:', JSON.stringify(sessionUpdate, null, 2));
        ws.send(JSON.stringify(sessionUpdate));
        addLog(`Using voice: ${sessionConfig.voice || 'alloy'}`, 'info');

        // Set up audio processing
        const source = audioContextRef.current.createMediaStreamSource(stream);
        const processor = audioContextRef.current.createScriptProcessor(4096, 1, 1);
        processorRef.current = processor;

        processor.onaudioprocess = (e) => {
          if (ws.readyState === WebSocket.OPEN) {
            const inputData = e.inputBuffer.getChannelData(0);
            const pcmData = floatTo16BitPCM(inputData);
            const base64 = btoa(String.fromCharCode(...new Uint8Array(pcmData.buffer)));
            
            ws.send(JSON.stringify({
              type: 'input_audio_buffer.append',
              audio: base64
            }));
          }
        };

        source.connect(processor);
        processor.connect(audioContextRef.current.destination);
      };

      ws.onmessage = handleMessage;

      ws.onerror = (error) => {
        addLog(`WebSocket error: ${error.message || 'Connection failed'}`, 'error');
        setStatus('Connection error');
      };

      ws.onclose = () => {
        addLog('WebSocket closed', 'warning');
        setIsConnected(false);
        setIsListening(false);
        setStatus('Disconnected. Click to reconnect.');
      };

    } catch (error) {
      addLog(`Error: ${error.message}`, 'error');
      setStatus(`Error: ${error.message}`);
    }
  }, [addLog, handleMessage]);

  // Stop the session
  const stopSession = useCallback(() => {
    addLog('Stopping session...', 'info');
    
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    
    if (mediaStreamRef.current) {
      mediaStreamRef.current.getTracks().forEach(track => track.stop());
      mediaStreamRef.current = null;
    }
    
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    
    audioBufferRef.current = [];
    isStreamingRef.current = false;
    setIsConnected(false);
    setIsListening(false);
    setIsSpeaking(false);
    setStatus('Session ended. Click to restart.');
    addLog('Session stopped', 'success');
  }, [addLog]);

  const toggleSession = useCallback(() => {
    if (isConnected) {
      stopSession();
    } else {
      startSession();
    }
  }, [isConnected, startSession, stopSession]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (wsRef.current) wsRef.current.close();
      if (mediaStreamRef.current) mediaStreamRef.current.getTracks().forEach(t => t.stop());
      if (audioContextRef.current) audioContextRef.current.close();
    };
  }, []);

  return (
    <div className="app">
      <div className="container">
        <header className="header">
          <h1 className="title">
            <span className="title-icon">🎙️</span>
            GPT Voice Chat
          </h1>
          <p className="subtitle">Real-time AI conversation via WebSocket</p>
        </header>

        <div className="voice-interface">
          <button 
            className={`mic-button ${isConnected ? 'active' : ''} ${isListening ? 'listening' : ''} ${isSpeaking ? 'speaking' : ''}`}
            onClick={toggleSession}
          >
            <div className="mic-icon">
              {isConnected ? (
                isSpeaking ? <SpeakingIcon /> : <MicrophoneIcon />
              ) : (
                <MicrophoneOffIcon />
              )}
            </div>
            {isConnected && <div className="pulse-ring" />}
            {isConnected && <div className="pulse-ring delay" />}
          </button>

          <div className="status-text">{status}</div>

          {isConnected && (
            <div className="visualizer">
              {[...Array(5)].map((_, i) => (
                <div 
                  key={i} 
                  className={`bar ${isListening ? 'active' : ''} ${isSpeaking ? 'speaking' : ''}`}
                  style={{ animationDelay: `${i * 0.1}s` }}
                />
              ))}
            </div>
          )}
        </div>

        <div className="transcript-section">
          {transcript && (
            <div className="transcript-box user">
              <span className="label">You:</span>
              <p>{transcript}</p>
            </div>
          )}
          {aiResponse && (
            <div className="transcript-box ai">
              <span className="label">AI:</span>
              <p>{aiResponse}</p>
            </div>
          )}
        </div>

        <div className="logs-section">
          <div className="logs-header">
            <span>Connection Log</span>
            <button className="clear-btn" onClick={() => setLogs([])}>Clear</button>
          </div>
          <div className="logs-container">
            {logs.map((log, i) => (
              <div key={i} className={`log-entry ${log.type}`}>
                <span className="log-time">{log.timestamp}</span>
                <span className="log-message">{log.message}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

// Icons
const MicrophoneIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3zm-1-9c0-.55.45-1 1-1s1 .45 1 1v6c0 .55-.45 1-1 1s-1-.45-1-1V5zm6 6c0 2.76-2.24 5-5 5s-5-2.24-5-5H5c0 3.53 2.61 6.43 6 6.92V21h2v-3.08c3.39-.49 6-3.39 6-6.92h-2z"/>
  </svg>
);

const MicrophoneOffIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
    <path d="M12 14c1.66 0 3-1.34 3-3V5c0-1.66-1.34-3-3-3S9 3.34 9 5v6c0 1.66 1.34 3 3 3z"/>
  </svg>
);

const SpeakingIcon = () => (
  <svg viewBox="0 0 24 24" fill="currentColor" width="32" height="32">
    <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>
  </svg>
);

export default App;
