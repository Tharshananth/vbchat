# Azure VM Deployment Guide

## Azure VM Configuration
- **Backend Port**: 8000
- **Frontend Port**: 8042
- **IP Address**: 172.16.68.4

---

## Backend Deployment (Port 8000)

### 1. Install Dependencies
```bash
cd backend
pip install -r requirements.txt
```

### 2. Setup Environment
```bash
# Copy and configure .env file
cp .env.example .env

# Add your API keys to .env:
# OPENAI_API_KEY=your_key
# ANTHROPIC_API_KEY=your_key
# GOOGLE_API_KEY=your_key
# etc.
```

### 3. Verify Database (Auto-Initializes)
Database will auto-initialize on first startup:
- Creates `data/database/feedback.db`
- Creates all required tables
- Initializes vector store (ChromaDB)

### 4. Run Backend
```bash
# Option A: Development (with auto-reload)
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

# Option B: Production (no reload)
uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

**Verify Backend**:
- Open: `http://172.16.68.4:8000/docs`
- Should see Swagger API documentation
- Click "Try it out" on health endpoint to test

---

## Frontend Deployment (Port 8042)

### 1. Install Dependencies
```bash
cd frontend
npm install
```

### 2. Setup Environment
```bash
# Configure API URL for Azure VM
# Verify .env.production has:
REACT_APP_API_URL=http://172.16.68.4:8000
```

### 3. Build Frontend
```bash
npm run build
```

This creates production-optimized build in `frontend/build/` directory.

### 4. Run Frontend on Port 8042

**Option A: Using `serve` package**
```bash
npm install -g serve
serve -s build -l 8042
```

**Option B: Using Node.js with custom port**
Create `frontend/server.js`:
```javascript
const express = require('express');
const path = require('path');
const app = express();

app.use(express.static(path.join(__dirname, 'build')));
app.get('/*', (req, res) => {
  res.sendFile(path.join(__dirname, 'build', 'index.html'));
});

app.listen(8042, '0.0.0.0', () => {
  console.log('Frontend running on http://0.0.0.0:8042');
});
```

Then run:
```bash
npm install express
node server.js
```

**Verify Frontend**:
- Open: `http://172.16.68.4:8042`
- Should see chatbot UI
- Try sending a message (should connect to backend on port 8000)

---

## Testing Checklist

- [ ] Backend starts without errors
- [ ] `http://172.16.68.4:8000/docs` loads Swagger UI
- [ ] Frontend builds successfully
- [ ] Frontend loads on `http://172.16.68.4:8042`
- [ ] Can send message from frontend chatbot
- [ ] Backend logs show incoming message
- [ ] Bot responds with LLM output
- [ ] Feedback buttons work (thumbs up/down)

---

## Troubleshooting

### Backend won't start
```bash
# Check if port 8000 is in use
netstat -tlnp | grep 8000

# Kill process on port 8000
lsof -ti:8000 | xargs kill -9  # Linux/Mac
taskkill /pid <PID> /f         # Windows
```

### Frontend can't connect to backend
- Verify backend is running on port 8000
- Check API_BASE_URL in frontend .env matches: `http://172.16.68.4:8000`
- Ensure CORS is enabled in backend config.yaml
- Check browser console for exact error

### Database errors
- Delete `data/database/feedback.db` and restart (will auto-recreate)
- Check `logs/` directory for detailed errors
- Ensure `data/database/` directory has write permissions

### LLM provider errors
- Verify API keys are set in .env
- Check which provider is set as default in `config.yaml`
- View backend logs to see which provider was tried

---

## Environment Files Overview

| File | Purpose | Location |
|------|---------|----------|
| `.env.example` (backend) | Template for backend config | `backend/` |
| `.env` (backend) | Actual config with API keys | `backend/` (create from example) |
| `.env.production` (frontend) | Production API URL | `frontend/` |
| `config.yaml` | Application settings | `backend/` |

---

## Performance Notes

- Vector DB (ChromaDB) loads on startup
- Documents auto-load from `data/directory` on first run
- Rate limiting enabled: prevent abuse
- GZip compression enabled: reduce bandwidth
- Database uses SQLite (suitable for testing, consider migration for production)

---

## When Ready for Production

For production beyond testing:
1. Switch to PostgreSQL (currently using SQLite)
2. Add proper SSL/TLS certificates
3. Configure Redis for session caching
4. Add authentication/authorization
5. Implement request signing
6. Set up proper monitoring and alerting
