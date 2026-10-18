# 🎬 Anisu — YouTube Downloader

A fast, free, and beautiful YouTube video downloader built with **Flask** + **yt-dlp**.

![Anisu Screenshot](https://i.imgur.com/placeholder.png)

## ✨ Features

- 🎨 **Dark Glassmorphism UI** — Purple/Cyan neon design
- 📥 **Download MP4, MP3, WebM** — Multiple formats
- 🎞 **Quality selector** — 360p up to 4K
- ⚡ **Lightning fast** — Direct stream extraction via yt-dlp
- 🔒 **No sign-up** — Paste URL and download instantly
- 📱 **Fully responsive** — Works on mobile & desktop

## 🛠 Tech Stack

| Layer | Technology |
|---|---|
| Frontend | HTML5, Vanilla CSS (Glassmorphism), JavaScript |
| Backend | Python 3, Flask, Flask-CORS |
| Downloader | yt-dlp (latest) |
| Runtime | Node.js (for yt-dlp JS extraction) |

## 🚀 Setup & Run

### Prerequisites
- Python 3.10+
- Node.js 18+
- ffmpeg (for MP3 audio extraction)

### Installation

```bash
# Clone the repo
git clone https://github.com/SukumarDas23/Anisu.git
cd Anisu

# Install Python dependencies
pip install -r requirements.txt

# Run the server
flask --app app run --port 5000
```

Then open **http://localhost:5000** in your browser.

## 📁 Project Structure

```
Anisu/
├── app.py               ← Flask backend (yt-dlp API)
├── requirements.txt     ← Python dependencies
├── templates/
│   └── index.html       ← Main HTML page
├── static/
│   ├── css/style.css    ← Dark Glassmorphism styles
│   └── js/main.js       ← Frontend logic
└── downloads/           ← Temp folder (auto-cleaned)
```

## ⚠️ Disclaimer

This tool is for **personal use only**. Please respect content creators and YouTube's [Terms of Service](https://www.youtube.com/t/terms).

## 📄 License

MIT License © 2026 SukumarDas23
