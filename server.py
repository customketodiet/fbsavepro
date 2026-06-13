#!/usr/bin/env python3
"""FBSave Pro - Backend Server"""

import re, json, html, time, logging, urllib.parse
from flask import Flask, request, jsonify, send_from_directory, Response
import requests
from bs4 import BeautifulSoup

app = Flask(__name__, static_folder="static", template_folder="templates")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

DESKTOP_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
MOBILE_UA  = ("Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36")

BASE_HEADERS = {
    "User-Agent": DESKTOP_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Cache-Control": "max-age=0",
}

SESSION_TIMEOUT   = 15
MAX_CONTENT_SIZE  = 10 * 1024 * 1024

@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response

@app.route("/api/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return jsonify({}), 200

def normalize_fb_url(url):
    url = url.strip()
    if "fb.watch" in url:
        return url
    url = re.sub(r"https?://(m\.|mbasic\.|touch\.)?facebook\.com", "https://www.facebook.com", url)
    if not url.startswith("http"):
        url = "https://" + url
    return url

def is_fb_url(url):
    try:
        p = urllib.parse.urlparse(url)
        return bool(re.search(r"(facebook\.com|fb\.watch|fb\.com)", p.netloc))
    except Exception:
        return False

def unescape_fb_url(raw):
    return raw.replace("\\/", "/").replace("\\u0025", "%").strip().strip('"').strip("'")

def extract_video_urls(page_html):
    result = {"hd_url": None, "sd_url": None, "title": "Facebook Video", "duration": None, "thumbnail": None}

    # Pattern 1: browser_native_hd_url / browser_native_sd_url
    for key, field in [("hd_url", "browser_native_hd_url"), ("sd_url", "browser_native_sd_url")]:
        if not result[key]:
            m = re.search(rf'"{field}"\s*:\s*"([^"]+)"', page_html)
            if m:
                result[key] = unescape_fb_url(m.group(1))

    # Pattern 2: hd_src_no_ratelimit / sd_src_no_ratelimit
    for key, field in [("hd_url", "hd_src_no_ratelimit"), ("sd_url", "sd_src_no_ratelimit")]:
        if not result[key]:
            m = re.search(rf'"{field}"\s*:\s*"([^"]+)"', page_html)
            if m:
                result[key] = unescape_fb_url(m.group(1))

    # Pattern 3: hd_src / sd_src
    for key, field in [("hd_url", "hd_src"), ("sd_url", "sd_src")]:
        if not result[key]:
            m = re.search(rf'"{field}"\s*:\s*"([^"]+\.mp4[^"]*)"', page_html)
            if m:
                result[key] = unescape_fb_url(m.group(1))

    # Pattern 4: playable_url / playable_url_quality_hd
    for key, field in [("sd_url", "playable_url"), ("hd_url", "playable_url_quality_hd")]:
        if not result[key]:
            m = re.search(rf'"{field}"\s*:\s*"([^"]+)"', page_html)
            if m:
                url = unescape_fb_url(m.group(1))
                if url and ".mp4" in url:
                    result[key] = url

    # Pattern 5: og:video meta tag
    if not result["sd_url"] and not result["hd_url"]:
        m = re.search(r'<meta\s+property="og:video"\s+content="([^"]+)"', page_html)
        if m:
            result["sd_url"] = unescape_fb_url(m.group(1))

    # Pattern 6: video src in HTML
    if not result["sd_url"]:
        m = re.search(r'<video[^>]+src="([^"]+\.mp4[^"]*)"', page_html)
        if m:
            result["sd_url"] = unescape_fb_url(m.group(1))

    # Pattern 7: JSON blob sweep for .mp4 URLs (unescape first, then search)
    if not result["hd_url"] or not result["sd_url"]:
        # Unescape the entire page first to normalize all URL variants
        unescaped_html = page_html.replace("\\/", "/").replace("\\u002F", "/").replace("\\u003A", ":")
        all_mp4s = re.findall(r'https?://[^\s"\'<>\\]+?\.mp4[^\s"\'<>\\]*', unescaped_html)
        cleaned = []
        for u in all_mp4s:
            u2 = u.strip().rstrip('",\'')
            if "facebook.com" in u2 or "fbcdn.net" in u2 or "cdninstagram.com" in u2:
                cleaned.append(u2)
        cleaned = sorted(set(cleaned), key=lambda x: len(x), reverse=True)
        if cleaned and not result["hd_url"]:
            result["hd_url"] = cleaned[0]
        if len(cleaned) > 1 and not result["sd_url"]:
            result["sd_url"] = cleaned[1]
        elif cleaned and not result["sd_url"]:
            result["sd_url"] = cleaned[0]

    # Title
    m = re.search(r'<meta\s+(?:property="og:title"|name="title")\s+content="([^"]*)"', page_html)
    if m:
        result["title"] = html.unescape(m.group(1))
    else:
        m = re.search(r"<title>([^<]+)</title>", page_html)
        if m:
            result["title"] = html.unescape(m.group(1).replace(" | Facebook", "").strip())

    # Thumbnail
    m = re.search(r'<meta\s+property="og:image"\s+content="([^"]+)"', page_html)
    if m:
        result["thumbnail"] = unescape_fb_url(m.group(1))

    # Duration
    m = re.search(r'"duration"\s*:\s*(\d+)', page_html)
    if m:
        result["duration"] = int(m.group(1))

    # Deduplicate
    if result["hd_url"] and result["sd_url"] and result["hd_url"] == result["sd_url"]:
        result["hd_url"] = None

    return result

def fetch_page(url, cookies_str=""):
    session = requests.Session()
    headers = dict(BASE_HEADERS)
    if cookies_str.strip():
        cookie_dict = {}
        for part in cookies_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                cookie_dict[k.strip()] = v.strip()
        session.cookies.update(cookie_dict)
        headers["Cookie"] = cookies_str
        log.info(f"Using cookies: {list(cookie_dict.keys())}")
    try:
        resp = session.get(url, headers=headers, timeout=SESSION_TIMEOUT, allow_redirects=True, stream=True)
        content = b""
        for chunk in resp.iter_content(chunk_size=65536):
            content += chunk
            if len(content) > MAX_CONTENT_SIZE:
                break
        page_html = content.decode("utf-8", errors="replace")
        log.info(f"Fetched: {resp.status_code} | {len(page_html)} bytes | {resp.url}")
        return page_html
    except requests.exceptions.Timeout:
        raise ValueError("Request timed out. Facebook may be slow or blocking the connection.")
    except requests.exceptions.ConnectionError as e:
        raise ValueError(f"Connection error: {str(e)}")

def fetch_page_mobile(url, cookies_str=""):
    mobile_url = url.replace("www.facebook.com", "m.facebook.com")
    session = requests.Session()
    headers = dict(BASE_HEADERS)
    headers["User-Agent"] = MOBILE_UA
    if cookies_str.strip():
        headers["Cookie"] = cookies_str
        for part in cookies_str.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                session.cookies.set(k.strip(), v.strip())
    resp = session.get(mobile_url, headers=headers, timeout=SESSION_TIMEOUT, allow_redirects=True, stream=True)
    content = b""
    for chunk in resp.iter_content(chunk_size=65536):
        content += chunk
        if len(content) > MAX_CONTENT_SIZE:
            break
    return content.decode("utf-8", errors="replace")

def fmt_duration(seconds):
    if not seconds:
        return None
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"

@app.route("/")
def index():
    return send_from_directory("templates", "index.html")

@app.route("/api/fetch", methods=["POST"])
def api_fetch():
    try:
        body = request.get_json(force=True, silent=True) or {}
        url = (body.get("url") or "").strip()
        cookies = (body.get("cookies") or "").strip()

        if not url:
            return jsonify({"success": False, "error": "No URL provided."}), 400
        if not is_fb_url(url):
            return jsonify({"success": False, "error": "Invalid URL. Please provide a valid Facebook video link."}), 400

        url = normalize_fb_url(url)
        log.info(f"Processing: {url}")

        page_html = fetch_page(url, cookies)
        data = extract_video_urls(page_html)

        if not data["hd_url"] and not data["sd_url"]:
            log.info("Trying mobile fallback...")
            try:
                mobile_html = fetch_page_mobile(url, cookies)
                data = extract_video_urls(mobile_html)
            except Exception as e:
                log.warning(f"Mobile fallback failed: {e}")

        if not data["hd_url"] and not data["sd_url"]:
            if "login" in page_html.lower() and not cookies:
                return jsonify({
                    "success": False,
                    "error": "This video is private or login-required. Switch to the 'Private Video' tab and provide your Facebook session cookies."
                }), 403
            return jsonify({
                "success": False,
                "error": "Could not extract download links. The video may be private, geo-restricted, or not a direct video post."
            }), 422

        return jsonify({
            "success": True,
            "title": data["title"] or "Facebook Video",
            "thumbnail": data["thumbnail"],
            "duration": fmt_duration(data.get("duration")),
            "hd_url": data["hd_url"],
            "sd_url": data["sd_url"],
        })

    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 422
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
        return jsonify({"success": False, "error": f"Server error: {str(e)}"}), 500

@app.route("/api/proxy-download")
def proxy_download():
    video_url = request.args.get("url", "").strip()
    filename  = request.args.get("filename", "fbsavepro_video.mp4")
    if not video_url:
        return jsonify({"error": "No URL"}), 400
    allowed_hosts = ["fbcdn.net", "facebook.com", "cdninstagram.com", "akamaized.net"]
    try:
        parsed = urllib.parse.urlparse(video_url)
        if not any(h in parsed.netloc for h in allowed_hosts):
            return jsonify({"error": "Unauthorized source."}), 403
    except Exception:
        return jsonify({"error": "Invalid URL"}), 400
    try:
        headers = {"User-Agent": DESKTOP_UA, "Accept": "*/*",
                   "Accept-Encoding": "identity", "Referer": "https://www.facebook.com/"}
        if "Range" in request.headers:
            headers["Range"] = request.headers["Range"]
        upstream = requests.get(video_url, headers=headers, stream=True, timeout=30)
        def generate():
            for chunk in upstream.iter_content(chunk_size=65536):
                if chunk:
                    yield chunk
        resp_headers = {
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Type": upstream.headers.get("Content-Type", "video/mp4"),
            "Accept-Ranges": "bytes",
        }
        if "Content-Length" in upstream.headers:
            resp_headers["Content-Length"] = upstream.headers["Content-Length"]
        if "Content-Range" in upstream.headers:
            resp_headers["Content-Range"] = upstream.headers["Content-Range"]
        status = upstream.status_code if upstream.status_code in (200, 206) else 200
        return Response(generate(), status=status, headers=resp_headers)
    except Exception as e:
        log.error(f"Proxy error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "version": "2.0.0", "timestamp": int(time.time())})

if __name__ == "__main__":
    print("\n" + "="*55)
    print("  FBSave Pro  -  http://localhost:5000")
    print("="*55 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
