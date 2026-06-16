from flask import Flask, render_template, request, jsonify, session, send_file
from flask_cors import CORS
import yt_dlp
import os
import uuid
import re
import json
from werkzeug.utils import secure_filename
import logging

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

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/get-info', methods=['POST'])
def get_video_info():
    data = request.json
    url = data.get('url')
    
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400
    
    url = clean_youtube_url(url)
    logger.info(f"Fetching info for: {url}")
    
    try:
        # Use the working method from your script
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': 'only_download',
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
                'uploader': info.get('uploader', 'Unknown'),
                'duration': info.get('duration', 0),
                'formats': formats[:10]
            })
            
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 400

@app.route('/download', methods=['POST'])
def download_video():
    data = request.json
    url = data.get('url')
    format_id = data.get('format_id')
    
    if not url:
        return jsonify({'success': False, 'error': 'No URL provided'}), 400
    
    url = clean_youtube_url(url)
    
    filename = f"{uuid.uuid4().hex}.mp4"
    filepath = os.path.join(DOWNLOAD_FOLDER, filename)
    
    try:
        ydl_opts = {
            'format': format_id,
            'outtmpl': filepath,
            'quiet': True,
            'no_warnings': True,
            'ignoreerrors': 'only_download',
            'extractor_args': {
                'youtube': {
                    'player_client': ['android_sdkless', 'web_safari'],
                    'skip': ['ios', 'web'],
                }
            },
            'js_runtimes': 'node',
            'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'referer': 'https://www.youtube.com/',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        if os.path.exists(filepath) and os.path.getsize(filepath) > 0:
            return send_file(
                filepath,
                as_attachment=True,
                download_name=f"video_{uuid.uuid4().hex[:8]}.mp4",
                mimetype='video/mp4'
            )
        else:
            return jsonify({'success': False, 'error': 'Download failed'}), 500
            
    except Exception as e:
        logger.error(f"Download error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except:
                pass

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
