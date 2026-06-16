from flask import Flask, render_template, request, send_file, jsonify, session
from flask_cors import CORS
import yt_dlp
import os
import uuid
import re
import ssl
import certifi
from werkzeug.utils import secure_filename
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Fix SSL certificate issues
os.environ['SSL_CERT_FILE'] = certifi.where()
os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

# Completely disable SSL verification for all requests
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# Also disable SSL for urllib3
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

DOWNLOAD_FOLDER = 'downloads'
COOKIE_FOLDER = 'cookies'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(COOKIE_FOLDER, exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

def clean_youtube_url(url):
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
                return jsonify({'success': False, 'error': 'Cookie file appears empty or invalid'}), 400
        
        session['cookie_file'] = filepath
        logger.info(f"Cookie file uploaded: {filepath}")
        
        return jsonify({
            'success': True,
            'message': 'Cookie file uploaded successfully!',
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
        return jsonify({'success': True, 'message': 'Cookie file cleared'})
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
    
    cookie_file = get_cookie_path()
    logger.info(f"Cookie file: {cookie_file}")
    
    try:
        # Use a different approach - fetch with direct HTTP and bypass SSL
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'geo_bypass': True,
            'cookiefile': cookie_file if cookie_file else None,
            # Add these headers to mimic a browser
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
                'Sec-Fetch-Mode': 'navigate',
            },
            # Add these to help with SSL issues
            'source_address': '0.0.0.0',
            'socket_timeout': 30,
            'retries': 5,
            'fragment_retries': 5,
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            if not info:
                return jsonify({'success': False, 'error': 'Could not fetch video info'}), 400
            
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
                'duration': info.get('duration', 0),
                'formats': formats[:10]
            })
            
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error: {error_msg}")
        
        # Provide more helpful error messages
        if 'SSL' in error_msg or 'certificate' in error_msg:
            error_msg = 'SSL certificate issue. The cookie file may not be valid. Please try: 1) Export fresh cookies 2) Use the Local Video Downloader instead.'
        elif 'Video unavailable' in error_msg:
            error_msg = 'Video is unavailable or private'
        elif 'Sign in' in error_msg:
            error_msg = 'Video requires login or is age-restricted. Please try a different cookie file.'
        elif 'rate limit' in error_msg.lower():
            error_msg = 'Rate limited. Please try again later'
        else:
            error_msg = f'Unable to fetch video. Error: {error_msg[:100]}'
        
        return jsonify({'success': False, 'error': error_msg}), 400

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
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-us,en;q=0.5',
            },
            'source_address': '0.0.0.0',
            'socket_timeout': 30,
            'retries': 5,
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
            return jsonify({'success': False, 'error': 'Download failed - file not created'}), 500
            
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
