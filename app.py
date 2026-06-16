from flask import Flask, render_template, request, send_file, jsonify, session
from flask_cors import CORS
import yt_dlp
import os
import uuid
import re
import json
import urllib.request
from werkzeug.utils import secure_filename
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

DOWNLOAD_FOLDER = 'downloads'
COOKIE_FOLDER = 'cookies'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(COOKIE_FOLDER, exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024

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

def get_video_info_multimethod(url):
    """
    Get video information using multiple methods (from your proven script)
    Starts with the method that works first!
    """
    url = clean_youtube_url(url)
    logger.info(f"Fetching info for: {url}")
    
    # Method 1: Android SDK-less (proven to work without PO token)
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': 'only_download',
        'retries': 2,
        'extract_flat': False,
        'extractor_args': {
            'youtube': {
                'player_client': ['android_sdkless', 'web_safari'],
                'skip': ['ios', 'web'],
            }
        },
        'js_runtimes': 'node',
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'referer': 'https://www.youtube.com/',
        'http_headers': {
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }
    
    try:
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
                            'filesize': f.get('filesize', 0),
                            'width': f.get('width', 0)
                        })
                formats.sort(key=lambda x: int(x['quality'].replace('p', '')), reverse=True)
                
                return {
                    'success': True,
                    'title': info.get('title', 'Unknown'),
                    'thumbnail': info.get('thumbnail', ''),
                    'uploader': info.get('uploader', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'formats': formats[:10],
                    'description': info.get('description', '')[:500],
                    'method': 'android_sdkless'
                }
    except Exception as e:
        logger.warning(f"Method 1 failed: {e}")
    
    # Method 2: Mobile fallback
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'ignoreerrors': 'only_download',
        'retries': 3,
        'extract_flat': False,
        'extractor_args': {
            'youtube': {
                'player_client': ['android'],
                'skip': ['dash', 'hls'],
            }
        },
        'user_agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
        'referer': 'https://m.youtube.com/',
    }
    
    try:
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
                            'filesize': f.get('filesize', 0),
                            'width': f.get('width', 0)
                        })
                formats.sort(key=lambda x: int(x['quality'].replace('p', '')), reverse=True)
                
                return {
                    'success': True,
                    'title': info.get('title', 'Unknown'),
                    'thumbnail': info.get('thumbnail', ''),
                    'uploader': info.get('uploader', 'Unknown'),
                    'duration': info.get('duration', 0),
                    'formats': formats[:10],
                    'description': info.get('description', '')[:500],
                    'method': 'mobile'
                }
    except Exception as e:
        logger.warning(f"Method 2 failed: {e}")
    
    return {'success': False, 'error': 'Could not fetch video info using any method'}

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
    
    # Use multi-method approach
    result = get_video_info_multimethod(url)
    if result.get('success'):
        return jsonify(result)
    
    return jsonify({'success': False, 'error': result.get('error', 'Could not fetch video info')}), 400

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
        # Use the proven format from your script
        if format_id == 'best':
            format_spec = 'bestvideo+bestaudio/best'
        else:
            format_spec = format_id
        
        ydl_opts = {
            'format': format_spec,
            'outtmpl': filepath,
            'quiet': False,
            'no_warnings': True,
            'ignoreerrors': 'only_download',
            'retries': 2,
            'merge_output_format': 'mp4',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_sdkless', 'web_safari'],
                    'skip': ['ios', 'web'],
                }
            },
            'js_runtimes': 'node',
            'cookiefile': cookie_file if cookie_file else None,
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': 'https://www.youtube.com/',
            'http_headers': {
                'Accept': '*/*',
                'Accept-Language': 'en-US,en;q=0.9',
            },
            'sleep_interval': 0,
            'max_sleep_interval': 0,
            'throttled_rate': 0,
            'progress_hooks': [lambda d: logger.info(f"Download progress: {d.get('_percent_str', '')}")],
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
