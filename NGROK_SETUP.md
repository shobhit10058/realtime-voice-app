# Sharing with ngrok - Setup Guide

## Overview

ngrok allows you to expose your local backend to the internet, making it accessible from anywhere. This is useful for:
- Testing on mobile devices
- Sharing with team members
- Demo purposes

## Prerequisites

1. Install ngrok: https://ngrok.com/download
2. Sign up for a free ngrok account (required for custom domains)
3. Get your ngrok auth token

## Setup Steps

### Step 1: Start Your Backend

```bash
cd realtime-voice-app/backend
python app.py
```

Backend should be running on `http://localhost:5000`

### Step 2: Start ngrok Tunnel

In a new terminal:

```bash
# Basic tunnel (random URL each time)
ngrok http 5000

# Or with custom domain (requires paid plan)
ngrok http 5000 --domain=your-custom-domain.ngrok-free.app
```

You'll see output like:
```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:5000
```

**Copy the HTTPS URL** (e.g., `https://abc123.ngrok-free.app`)

### Step 3: Update Frontend Configuration

The frontend needs to know to connect to the ngrok URL. You have two options:

#### Option A: Environment Variable (Recommended)

Create `.env` file in `realtime-voice-app/frontend/`:

```env
REACT_APP_BACKEND_URL=https://abc123.ngrok-free.app
```

Then restart the React dev server.

#### Option B: Manual URL Entry

The frontend will prompt you to enter the ngrok URL if it detects you're accessing via ngrok.

### Step 4: Start Frontend

```bash
cd realtime-voice-app/frontend
npm start
```

### Step 5: Access via ngrok

If you tunneled the frontend too, access it via the ngrok URL. Otherwise, access `http://localhost:3000` and it will connect to the ngrok backend.

## Important Notes

### WebSocket Support

✅ **ngrok supports WebSockets** - Your WebSocket connections will work through the tunnel.

### HTTPS Requirement

- ngrok provides HTTPS URLs
- Modern browsers require HTTPS for microphone access
- This is actually **better** than localhost for testing!

### ngrok Free Tier Limitations

- Random URLs change on restart
- Session time limits
- Bandwidth limits
- For production, consider ngrok paid plans or proper hosting

### Security

⚠️ **Warning**: Exposing your backend publicly means:
- Anyone with the URL can access it
- Your Azure API key is exposed (though it's in env vars)
- Consider using ngrok's authentication features:
  ```bash
  ngrok http 5000 --basic-auth="username:password"
  ```

## Troubleshooting

### WebSocket Connection Fails

1. Make sure you're using the **HTTPS** ngrok URL (not HTTP)
2. Check that ngrok is forwarding WebSocket connections (it should by default)
3. Verify backend is running on port 5000

### CORS Errors

The backend already has CORS enabled, so this shouldn't be an issue. If you see CORS errors:
- Make sure you're accessing via the ngrok HTTPS URL
- Check backend logs for CORS-related messages

### Microphone Not Working

- HTTPS is required for microphone access
- Make sure you're accessing via the ngrok HTTPS URL
- Check browser console for permission errors

## Alternative: Tunnel Both Frontend and Backend

If you want to share the entire app via one ngrok URL:

1. Build the frontend:
   ```bash
   cd realtime-voice-app/frontend
   npm run build
   ```

2. The backend already serves the built frontend if it exists in `frontend/build/`

3. Tunnel just the backend:
   ```bash
   ngrok http 5000
   ```

4. Access everything via the ngrok URL

## Quick Start Script

Create a file `start_with_ngrok.sh`:

```bash
#!/bin/bash

# Start backend in background
cd realtime-voice-app/backend
python app.py &
BACKEND_PID=$!

# Wait for backend to start
sleep 2

# Start ngrok
ngrok http 5000

# Cleanup on exit
kill $BACKEND_PID
```

Usage:
```bash
chmod +x start_with_ngrok.sh
./start_with_ngrok.sh
```

## Testing Checklist

- [ ] Backend starts successfully
- [ ] ngrok tunnel is active
- [ ] Frontend connects to ngrok backend URL
- [ ] WebSocket connection establishes
- [ ] Microphone permission granted
- [ ] Audio input works
- [ ] AI responses play correctly
- [ ] Interruption works

---

*For production deployment, consider using proper hosting (Vercel, Netlify, Railway, etc.) instead of ngrok.*

