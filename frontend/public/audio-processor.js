/**
 * AudioWorklet Processor for capturing microphone input
 * Replaces deprecated ScriptProcessorNode
 */
class AudioCaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.bufferSize = 4096;
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;

    const channelData = input[0];
    if (!channelData) return true;

    // Accumulate samples into buffer
    for (let i = 0; i < channelData.length; i++) {
      this.buffer[this.bufferIndex++] = channelData[i];

      // When buffer is full, send it to main thread
      if (this.bufferIndex >= this.bufferSize) {
        // Copy buffer to send (since we'll reuse the original)
        const audioData = this.buffer.slice(0);
        this.port.postMessage({ audioData });
        this.bufferIndex = 0;
      }
    }

    return true;
  }
}

registerProcessor('audio-capture-processor', AudioCaptureProcessor);

