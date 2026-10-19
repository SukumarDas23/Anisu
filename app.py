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

BGUTIL_SCRIPT = '/home/ubuntu/bgutil-ytdlp-pot-provider/server/build/generate_once.js'

YDL_BASE = {
    'quiet':       True,
    'no_warnings': True,
    'http_headers': {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/131.0.0.0 Safari/537.36'
        ),
        'Accept-Language': 'en-US,en;q=0.9',
    },
    'js_runtimes': {'node': {'cmd': '/usr/bin/node'}},

    'external_downloader': 'aria2c',
    'external_downloader_args': {
        'aria2c': [
            '--max-connection-per-server=16',
            '--split=16',
            '--min-split-size=1M',
            '--continue=true',
            '--summary-interval=0',
        ]
    },
}

BGUTIL_EXTRACTOR_ARGS = {
    # web_embedded: returns all DASH streams (144p to 4K) with real URLs
    # bgutil provides PO tokens so downloads work from datacenter IPs
    'youtube': {'player_client': ['web_embedded']},
    'youtubepot-bgutilscript': {
        'script_path': [BGUTIL_SCRIPT]
    },
}


def sanitize_filename(name):
    return re.sub(r'[\/*?:"<>|]', '', name)


def normalize_height(h):
    if h >= 2000: return 2160, '4K'
    if h >= 1300: return 1440, '1440p'
    if h >= 900:  return 1080, '1080p'
    if h >= 600:  return 720,  '720p'
    if h >= 400:  return 480,  '480p'
    if h >= 260:  return 360,  '360p'
    if h >= 180:  return 240,  '240p'
    return 144, '144p'


def make_ydl_opts(extra=None):
    opts = {
        **YDL_BASE,
        'extractor_args': BGUTIL_EXTRACTOR_ARGS,
        'remote_components': {'ejs': ['github']},
    }
    if extra:
        opts.update(extra)
    return opts


def extract_info_robust(url):
    errors = []
    clients = [
        ['web_embedded'],
        ['tv_embedded'],
        ['web_embedded', 'tv_embedded'],
    ]
    for client in clients:
        try:
            args = {**BGUTIL_EXTRACTOR_ARGS, 'youtube': {'player_client': client}}
            opts = {**YDL_BASE, 'skip_download': True,
                    'extractor_args': args,
                    'remote_components': {'ejs': ['github']}}
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url, download=False)
        except Exception as e:
            errors.append(f'[{client}] {e}')
    raise RuntimeError(' | '.join(errors))


def download_robust(url, fmt_str, merge_ext, output_path, post_processors=None):
    errors = []
    def _cfg(client):
        args = {**BGUTIL_EXTRACTOR_ARGS, "youtube": {"player_client": client}}
        return {**YDL_BASE, "format": fmt_str, "outtmpl": output_path,
                "noplaylist": True, "merge_output_format": merge_ext,
                "extractor_args": args, "remote_components": {"ejs": ["github"]}}
    configs = [_cfg(["web_embedded"]), _cfg(["tv_embedded"]), _cfg(["web_embedded","tv_embedded"])]
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
            if 'Private' in msg or 'age' in msg.lower():
                break
            time.sleep(1)

    raise RuntimeError(' | '.join(errors))


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/info', methods=['POST'])
def get_info():
    data = request.get_json()
    url  = data.get('url', '').strip()
    if not url:
        return jsonify({'error': 'No URL provided'}), 400

    try:
        info = extract_info_robust(url)
        best_video = {}

        for f in info.get('formats', []):
            height  = f.get('height')
            ext     = f.get('ext', '')
            vcodec  = f.get('vcodec', 'none')
            proto   = f.get('protocol', '')
            fid     = f.get('format_id', '')
            has_url = bool(f.get('url'))

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

        ext_order = {'mp4': 0, 'webm': 1}
        formats = sorted(
            best_video.values(),
            key=lambda x: (ext_order.get(x['ext'], 9), -(x.get('height') or 0))
        )
        formats.append({
            'format_id': 'bestaudio/best',
            'ext':       'mp3',
            'quality':   'Best',
            'height':    0,
            'type':      'audio',
            'filesize':  None,
        })

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
            return jsonify({'error': 'YouTube bot check — please try again in a moment.'}), 403
        if 'Private' in msg:
            return jsonify({'error': 'This video is private.'}), 403
        if '429' in msg or 'Too Many' in msg:
            return jsonify({'error': 'Too many requests — please wait 1–2 minutes.'}), 429
        return jsonify({'error': f'Could not fetch video info. Please try again.'}), 500


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
            fmt_str         = 'bestaudio/best'
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

        if fmt_type == 'audio' and downloaded_file:
            base = os.path.splitext(downloaded_file)[0]
            if os.path.exists(base + '.mp3'):
                downloaded_file = base + '.mp3'

        if not downloaded_file or not os.path.exists(downloaded_file):
            title_key = sanitize_filename(info.get('title', ''))[:20].lower()
            all_files = [os.path.join(DOWNLOAD_FOLDER, f) for f in os.listdir(DOWNLOAD_FOLDER)]
            candidates = [f for f in all_files if title_key in os.path.basename(f).lower()]
            if candidates:
                downloaded_file = max(candidates, key=os.path.getmtime)
            elif all_files:
                downloaded_file = max(all_files, key=os.path.getmtime)

        if not downloaded_file or not os.path.exists(downloaded_file):
            return jsonify({'error': 'Downloaded file not found.'}), 500

        basename   = os.path.basename(downloaded_file)
        filesize   = os.path.getsize(downloaded_file)
        actual_ext = os.path.splitext(basename)[1].lower()
        mime_map   = {
            '.mp4': 'video/mp4', '.webm': 'video/webm',
            '.mkv': 'video/x-matroska', '.mp3': 'audio/mpeg',
            '.m4a': 'audio/mp4',
        }
        mime = mime_map.get(actual_ext, 'application/octet-stream')

        safe_name = basename.encode('ascii', 'ignore').decode('ascii').strip() or f'download{actual_ext}'
        utf8_name = urllib.parse.quote(basename, safe='')
        content_disposition = (
            f'attachment; filename="{safe_name}"; '
            f'filename*=UTF-8\'\'{utf8_name}'
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
        if 'bot' in msg.lower() or 'Sign in' in msg or 'reload' in msg.lower():
            return jsonify({'error': 'YouTube temporarily blocked the request. Please retry in a moment.'}), 403
        if '429' in msg or 'Too Many' in msg:
            return jsonify({'error': 'Too many requests — please wait 1–2 minutes.'}), 429
        if 'Private' in msg:
            return jsonify({'error': 'This video is private.'}), 403
        return jsonify({'error': 'Download failed — please try again.'}), 500


if __name__ == '__main__':
    app.run(debug=True, port=5000)
