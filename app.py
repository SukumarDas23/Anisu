import os
import re
import time
import urllib.parse
import yt_dlp
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from flask_cors import CORS

app = Flask(__name__, template_folder='templates', static_folder='static')
CORS(app)

DOWNLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'downloads')
os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)

# ── Browser headers ─────────────────────────────────────────────────────────
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/131.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-US,en;q=0.9',
}

# ── Base yt-dlp options (no client override — use yt-dlp default) ────────────
YDL_BASE = {
    'quiet':       True,
    'no_warnings': True,
    'http_headers': HEADERS,
    'js_runtimes': {'node': {'cmd': '/usr/bin/node'}},
}


def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "", name)


def normalize_height(h):
    """Map pixel height to a clean quality label."""
    if h >= 2000: return 2160, '4K'
    if h >= 1300: return 1440, '1440p'
    if h >= 900:  return 1080, '1080p'
    if h >= 600:  return 720,  '720p'
    if h >= 400:  return 480,  '480p'
    if h >= 260:  return 360,  '360p'
    if h >= 180:  return 240,  '240p'
    return 144, '144p'


def make_ydl_opts(extra=None, with_cookies=True):
    """Build yt-dlp options, optionally adding Firefox cookies."""
    opts = {**YDL_BASE}
    if with_cookies:
        try:
            # Only use cookies if Firefox cookie DB is accessible
            firefox_profile = os.path.expanduser('~/.mozilla/firefox')
            if os.path.exists(firefox_profile):
                opts['cookiesfrombrowser'] = ('firefox',)
        except Exception:
            pass
    if extra:
        opts.update(extra)
    return opts


def extract_info_robust(url):
    """Try to extract video info with multiple fallback strategies."""
    errors = []

    # Strategy 1: Default client + cookies (best quality detection)
    try:
        opts = make_ydl_opts({'skip_download': True}, with_cookies=True)
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        errors.append(f'[cookies] {e}')

    # Strategy 2: Default client without cookies
    try:
        opts = make_ydl_opts({'skip_download': True}, with_cookies=False)
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        errors.append(f'[no-cookies] {e}')

    # Strategy 3: android+web client (older but sometimes works)
    try:
        opts = make_ydl_opts({
            'skip_download': True,
            'extractor_args': {'youtube': {'player_client': ['android', 'web']}},
        }, with_cookies=False)
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception as e:
        errors.append(f'[android] {e}')

    raise RuntimeError(' | '.join(errors))


def download_robust(url, fmt_str, merge_ext, output_path, post_processors=None):
    """Try downloading with multiple fallback strategies."""
    errors = []

    configs = [
        # Strategy 1: With cookies + node.js
        make_ydl_opts({
            'format': fmt_str,
            'outtmpl': output_path,
            'noplaylist': True,
            'merge_output_format': merge_ext,
        }, with_cookies=True),
        # Strategy 2: Without cookies
        make_ydl_opts({
            'format': fmt_str,
            'outtmpl': output_path,
            'noplaylist': True,
            'merge_output_format': merge_ext,
        }, with_cookies=False),
        # Strategy 3: Fallback to 'best' (combined stream, no merge needed)
        make_ydl_opts({
            'format': 'best',
            'outtmpl': output_path,
            'noplaylist': True,
        }, with_cookies=False),
    ]

    for cfg in configs:
        if post_processors:
            cfg['postprocessors'] = post_processors

        downloaded_file = None

        def _hook(d):
            nonlocal downloaded_file
            if d['status'] == 'finished':
                downloaded_file = (
                    d.get('filename') or
                    d.get('info_dict', {}).get('_filename')
                )

        cfg['progress_hooks'] = [_hook]

        try:
            with yt_dlp.YoutubeDL(cfg) as ydl:
                info = ydl.extract_info(url, download=True)
                if not downloaded_file:
                    downloaded_file = ydl.prepare_filename(info)
            return downloaded_file, info
        except Exception as e:
            msg = str(e)
            errors.append(msg)
            # Don't retry on private/age-restricted — it won't help
            if 'Private' in msg or 'age' in msg.lower():
                break
            # Brief pause before retry
            time.sleep(1)

    raise RuntimeError(' | '.join(errors))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        info = extract_info_robust(url)

        # ── Build format list from REAL yt-dlp formats ──
        best_video = {}

        for f in info.get('formats', []):
            height = f.get('height')
            ext    = f.get('ext', '')
            vcodec = f.get('vcodec', 'none')
            proto  = f.get('protocol', '')
            fid    = f.get('format_id', '')
            has_url = bool(f.get('url'))

            # Include https + m3u8_native (HLS) — both have real download URLs
            if (height and vcodec != 'none'
                    and ext in ('mp4', 'webm')
                    and has_url
                    and proto in ('https', 'm3u8_native', 'http')):
                _, label = normalize_height(height)
                key = (ext, label)
                tbr = f.get('tbr') or 0
                existing = best_video.get(key)
                if not existing or tbr > (existing.get('tbr') or 0):
                    best_video[key] = {
                        'format_id': fid,
                        'ext':       ext,
                        'quality':   label,
                        'height':    height,
                        'type':      'video',
                        'filesize':  f.get('filesize') or f.get('filesize_approx'),
                        'tbr':       tbr,
                    }

        # Sort: MP4 first (highest→lowest), then WebM
        ext_order = {'mp4': 0, 'webm': 1}
        formats = sorted(
            best_video.values(),
            key=lambda x: (ext_order.get(x['ext'], 9), -(x.get('height') or 0))
        )

        # Add MP3 audio option
        formats.append({
            'format_id': 'bestaudio/best',
            'ext':       'mp3',
            'quality':   'Best',
            'height':    0,
            'type':      'audio',
            'filesize':  None,
        })

        # ── Best thumbnail ──
        thumbnail  = info.get('thumbnail', '')
        thumbnails = info.get('thumbnails', [])
        if thumbnails:
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

    except Exception as e:
        msg = str(e)
        if 'Sign in' in msg or 'bot' in msg.lower():
            return jsonify({'error': 'YouTube bot check triggered. Open YouTube in Firefox, sign in, then retry.'}), 403
        if 'Private' in msg:
            return jsonify({'error': 'This video is private.'}), 403
        if '429' in msg or 'Too Many' in msg:
            return jsonify({'error': 'Too many requests — YouTube is rate limiting. Please wait 1–2 minutes and retry.'}), 429
        return jsonify({'error': f'Could not fetch video: {msg[:200]}'}), 500


