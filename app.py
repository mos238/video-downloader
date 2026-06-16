from flask import Flask, render_template, request, send_file, jsonify, session
from flask_cors import CORS
import yt_dlp
import os
import uuid
import re
import ssl
import certifi
import json
import urllib.request
from werkzeug.utils import secure_filename
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# SSL fix for yt-dlp
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

DOWNLOAD_FOLDER = 'downloads'
COOKIE_FOLDER = 'cookies'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(COOKIE_FOLDER, exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# YouTube oEmbed API endpoint
OEMBED_API = "https://www.youtube.com/oembed?url={}&format=json"

def clean_youtube_url(url):
    """Clean YouTube URL by removing tracking parameters"""
    url = url.strip()
    
    if 'youtu.be' in url:
        match = re.search(r'youtu\.be/([a-zA-Z0-9_-]+)', url)
        if match:
            video_id = match.group(1)
            return f'https://www.youtube.com/watch?v={video_id}'
    
    if 'youtube.com' in url:
        url = re.sub(r'[?&](si|feature|list|index|pp|is|emb|utm|ab_channel)=[^&]*', '', url)
        url = re.sub(r'[?&]$', '', url)
    
    return url

def get_cookie_path():
    cookie_file = session.get('cookie_file', '')
    if cookie_file and os.path.exists(cookie_file):
        return cookie_file
    return None

def get_video_info_oembed(url):
    """Get video information using YouTube's oEmbed API (no SSL issues)"""
    try:
        # Get video ID from URL
        video_id = None
        match = re.search(r'v=([a-zA-Z0-9_-]+)', url)
        if match:
            video_id = match.group(1)
        else:
            match = re.search(r'youtu\.be/([a-zA-Z0-9_-]+)', url)
            if match:
                video_id = match.group(1)
        
        if not video_id:
            return None
        
        # Use oEmbed API
        api_url = OEMBED_API.format(url)
        with urllib.request.urlopen(api_url, timeout=10) as response:
            data = json.loads(response.read().decode())
            
            # Get additional info from yt-dlp (for formats)
            formats = []
            try:
                ydl_opts = {
                    'quiet': True,
                    'no_warnings': True,
                    'nocheckcertificate': True,
                    'ignoreerrors': True,
                    'cookiefile': get_cookie_path() if get_cookie_path() else None,
                    'http_headers': {
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                    }
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    if info:
                        for f in info.get('formats', []):
                            if f.get('height') and f.get('ext') in ['mp4', 'webm']:
                                formats.append({
                                    'quality': f"{f['height']}p",
                                    'format_id': f['format_id'],
                                    'ext': f['ext'],
                                    'filesize': f.get('filesize', 0)
                                })
                        formats.sort(key=lambda x: int(x['quality'].replace('p', '')), reverse=True)
            except Exception as e:
                logger.warning(f"yt-dlp format fetch failed: {e}")
                # Fallback formats
                formats = [
                    {'quality': '1080p', 'format_id': 'bestvideo+bestaudio', 'ext': 'mp4', 'filesize': 0},
                    {'quality': '720p', 'format_id': 'bestvideo[height<=720]+bestaudio/best[height<=720]', 'ext': 'mp4', 'filesize': 0},
                    {'quality': '480p', 'format_id': 'bestvideo[height<=480]+bestaudio/best[height<=480]', 'ext': 'mp4', 'filesize': 0},
                ]
            
            return {
                'success': True,
                'title': data.get('title', 'Unknown'),
                'thumbnail': data.get('thumbnail_url', ''),
                'author_name': data.get('author_name', 'Unknown'),
                'video_id': video_id,
                'formats': formats
            }
    except Exception as e:
        logger.error(f"oEmbed API error: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload-cookie', methods=['POST'])
def upload_cookie():
    try:
        if 'cookie_file' not in request.files:
            return jsonify({'success': False, 'error': 'No file uploaded'}), 400
        
        file = request.files['cookie_file']
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        filename = secure_filename(f"cookies_{uuid.uuid4().hex[:8]}.txt")
        filepath = os.path.join(COOKIE_FOLDER, filename)
        file.save(filepath)
        
        with open(filepath, 'r') as f:
            content = f.read()
            if len(content) < 50:
                os.remove(filepath)
                return jsonify({'success': False, 'error': 'Cookie file appears empty'}), 400
        
        session['cookie_file'] = filepath
        logger.info(f"Cookie file uploaded: {filepath}")
        
        return jsonify({
            'success': True,
            'message': 'Cookie uploaded successfully!',
            'filename': filename,
            'size': len(content)
        })
    except Exception as e:
        logger.error(f"Upload error: {str(e)}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/clear-cookie', methods=['POST'])
def clear_cookie():
    try:
        cookie_file = session.get('cookie_file')
        if cookie_file and os.path.exists(cookie_file):
            os.remove(cookie_file)
        session.pop('cookie_file', None)
        return jsonify({'success': True, 'message': 'Cookie cleared'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/get-cookie-status', methods=['GET'])
def get_cookie_status():
    cookie_file = session.get('cookie_file')
    if cookie_file and os.path.exists(cookie_file):
        size = os.path.getsize(cookie_file)
        return jsonify({
            'has_cookie': True,
            'size': size,
            'size_mb': f"{size / 1024 / 1024:.2f} MB"
        })
    return jsonify({'has_cookie': False})

@app.route('/get-info', methods=['POST'])
def get_video_info():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400
    
    url = clean_youtube_url(url)
    logger.info(f"Fetching info for: {url}")
    
    # Try oEmbed API first (no SSL issues)
    result = get_video_info_oembed(url)
    if result and result.get('success'):
        return jsonify(result)
    
    # Fallback: try yt-dlp
    try:
        cookie_file = get_cookie_path()
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'geo_bypass': True,
            'cookiefile': cookie_file if cookie_file else None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                formats = []
                for f in info.get('formats', []):
                    if f.get('height') and f.get('ext') in ['mp4', 'webm']:
                        formats.append({
                            'quality': f"{f['height']}p",
                            'format_id': f['format_id'],
                            'ext': f['ext'],
                            'filesize': f.get('filesize', 0)
                        })
                formats.sort(key=lambda x: int(x['quality'].replace('p', '')), reverse=True)
                
                return jsonify({
                    'success': True,
                    'title': info.get('title', 'Unknown'),
                    'thumbnail': info.get('thumbnail', ''),
                    'author_name': info.get('uploader', 'Unknown'),
                    'video_id': info.get('id', ''),
                    'formats': formats[:10]
                })
    except Exception as e:
        logger.error(f"yt-dlp fallback error: {e}")
    
    return jsonify({'success': False, 'error': 'Could not fetch video info. Please try a different URL or use the Local Video Downloader.'}), 400

@app.route('/download', methods=['POST'])
def download_video():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400
    
    url = clean_youtube_url(url)
    logger.info(f"Downloading: {url}")
    
    cookie_file = get_cookie_path()
    
    filename = f"{uuid.uuid4().hex}.mp4"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    
    try:
        ydl_opts = {
            'format': format_id,
            'outtmpl': filepath,
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'geo_bypass': True,
            'cookiefile': cookie_file if cookie_file else None,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            }
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return send_file(
                filepath,
                as_attachment=True,
                download_name=f"youtube_video_{uuid.uuid4().hex[:8]}.mp4",
                mimetype='video/mp4'
            )
        else:
            return jsonify({'success': False, 'error': 'Download failed'}), 500
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Download error: {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 500
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
