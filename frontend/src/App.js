import React, { useState, useRef, useCallback, useEffect } from 'react';
import './App.css';

// Audio configuration for gpt-realtime
const SAMPLE_RATE = 24000;

function App() {
  const [isConnected, setIsConnected] = useState(false);
  const [isListening, setIsListening] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [status, setStatus] = useState('Click to start voice chat');
  const [transcript, setTranscript] = useState('');
  const [aiResponse, setAiResponse] = useState('');
  const [conversationHistory, setConversationHistory] = useState([]);  // Persist all exchanges
  const [logs, setLogs] = useState([]);
  const [sarvamTranscript, setSarvamTranscript] = useState('');
  const [isSarvamProcessing, setIsSarvamProcessing] = useState(false);
  const [isRecordingForSarvam, setIsRecordingForSarvam] = useState(false);

  const wsRef = useRef(null);
  const audioContextRef = useRef(null);
  const mediaStreamRef = useRef(null);
  const processorRef = useRef(null);
  const workletNodeRef = useRef(null);
  
  // PCM Player approach - more reliable for streaming
  const pcmPlayerRef = useRef(null);
  const isStreamingRef = useRef(false);
  
  // Sarvam AI - separate MediaRecorder for independent audio capture
  const sarvamRecorderRef = useRef(null);
  const sarvamChunksRef = useRef([]);
  
  // Refs to track last completed exchange for history saving
  const lastCompletedTranscriptRef = useRef('');
  const lastCompletedAiResponseRef = useRef('');
  
  // Interruption debounce refs - prevent false interruptions from background noise
  const speechStartedAtRef = useRef(null);           // Timestamp when speech was detected
  const interruptionDebounceRef = useRef(null);      // Debounce timer for interruption
  const pendingInterruptionRef = useRef(false);      // Whether we're waiting to confirm interruption
  const interruptionConfigRef = useRef({
    min_speech_duration_ms: 400,   // User must speak for at least 400ms to interrupt
    debounce_ms: 300,              // Wait 300ms after speech_started to decide
    require_sustained_speech: true
  });

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

  // Improved PCM Player class for smooth streaming audio
  class PCMPlayer {
    constructor(options) {
      this.sampleRate = options.sampleRate || 24000;
      this.channels = options.channels || 1;
      
      this.audioCtx = null;
      this.gainNode = null;
      this.scheduledTime = 0;
      this.samples = new Float32Array(0);
      this.isPlaying = false;
      this.onPlayingChange = options.onPlayingChange || (() => {});
      
      // Buffering settings for smooth playback - tuned to prevent audio breaking at start
      this.minBufferSize = Math.floor(this.sampleRate * 0.15); // 150ms minimum buffer before playing (was 80ms)
      this.maxBufferSize = Math.floor(this.sampleRate * 0.5);  // 500ms max buffer before forcing flush (was 300ms)
      this.isBuffering = true; // Start in buffering mode
      this.scheduledBuffers = [];
      this.endCheckTimer = null;
    }
    
    init() {
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: this.sampleRate
      });
      this.gainNode = this.audioCtx.createGain();
      this.gainNode.gain.value = 1;
      this.gainNode.connect(this.audioCtx.destination);
      this.scheduledTime = this.audioCtx.currentTime;
    }
    
    feed(data) {
      if (!this.audioCtx) this.init();
      
      // Resume if suspended
      if (this.audioCtx.state === 'suspended') {
        this.audioCtx.resume();
      }
      
      // Append new data to samples
      const newSamples = new Float32Array(this.samples.length + data.length);
      newSamples.set(this.samples);
      newSamples.set(data, this.samples.length);
      this.samples = newSamples;
      
      // Decide when to flush based on buffer state
      if (this.isBuffering) {
        // Initial buffering - wait for minimum buffer before starting
        if (this.samples.length >= this.minBufferSize) {
          this.isBuffering = false;
          this.flush();
        }
      } else {
        // Streaming mode - flush when we have enough for smooth playback
        // Use slightly larger chunks for smoother audio (less gaps)
        const chunkSize = Math.floor(this.sampleRate * 0.12); // 120ms chunks (was 100ms)
        if (this.samples.length >= chunkSize) {
          this.flush();
        }
      }
      
      // Force flush if buffer gets too large (prevents memory issues)
      if (this.samples.length >= this.maxBufferSize) {
        this.flush();
      }
    }
    
    flush() {
      if (!this.audioCtx || this.samples.length === 0) return;
      
      const bufferSource = this.audioCtx.createBufferSource();
      const buffer = this.audioCtx.createBuffer(this.channels, this.samples.length, this.sampleRate);
      buffer.getChannelData(0).set(this.samples);
      
      bufferSource.buffer = buffer;
      bufferSource.connect(this.gainNode);
      
      // Schedule playback - ensure continuous audio without gaps
      const currentTime = this.audioCtx.currentTime;
      const scheduleAhead = 0.05; // 50ms lookahead for scheduling (was 20ms) - smoother start
      
      if (this.scheduledTime < currentTime + scheduleAhead) {
        // We're behind or just starting - schedule with enough buffer to prevent glitches
        this.scheduledTime = currentTime + scheduleAhead;
      }
      
      bufferSource.start(this.scheduledTime);
      this.scheduledTime += buffer.duration;
      
      // Track this buffer for cleanup
      this.scheduledBuffers.push(bufferSource);
      
      // Track playing state
      if (!this.isPlaying) {
        this.isPlaying = true;
        this.onPlayingChange(true);
      }
      
      // Setup end detection
      bufferSource.onended = () => {
        // Remove from scheduled buffers
        const idx = this.scheduledBuffers.indexOf(bufferSource);
        if (idx > -1) this.scheduledBuffers.splice(idx, 1);
        
        // Check if playback is complete
        this.checkPlaybackEnd();
      };
      
      // Clear the samples
      this.samples = new Float32Array(0);
    }
    
    checkPlaybackEnd() {
      // Debounce the end check
      if (this.endCheckTimer) {
        clearTimeout(this.endCheckTimer);
      }
      
      this.endCheckTimer = setTimeout(() => {
        if (this.audioCtx && 
            this.scheduledBuffers.length === 0 && 
            this.samples.length === 0 &&
            this.audioCtx.currentTime >= this.scheduledTime - 0.05) {
          this.isPlaying = false;
          this.isBuffering = true; // Reset to buffering mode for next response
          this.onPlayingChange(false);
        }
      }, 200);
    }
    
    stop() {
      if (this.endCheckTimer) {
        clearTimeout(this.endCheckTimer);
        this.endCheckTimer = null;
      }
      
      // Stop all scheduled buffers
      this.scheduledBuffers.forEach(buf => {
        try { buf.stop(); } catch(e) {}
      });
      this.scheduledBuffers = [];
      
      // Fade out
      if (this.gainNode && this.audioCtx) {
        const now = this.audioCtx.currentTime;
        this.gainNode.gain.setValueAtTime(this.gainNode.gain.value, now);
        this.gainNode.gain.linearRampToValueAtTime(0, now + 0.05);
        
        // Reset gain after fade
        setTimeout(() => {
          if (this.gainNode && this.audioCtx) {
            this.gainNode.gain.setValueAtTime(1, this.audioCtx.currentTime);
          }
        }, 100);
      }
      
      this.samples = new Float32Array(0);
      this.scheduledTime = this.audioCtx ? this.audioCtx.currentTime : 0;
      this.isPlaying = false;
      this.isBuffering = true;
      this.onPlayingChange(false);
    }
    
    destroy() {
      this.stop();
      if (this.audioCtx) {
        this.audioCtx.close();
        this.audioCtx = null;
      }
    }
  }

  // Stop all playing audio (for interruption handling)
  const stopAllAudio = useCallback(() => {
    if (pcmPlayerRef.current) {
      pcmPlayerRef.current.stop();
    }
    isStreamingRef.current = false;
    setIsSpeaking(false);
  }, []);

  // Process incoming audio
  const processAudioChunk = useCallback((base64Audio) => {
    // Initialize player if needed
    if (!pcmPlayerRef.current) {
      pcmPlayerRef.current = new PCMPlayer({
        sampleRate: SAMPLE_RATE,
        channels: 1,
        onPlayingChange: (playing) => {
          isStreamingRef.current = playing;
          setIsSpeaking(playing);
        }
      });
    }
    
    // Decode base64 to PCM
    const binaryString = atob(base64Audio);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    const int16Data = new Int16Array(bytes.buffer);
    const floatData = int16ToFloat32(int16Data);
    
    // Feed to player
    pcmPlayerRef.current.feed(floatData);
  }, []);

  // Flush remaining audio buffer
  const flushAudioBuffer = useCallback(() => {
    if (pcmPlayerRef.current) {
      pcmPlayerRef.current.flush();
    }
  }, []);

  // Start full session recording for Sarvam
  const startSarvamFullRecording = useCallback(() => {
    if (!mediaStreamRef.current || sarvamRecorderRef.current) return;
    
    try {
      sarvamChunksRef.current = [];
      const recorder = new MediaRecorder(mediaStreamRef.current, {
        mimeType: 'audio/webm;codecs=opus'
      });
      
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) {
          sarvamChunksRef.current.push(e.data);
        }
      };
      
      recorder.start(1000); // Collect data every 1 second
      sarvamRecorderRef.current = recorder;
      setIsRecordingForSarvam(true);
      addLog('Started recording for Sarvam transcription', 'info');
    } catch (err) {
      console.warn('Sarvam MediaRecorder not supported:', err);
      addLog('MediaRecorder not supported', 'error');
    }
  }, [addLog]);

  // Helper function to send a single chunk to Sarvam API
  const transcribeChunk = async (base64Audio, chunkIndex, totalChunks) => {
    try {
      const response = await fetch('/api/sarvam/transcribe', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          audio: base64Audio,
          format: 'webm',
          language_code: 'hi-IN'
        })
      });
      
      const result = await response.json();
      console.log(`Sarvam chunk ${chunkIndex + 1}/${totalChunks} result:`, result);
      
      if (result.audio_file) {
        addLog(`Saved: ${result.audio_file}`, 'info');
      }
      
      if (result.success && result.transcript) {
        return result.transcript;
      }
      return '';
    } catch (error) {
      console.warn(`Sarvam chunk ${chunkIndex + 1} error:`, error);
      return '';
    }
  };

  // Stop Sarvam recording and send to API (with chunking for long audio)
  const stopAndTranscribeWithSarvam = useCallback(async () => {
    if (!sarvamRecorderRef.current) {
      addLog('No recording to transcribe', 'warning');
      return;
    }
    
    const recorder = sarvamRecorderRef.current;
    sarvamRecorderRef.current = null;
    setIsRecordingForSarvam(false);
    setIsSarvamProcessing(true);
    setSarvamTranscript('');
    addLog('Processing with Sarvam AI...', 'info');
    
    return new Promise((resolve) => {
      recorder.onstop = async () => {
        if (sarvamChunksRef.current.length === 0) {
          setSarvamTranscript('(No audio recorded)');
          setIsSarvamProcessing(false);
          resolve();
          return;
        }
        
        try {
          // Each chunk from MediaRecorder is ~1 second
          // Sarvam limit is 30 seconds, so we'll send in batches of ~25 chunks (25 seconds) to be safe
          const CHUNKS_PER_BATCH = 25;
          const allChunks = [...sarvamChunksRef.current];
          sarvamChunksRef.current = [];
          
          const totalBatches = Math.ceil(allChunks.length / CHUNKS_PER_BATCH);
          addLog(`Processing ${allChunks.length} seconds of audio in ${totalBatches} batch(es)...`, 'info');
          
          let fullTranscript = '';
          
          for (let batchIndex = 0; batchIndex < totalBatches; batchIndex++) {
            const startIdx = batchIndex * CHUNKS_PER_BATCH;
            const endIdx = Math.min(startIdx + CHUNKS_PER_BATCH, allChunks.length);
            const batchChunks = allChunks.slice(startIdx, endIdx);
            
            // Combine batch chunks into a blob
            const audioBlob = new Blob(batchChunks, { type: 'audio/webm' });
            
            addLog(`Sending batch ${batchIndex + 1}/${totalBatches} (${(audioBlob.size / 1024).toFixed(1)} KB)...`, 'info');
            
            // Convert to base64
            const base64Audio = await new Promise((res) => {
              const reader = new FileReader();
              reader.onloadend = () => res(reader.result.split(',')[1]);
              reader.readAsDataURL(audioBlob);
            });
            
            // Transcribe this batch
            const batchTranscript = await transcribeChunk(base64Audio, batchIndex, totalBatches);
            if (batchTranscript) {
              fullTranscript += (fullTranscript ? ' ' : '') + batchTranscript;
              // Update transcript progressively
              setSarvamTranscript(fullTranscript);
            }
          }
          
          if (fullTranscript) {
            addLog('Sarvam transcription complete!', 'success');
          } else {
            setSarvamTranscript('(No speech detected in audio)');
            addLog('Sarvam: No speech detected', 'warning');
          }
          
        } catch (error) {
          console.warn('Sarvam processing error:', error);
          setSarvamTranscript(`Processing error: ${error.message}`);
          addLog(`Sarvam error: ${error.message}`, 'error');
        } finally {
          setIsSarvamProcessing(false);
        }
        resolve();
      };
      
      recorder.stop();
    });
  }, [addLog]);

  // Reset audio state for new response
  const resetAudioState = useCallback(() => {
    if (pcmPlayerRef.current) {
      pcmPlayerRef.current.samples = new Float32Array(0);
      pcmPlayerRef.current.isBuffering = true;
      if (pcmPlayerRef.current.audioCtx) {
        pcmPlayerRef.current.scheduledTime = pcmPlayerRef.current.audioCtx.currentTime;
      }
    }
  }, []);

  // Handle incoming WebSocket messages
  const handleMessage = useCallback((event) => {
    try {
      const data = JSON.parse(event.data);
      
      switch (data.type) {
        case 'session.created':
          addLog('Session created by Azure', 'success');
          break;
          
        case 'session.updated':
          addLog('Session configured', 'success');
          setIsListening(true);
          setStatus('Listening... Speak now!');
          break;
          
        case 'input_audio_buffer.speech_started':
          // Record when speech started for interruption duration checking
          speechStartedAtRef.current = Date.now();
          
          // Handle interruption with debouncing - don't interrupt immediately on background noise
          if (isStreamingRef.current) {
            // Set pending interruption flag
            pendingInterruptionRef.current = true;
            
            // Clear any existing debounce timer
            if (interruptionDebounceRef.current) {
              clearTimeout(interruptionDebounceRef.current);
            }
            
            // Wait before interrupting to ensure it's real user speech, not noise
            const config = interruptionConfigRef.current;
            interruptionDebounceRef.current = setTimeout(() => {
              // Only interrupt if speech is still ongoing (didn't get speech_stopped quickly)
              if (pendingInterruptionRef.current && speechStartedAtRef.current) {
                const speechDuration = Date.now() - speechStartedAtRef.current;
                // Only interrupt if user has been speaking long enough
                if (speechDuration >= config.min_speech_duration_ms / 2) {
                  addLog(`User interrupted (${speechDuration}ms speech) - stopping AI`, 'warning');
                  stopAllAudio();
                } else {
                  addLog(`Ignoring brief noise (${speechDuration}ms)`, 'info');
                }
              }
              pendingInterruptionRef.current = false;
            }, config.debounce_ms);
            
            addLog('Speech detected, waiting to confirm interruption...', 'info');
          } else {
            // AI not speaking, proceed normally
            addLog('Speech detected...', 'info');
          }
          
          // Save previous completed exchange to history
          if (lastCompletedTranscriptRef.current || lastCompletedAiResponseRef.current) {
            const newEntries = [];
            if (lastCompletedTranscriptRef.current) {
              newEntries.push({
                type: 'user',
                text: lastCompletedTranscriptRef.current,
                timestamp: new Date().toLocaleTimeString()
              });
            }
            if (lastCompletedAiResponseRef.current) {
              newEntries.push({
                type: 'ai',
                text: lastCompletedAiResponseRef.current,
                timestamp: new Date().toLocaleTimeString()
              });
            }
            setConversationHistory(prev => [...prev, ...newEntries]);
            // Clear refs after saving
            lastCompletedTranscriptRef.current = '';
            lastCompletedAiResponseRef.current = '';
          }
          setTranscript('(Listening...)');
          setAiResponse('');
          break;
          
        case 'input_audio_buffer.speech_stopped':
          // Calculate how long the user spoke
          const speechDuration = speechStartedAtRef.current 
            ? Date.now() - speechStartedAtRef.current 
            : 0;
          
          // If speech was very brief and we have a pending interruption, cancel it
          const config = interruptionConfigRef.current;
          if (pendingInterruptionRef.current && speechDuration < config.min_speech_duration_ms) {
            // Speech was too brief - likely background noise, cancel interruption
            addLog(`Speech too brief (${speechDuration}ms) - ignoring as noise`, 'info');
            pendingInterruptionRef.current = false;
            if (interruptionDebounceRef.current) {
              clearTimeout(interruptionDebounceRef.current);
              interruptionDebounceRef.current = null;
            }
            // Don't update transcript for noise
            break;
          }
          
          // Valid speech - confirm any pending interruption
          if (pendingInterruptionRef.current && isStreamingRef.current) {
            addLog(`Confirmed user interruption (${speechDuration}ms) - stopping AI`, 'warning');
            stopAllAudio();
            pendingInterruptionRef.current = false;
            if (interruptionDebounceRef.current) {
              clearTimeout(interruptionDebounceRef.current);
              interruptionDebounceRef.current = null;
            }
          }
          
          // Reset speech tracking
          speechStartedAtRef.current = null;
          
          addLog(`Processing... (spoke for ${speechDuration}ms)`, 'info');
          setTranscript('(Processing...)');
          break;
          
        case 'conversation.item.input_audio_transcription.completed':
          if (data.transcript) {
            setTranscript(data.transcript);
            lastCompletedTranscriptRef.current = data.transcript;
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
            lastCompletedAiResponseRef.current = data.transcript;
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
  }, [addLog, processAudioChunk, flushAudioBuffer, resetAudioState, stopAllAudio]);

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

      ws.onopen = async () => {
        addLog('WebSocket connected!', 'success');
        setIsConnected(true);
        setStatus('Configuring session...');

        // Configure session using config from backend
        // Azure OpenAI Realtime API uses a different format than OpenAI
        const sessionConfig = config.session_config || {};
        
        // Load interruption config from backend (for smart debouncing)
        if (sessionConfig.interruption_config) {
          interruptionConfigRef.current = {
            ...interruptionConfigRef.current,
            ...sessionConfig.interruption_config
          };
          addLog(`Interruption config: min ${sessionConfig.interruption_config.min_speech_duration_ms}ms, debounce ${sessionConfig.interruption_config.debounce_ms}ms`, 'info');
        }
        const instructions = sessionConfig.instructions || 'You are a helpful voice assistant.';
        const voice = sessionConfig.voice || 'alloy';
        
        // Azure OpenAI Realtime API - try minimal config
        // Azure seems to reject many standard OpenAI parameters
        const sessionUpdate = {
          type: 'session.update',
          session: {
            type: 'realtime',
            instructions: instructions
          }
        };
        console.log('Sending session.update with instructions:', instructions.substring(0, 100));
        console.log('Full session.update:', JSON.stringify(sessionUpdate, null, 2));
        ws.send(JSON.stringify(sessionUpdate));
        addLog(`Using voice: ${voice}`, 'info');

        // Set up audio processing using AudioWorklet (modern, non-deprecated API)
        try {
          await audioContextRef.current.audioWorklet.addModule('/audio-processor.js');
          
          const source = audioContextRef.current.createMediaStreamSource(stream);
          const workletNode = new AudioWorkletNode(audioContextRef.current, 'audio-capture-processor');
          workletNodeRef.current = workletNode;

          // Handle audio data from the worklet
          workletNode.port.onmessage = (event) => {
            if (ws.readyState === WebSocket.OPEN && event.data.audioData) {
              const pcmData = floatTo16BitPCM(event.data.audioData);
              const base64 = btoa(String.fromCharCode(...new Uint8Array(pcmData.buffer)));
              
              ws.send(JSON.stringify({
                type: 'input_audio_buffer.append',
                audio: base64
              }));
            }
          };

          source.connect(workletNode);
          // AudioWorkletNode doesn't need to connect to destination for input processing
          // but we keep a silent connection to ensure the audio graph stays active
          workletNode.connect(audioContextRef.current.destination);
          
          addLog('Audio worklet initialized', 'success');
        } catch (workletError) {
          // Fallback to ScriptProcessorNode for older browsers
          console.warn('AudioWorklet not supported, falling back to ScriptProcessor:', workletError);
          addLog('Using legacy audio processor', 'warning');
          
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
        }
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
    
    // Cleanup interruption debounce timer
    if (interruptionDebounceRef.current) {
      clearTimeout(interruptionDebounceRef.current);
      interruptionDebounceRef.current = null;
    }
    pendingInterruptionRef.current = false;
    speechStartedAtRef.current = null;
    
    // Cleanup Sarvam recorder
    if (sarvamRecorderRef.current) {
      try { sarvamRecorderRef.current.stop(); } catch(e) {}
      sarvamRecorderRef.current = null;
    }
    setIsRecordingForSarvam(false);
    
    // Cleanup AudioWorklet node
    if (workletNodeRef.current) {
      workletNodeRef.current.disconnect();
      workletNodeRef.current = null;
    }
    
    // Cleanup legacy ScriptProcessor (fallback)
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
    
    // Cleanup PCM player
    if (pcmPlayerRef.current) {
      pcmPlayerRef.current.destroy();
      pcmPlayerRef.current = null;
    }
    
    isStreamingRef.current = false;
    setIsConnected(false);
    setIsListening(false);
    setIsSpeaking(false);
    setStatus('Session ended. Click to restart.');
    // Reset all transcripts on disconnect
    setTranscript('');
    setAiResponse('');
    setConversationHistory([]);
    setSarvamTranscript('');
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
      if (interruptionDebounceRef.current) clearTimeout(interruptionDebounceRef.current);
      if (sarvamRecorderRef.current) try { sarvamRecorderRef.current.stop(); } catch(e) {}
      if (workletNodeRef.current) workletNodeRef.current.disconnect();
      if (processorRef.current) processorRef.current.disconnect();
      if (wsRef.current) wsRef.current.close();
      if (mediaStreamRef.current) mediaStreamRef.current.getTracks().forEach(t => t.stop());
      if (audioContextRef.current) audioContextRef.current.close();
      if (pcmPlayerRef.current) pcmPlayerRef.current.destroy();
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
          
          {/* Sarvam Recording Controls */}
          {isConnected && (
            <div className="sarvam-controls">
              {!isRecordingForSarvam ? (
                <button 
                  className="sarvam-btn start"
                  onClick={startSarvamFullRecording}
                  disabled={isSarvamProcessing}
                >
                  🎤 Start Sarvam Recording
                </button>
              ) : (
                <button 
                  className="sarvam-btn stop"
                  onClick={stopAndTranscribeWithSarvam}
                  disabled={isSarvamProcessing}
                >
                  ⏹️ Stop & Transcribe with Sarvam
                </button>
              )}
              {isRecordingForSarvam && (
                <span className="recording-indicator">● Recording for Sarvam...</span>
              )}
            </div>
          )}
        </div>

        <div className="transcript-section">
          {/* Conversation History */}
          {conversationHistory.length > 0 && (
            <div className="conversation-history">
              <div className="history-header">Conversation History</div>
              {conversationHistory.map((entry, index) => (
                <div key={index} className={`transcript-box ${entry.type} history`}>
                  <span className="label">{entry.type === 'user' ? 'You:' : 'AI:'}</span>
                  <p>{entry.text}</p>
                </div>
              ))}
            </div>
          )}
          
          {/* Current Exchange */}
          {transcript && (
            <div className="transcript-box user current">
              <span className="label">You (GPT Realtime):</span>
              <p>{transcript}</p>
            </div>
          )}
          {(sarvamTranscript || isSarvamProcessing) && (
            <div className="transcript-box sarvam">
              <span className="label">You (Sarvam Sarika 2.5):</span>
              <p>{isSarvamProcessing ? '(Transcribing...)' : sarvamTranscript}</p>
            </div>
          )}
          {aiResponse && (
            <div className="transcript-box ai current">
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
