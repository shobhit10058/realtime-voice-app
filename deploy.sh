#!/bin/bash
# Deployment script for Replit

echo "🚀 Building and deploying Realtime Voice App..."

# Install backend dependencies
echo "📦 Installing Python dependencies..."
cd backend
pip install -r requirements.txt

# Build frontend
echo "⚛️ Building React frontend..."
cd ../frontend
npm install
npm run build

# Start backend (serves frontend too)
echo "🎯 Starting server..."
cd ../backend
python app.py

