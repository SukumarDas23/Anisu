import os
import re
import urllib.parse
import yt_dlp
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from flask_cors import CORS

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

DOWNLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url = data.get('url', '').strip()

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'ignoreerrors': False,
        'js_runtimes': {'node': {'cmd': '/usr/bin/node'}},
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        },
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'android'],
            }
        },
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)

        # ── Build available quality tiers from formats ──
        video_heights = set()
        has_webm = False
        for f in info.get('formats', []):
            h = f.get('height')
            ext = f.get('ext', '')
            vcodec = f.get('vcodec', 'none')
            if h and vcodec != 'none':
                video_heights.add(h)
                if ext == 'webm':
                    has_webm = True

        # Standard tiers — keep only those available (or fallback to all)
        standard = [2160, 1440, 1080, 720, 480, 360]
        available_heights = sorted(
            [h for h in standard if any(abs(vh - h) <= 10 for vh in video_heights)],
            reverse=True
        )
        # Always include at least 720p and 1080p as fallback
        if not available_heights:
            available_heights = [1080, 720, 480, 360]

        def label(h):
            return '4K' if h == 2160 else f'{h}p'

        formats = []
        for h in available_heights:
            # MP4
            formats.append({
                'ext': 'mp4', 'quality': label(h),
                'height': h, 'type': 'video', 'filesize': None
            })

        if has_webm:
            for h in available_heights[:3]:  # top 3 qualities in WebM
                formats.append({
                    'ext': 'webm', 'quality': label(h),
                    'height': h, 'type': 'video', 'filesize': None
                })

        # Audio
        formats.append({
            'ext': 'mp3', 'quality': 'Best',
            'height': 0, 'type': 'audio', 'filesize': None
        })

        # ── Thumbnail (pick the best available) ──
        thumbnail = info.get('thumbnail', '')
        thumbnails = info.get('thumbnails', [])
        if thumbnails:
            # prefer maxresdefault or hqdefault
            for t in reversed(thumbnails):
                u = t.get('url', '')
                if 'maxresdefault' in u or 'hqdefault' in u:
                    thumbnail = u
                    break
            else:
                thumbnail = thumbnails[-1].get('url', thumbnail)

        return jsonify({
            'title':      info.get('title', 'Unknown Title'),
            'channel':    info.get('uploader', 'Unknown Channel'),
            'duration':   info.get('duration', 0),
            'thumbnail':  thumbnail,
            'view_count': info.get('view_count', 0),
            'formats':    formats,
            'url':        url,
        })

    except yt_dlp.utils.DownloadError as e:
        msg = str(e)
        if 'Sign in' in msg or 'age' in msg.lower():
            return jsonify({'error': 'This video requires sign-in or is age-restricted.'}), 403
        if 'Private' in msg:
            return jsonify({'error': 'This video is private.'}), 403
        return jsonify({'error': f'yt-dlp error: {msg}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/download', methods=['POST'])
def download_video():
    data = request.get_json()
    url      = data.get('url', '').strip()
    fmt_ext  = data.get('ext', 'mp4')
    quality  = data.get('quality', '720p')
    fmt_type = data.get('type', 'video')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        output_path = os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s')

        if fmt_type == 'audio':
            ydl_opts = {
                'format':    'bestaudio/best',
                'outtmpl':   output_path,
                'quiet':     True,
                'noplaylist': True,
                'js_runtimes': {'node': {'cmd': '/usr/bin/node'}},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                'extractor_args': {
                    'youtube': {'player_client': ['web', 'android']}
                },
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }
        else:
            height_val = quality.replace('p','').replace('4K','2160')
            ydl_opts = {
                'format':   (
                    f'bestvideo[height<={height_val}][ext={fmt_ext}]+bestaudio/best'
                    f'/bestvideo[height<={height_val}]+bestaudio/best'
                    f'/best[height<={height_val}]'
                    f'/best'
                ),
                'outtmpl':            output_path,
                'quiet':              True,
                'merge_output_format': fmt_ext,
                'noplaylist':         True,
                'js_runtimes': {'node': {'cmd': '/usr/bin/node'}},
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                },
                'extractor_args': {
                    'youtube': {'player_client': ['web', 'android']}
                },
            }

        downloaded_file = None

        class FilenameCapture:
            """Hook to capture the final output path."""
            def __call__(self, d):
                nonlocal downloaded_file
                if d['status'] == 'finished':
                    downloaded_file = d.get('filename') or d.get('info_dict', {}).get('_filename')

        ydl_opts['progress_hooks'] = [FilenameCapture()]

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if not downloaded_file:
                downloaded_file = ydl.prepare_filename(info)

        # For audio post-processing the extension changes
        if fmt_type == 'audio' and downloaded_file:
            base = os.path.splitext(downloaded_file)[0]
            mp3_path = base + '.mp3'
            if os.path.exists(mp3_path):
                downloaded_file = mp3_path

        # Fallback: scan downloads folder
        if not downloaded_file or not os.path.exists(downloaded_file):
            title = sanitize_filename(info.get('title', ''))[:30]
            for fname in sorted(os.listdir(DOWNLOAD_FOLDER), key=lambda f: -os.path.getmtime(os.path.join(DOWNLOAD_FOLDER, f))):
                if title[:15].lower() in fname.lower():
                    downloaded_file = os.path.join(DOWNLOAD_FOLDER, fname)
                    break
            else:
                # just take the newest file
                files = [os.path.join(DOWNLOAD_FOLDER, f) for f in os.listdir(DOWNLOAD_FOLDER)]
                if files:
                    downloaded_file = max(files, key=os.path.getmtime)

        if not downloaded_file or not os.path.exists(downloaded_file):
            return jsonify({'error': 'Downloaded file not found on server.'}), 500

        basename = os.path.basename(downloaded_file)
        filesize = os.path.getsize(downloaded_file)

        # Determine MIME from actual file extension
        actual_ext = os.path.splitext(basename)[1].lower()
        mime_map = {
            '.mp4': 'video/mp4', '.webm': 'video/webm',
            '.mkv': 'video/x-matroska', '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
        }
        mime = mime_map.get(actual_ext, 'application/octet-stream')

        # Safe ASCII filename for the header (strip non-latin1 chars)
        safe_name = basename.encode('ascii', 'ignore').decode('ascii').strip() or 'download' + actual_ext
        # RFC 5987 UTF-8 encoded filename as fallback for browsers that support it
        utf8_name = urllib.parse.quote(basename, safe='')
        content_disposition = (
            f"attachment; filename=\"{safe_name}\"; "
            f"filename*=UTF-8''{utf8_name}"
        )

        def generate():
            with open(downloaded_file, 'rb') as fh:
                while chunk := fh.read(65536):
                    yield chunk
            try:
                os.remove(downloaded_file)
            except Exception:
                pass

        return Response(
            stream_with_context(generate()),
            headers={
                'Content-Disposition': content_disposition,
                'Content-Type':        mime,
                'Content-Length':      str(filesize),
            }
        )

    except yt_dlp.utils.DownloadError as e:
        return jsonify({'error': f'Download failed: {e}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
