from flask import Flask, render_template, request, jsonify, session, send_file
from flask_cors import CORS
import os
import uuid
import re
import json
import subprocess
import logging
from werkzeug.utils import secure_filename

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)
CORS(app)

DOWNLOAD_FOLDER = 'downloads'
COOKIE_FOLDER = 'cookies'
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)
os.makedirs(COOKIE_FOLDER, exist_ok=True)

def clean_youtube_url(url):
    url = url.strip()
    if 'youtu.be' in url:
        match = re.search(r'youtu\.be/([a-zA-Z0-9_-]+)', url)
        if match:
            return f'https://www.youtube.com/watch?v={match.group(1)}'
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
    
    cookie_file = get_cookie_path()
    
    try:
        # Use the exact same command that works in terminal
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '--quiet',
            '--dump-json',
            '--no-check-certificate',
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        ]
        
        if cookie_file and os.path.exists(cookie_file):
            cmd.extend(['--cookies', cookie_file])
        
        cmd.append(url)
        
        logger.info(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode != 0:
            logger.error(f"yt-dlp error: {result.stderr}")
            return jsonify({'success': False, 'error': 'Failed to fetch video info'}), 400
        
        info = json.loads(result.stdout)
        
        # Get formats from the JSON
        formats = []
        seen_qualities = set()
        
        for f in info.get('formats', []):
            height = f.get('height')
            if height and f.get('vcodec') != 'none':
                quality = f"{height}p"
                if quality not in seen_qualities:
                    seen_qualities.add(quality)
                    # Get combined format for best quality
                    format_id = f['format_id']
                    # Add audio if available
                    if f.get('acodec') != 'none':
                        format_id = f"{format_id}+bestaudio"
                    formats.append({
                        'quality': quality,
                        'format_id': format_id,
                        'ext': f.get('ext', 'mp4'),
                        'filesize': f.get('filesize', 0),
                        'has_audio': f.get('acodec') != 'none'
                    })
        
        # Sort by quality (highest first)
        formats.sort(key=lambda x: int(x['quality'].replace('p', '')), reverse=True)
        
        # If no formats found, add common ones as fallback
        if not formats:
            formats = [
                {'quality': '1080p', 'format_id': '137+140', 'ext': 'mp4', 'filesize': 0, 'has_audio': True},
                {'quality': '720p', 'format_id': '136+140', 'ext': 'mp4', 'filesize': 0, 'has_audio': True},
                {'quality': '480p', 'format_id': '135+140', 'ext': 'mp4', 'filesize': 0, 'has_audio': True},
                {'quality': '360p', 'format_id': '134+140', 'ext': 'mp4', 'filesize': 0, 'has_audio': True},
            ]
        
        return jsonify({
            'success': True,
            'title': info.get('title', 'Unknown'),
            'thumbnail': info.get('thumbnail', ''),
            'uploader': info.get('uploader', 'Unknown'),
            'duration': info.get('duration', 0),
            'formats': formats[:10]
        })
        
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Request timed out'}), 400
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Error: {error_msg}")
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
        cmd = [
            'yt-dlp',
            '--no-warnings',
            '--quiet',
            '--no-check-certificate',
            '--format', format_id,
            '--output', filepath,
            '--user-agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        ]
        
        if cookie_file and os.path.exists(cookie_file):
            cmd.extend(['--cookies', cookie_file])
        
        cmd.append(url)
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
        
        if result.returncode != 0:
            logger.error(f"Download error: {result.stderr}")
            return jsonify({'success': False, 'error': 'Download failed'}), 500
        
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return send_file(
                filepath,
                as_attachment=True,
                download_name=f"video_{uuid.uuid4().hex[:8]}.mp4",
                mimetype='video/mp4'
            )
        else:
            return jsonify({'success': False, 'error': 'Download failed'}), 500
            
    except subprocess.TimeoutExpired:
        return jsonify({'success': False, 'error': 'Download timed out'}), 500
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
