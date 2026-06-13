# FBSave Pro - Full Stack Facebook Video Downloader

## Quick Start

### 1. Install Dependencies
```bash
pip install flask requests beautifulsoup4 lxml
```

### 2. Run the Server
```bash
python3 server.py
# OR
bash start.sh
```

### 3. Open in Browser
```
http://localhost:5000
```

---

## Project Structure
```
fbsavepro/
├── server.py           # Flask backend (extraction engine)
├── templates/
│   └── index.html      # Frontend UI (all-in-one)
├── static/             # Static assets (add CSS/JS/images here)
├── requirements.txt    # Python dependencies
├── start.sh            # Easy launch script
└── README.md           # This file
```

## API Endpoints

### POST /api/fetch
Fetch video download URLs.
```json
Request:  { "url": "https://facebook.com/...", "cookies": "c_user=...; xs=..." }
Response: { "success": true, "hd_url": "...", "sd_url": "...", "title": "...", "thumbnail": "...", "duration": "1:23" }
```

### GET /api/proxy-download
Stream video to browser (avoids CORS).
```
/api/proxy-download?url=<video_url>&filename=video.mp4
```

### GET /api/health
Health check.
```json
{ "status": "ok", "version": "2.0.0" }
```

## Video Extraction Patterns (7 methods)
1. browser_native_hd_url / browser_native_sd_url
2. hd_src_no_ratelimit / sd_src_no_ratelimit  
3. hd_src / sd_src (JSON)
4. playable_url / playable_url_quality_hd
5. og:video meta tag
6. HTML video src attribute
7. Full JSON blob mp4 URL sweep

## Deploy to Production
- Set `API_BASE` in index.html to your domain
- Use Nginx as reverse proxy in front of Flask
- Add SSL (Let's Encrypt)
- Run with gunicorn: `gunicorn -w 4 server:app`