@app.route('/api/download', methods=['POST'])
def download_video():
    data     = request.get_json()
    url      = data.get('url', '').strip()
    fmt_ext  = data.get('ext', 'mp4')
    quality  = data.get('quality', '720p')
    fmt_type = data.get('type', 'video')

    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        output_path = os.path.join(DOWNLOAD_FOLDER, '%(title)s.%(ext)s')

        if fmt_type == 'audio':
            fmt_str        = 'bestaudio/best'
            post_processors = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }]
            merge_ext = 'mp3'
        else:
            post_processors = []
            height_val = quality.replace('p', '').replace('4K', '2160')
            try:
                height_int = int(height_val)
            except ValueError:
                height_int = 720

            # Robust format string: tries preferred ext → any ext → combined
            fmt_str = (
                f'bestvideo[height<={height_int}][ext={fmt_ext}]+bestaudio[ext=m4a]'
                f'/bestvideo[height<={height_int}][ext={fmt_ext}]+bestaudio'
                f'/bestvideo[height<={height_int}]+bestaudio'
                f'/best[height<={height_int}]'
                f'/best'
            )
            merge_ext = fmt_ext

        downloaded_file, info = download_robust(
            url, fmt_str, merge_ext, output_path, post_processors
        )

        # Audio: extension changes after FFmpeg post-processing
        if fmt_type == 'audio' and downloaded_file:
            base = os.path.splitext(downloaded_file)[0]
            if os.path.exists(base + '.mp3'):
                downloaded_file = base + '.mp3'

        # Fallback: scan downloads folder for newest matching file
        if not downloaded_file or not os.path.exists(downloaded_file):
            title_key = sanitize_filename(info.get('title', ''))[:20].lower()
            all_files = [
                os.path.join(DOWNLOAD_FOLDER, f)
                for f in os.listdir(DOWNLOAD_FOLDER)
            ]
            candidates = [f for f in all_files if title_key in os.path.basename(f).lower()]
            if candidates:
                downloaded_file = max(candidates, key=os.path.getmtime)
            elif all_files:
                downloaded_file = max(all_files, key=os.path.getmtime)

        if not downloaded_file or not os.path.exists(downloaded_file):
            return jsonify({'error': 'Downloaded file not found on server.'}), 500

        basename   = os.path.basename(downloaded_file)
        filesize   = os.path.getsize(downloaded_file)
        actual_ext = os.path.splitext(basename)[1].lower()
        mime_map   = {
            '.mp4': 'video/mp4', '.webm': 'video/webm',
            '.mkv': 'video/x-matroska', '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
        }
        mime = mime_map.get(actual_ext, 'application/octet-stream')

        # Safe latin-1 filename + RFC 5987 UTF-8 fallback
        safe_name = basename.encode('ascii', 'ignore').decode('ascii').strip()
        if not safe_name:
            safe_name = f'download{actual_ext}'
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

    except Exception as e:
        msg = str(e)
        if 'Sign in' in msg or 'bot' in msg.lower() or 'reload' in msg.lower():
            return jsonify({'error': '⚠️ YouTube bot check. Open Firefox → go to youtube.com → sign in → retry.'}), 403
        if '429' in msg or 'Too Many' in msg:
            return jsonify({'error': '⏳ YouTube rate limit hit. Wait 2–3 minutes then retry.'}), 429
        if 'Private' in msg:
            return jsonify({'error': 'This video is private.'}), 403
        return jsonify({'error': f'Download failed: {msg[:300]}'}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
