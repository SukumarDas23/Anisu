/* ===========================
   ANISU — main.js
   Full UI logic for the
   YouTube downloader
   =========================== */

const $ = id => document.getElementById(id);

// ── Elements ──
const urlInput        = $('url-input');
const fetchBtn        = $('fetch-btn');
const fetchSpinner    = $('fetch-spinner');
const fetchBtnText    = fetchBtn.querySelector('.btn-text');
const pasteBtn        = $('paste-btn');
const inputHint       = $('input-hint');
const cardDivider     = $('card-divider');
const previewSection  = $('preview-section');

const videoThumbnail  = $('video-thumbnail');
const durationBadge   = $('duration-badge');
const videoTitle      = $('video-title');
const channelText     = $('channel-text');
const viewsText       = $('views-text');

const formatPills     = document.querySelectorAll('#format-pills .pill');
const qualityPillsEl  = $('quality-pills');
const qualityGroup    = $('quality-group');
const filesizeHint    = $('filesize-hint');

const downloadBtn     = $('download-btn');
const downloadBtnText = downloadBtn.querySelector('.download-btn-text');
const downloadProgress= $('download-progress');
const statusMsg       = $('status-msg');
const newDownloadBtn  = $('new-download-btn');

// ── State ──
let currentVideo = null;   // full API response
let selectedFormat = { type: 'video', ext: 'mp4' };
let selectedQuality = null;
let qualityFormats  = [];  // formats for current ext/type


// ── Helpers ──
function formatDuration(seconds) {
  if (!seconds) return '0:00';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  if (h > 0) return `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  return `${m}:${String(s).padStart(2,'0')}`;
}

function formatViews(n) {
  if (!n) return '0 views';
  if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B views';
  if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M views';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K views';
  return n + ' views';
}

function formatFilesize(bytes) {
  if (!bytes) return '';
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(2) + ' GB';
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
  if (bytes >= 1e3) return (bytes / 1e3).toFixed(0) + ' KB';
  return bytes + ' B';
}

function isValidYouTubeUrl(url) {
  return /^(https?:\/\/)?(www\.)?(youtube\.com\/(watch\?v=|shorts\/|embed\/)|youtu\.be\/)[\w-]{11}/.test(url);
}

function setHint(msg, type = '') {
  inputHint.textContent = msg;
  inputHint.className = 'input-hint' + (type ? ' ' + type : '');
}

function setStatus(msg, type = '') {
  statusMsg.textContent = msg;
  statusMsg.className = 'status-msg' + (type ? ' ' + type : '');
}

function showPreview() {
  cardDivider.hidden = false;
  previewSection.hidden = false;
}

function hidePreview() {
  cardDivider.hidden = true;
  previewSection.hidden = true;
}

function resetDownload() {
  downloadBtnText.textContent = 'Download Now';
  downloadProgress.style.width = '0%';
  downloadBtn.disabled = false;
  newDownloadBtn.hidden = true;
  setStatus('');
}


// ── Paste Button ──
pasteBtn.addEventListener('click', async () => {
  try {
    const text = await navigator.clipboard.readText();
    urlInput.value = text;
    urlInput.dispatchEvent(new Event('input'));
    setHint('Pasted from clipboard!', 'info');
    setTimeout(() => setHint(''), 2000);
  } catch {
    setHint('Clipboard access denied. Please paste manually.', 'error');
  }
});


// ── URL Input Validation ──
urlInput.addEventListener('input', () => {
  const val = urlInput.value.trim();
  if (!val) { setHint(''); return; }
  if (isValidYouTubeUrl(val)) {
    setHint('✓ Valid YouTube URL', 'info');
  } else {
    setHint('Please enter a valid YouTube URL', 'error');
  }
});

urlInput.addEventListener('paste', () => {
  setTimeout(() => {
    urlInput.dispatchEvent(new Event('input'));
  }, 100);
});

// Enter key to fetch
urlInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') fetchBtn.click();
});


// ── Fetch Video Info ──
fetchBtn.addEventListener('click', async () => {
  const url = urlInput.value.trim();

  if (!url) {
    setHint('Please enter a YouTube URL', 'error');
    urlInput.focus();
    return;
  }
  if (!isValidYouTubeUrl(url)) {
    setHint('Please enter a valid YouTube URL', 'error');
    return;
  }

  // Loading state
  fetchBtnText.textContent = 'Fetching...';
  fetchSpinner.hidden = false;
  fetchBtn.disabled = true;
  setHint('');
  hidePreview();
  resetDownload();

  try {
    const res = await fetch('/api/info', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url })
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      setHint(data.error || 'Failed to fetch video info', 'error');
      return;
    }

    currentVideo = data;
    renderPreview(data);
    showPreview();
    setHint('');

  } catch (err) {
    setHint('Network error. Is the server running?', 'error');
  } finally {
    fetchBtnText.textContent = 'Fetch Video';
    fetchSpinner.hidden = true;
    fetchBtn.disabled = false;
  }
});


// ── Render Preview ──
function renderPreview(data) {
  videoThumbnail.src = data.thumbnail || '';
  videoThumbnail.alt = data.title;
  durationBadge.textContent = formatDuration(data.duration);
  videoTitle.textContent = data.title;
  channelText.textContent = data.channel;
  viewsText.textContent = formatViews(data.view_count);

  // Default format selection
  selectedFormat = { type: 'video', ext: 'mp4' };
  formatPills.forEach(p => {
    p.classList.toggle('active', p.dataset.ext === 'mp4' && p.dataset.type === 'video');
  });

  updateQualityPills();
}


// ── Format Pills ──
formatPills.forEach(pill => {
  pill.addEventListener('click', () => {
    formatPills.forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    selectedFormat = { type: pill.dataset.type, ext: pill.dataset.ext };
    updateQualityPills();
  });
});


// ── Quality Pills ──
function updateQualityPills() {
  qualityPillsEl.innerHTML = '';
  filesizeHint.textContent = '';
  selectedQuality = null;

  if (selectedFormat.type === 'audio') {
    qualityGroup.style.display = 'none';
    filesizeHint.textContent = 'MP3 at 192kbps';
    return;
  }

  qualityGroup.style.display = '';

  if (!currentVideo) return;

  // Filter formats by extension
  qualityFormats = currentVideo.formats.filter(
    f => f.type === 'video' && f.ext === selectedFormat.ext
  );

  // Standard quality labels to show in order
  const standardQualities = ['4K', '2160p', '1440p', '1080p', '720p', '480p', '360p'];

  // Find best matching formats
  let displayFormats = [];
  for (const q of standardQualities) {
    const h = q === '4K' ? 2160 : parseInt(q);
    const match = qualityFormats.find(f => f.height === h) ||
                  qualityFormats.find(f => f.quality === q);
    if (match && !displayFormats.find(d => d.quality === match.quality)) {
      displayFormats.push(match);
    }
  }

  // If API returned formats but none matched standard labels, use raw
  if (displayFormats.length === 0) {
    displayFormats = qualityFormats.slice(0, 5);
  }

  // Always ensure at least 720p / best options
  if (displayFormats.length === 0) {
    ['1080p', '720p', '480p', '360p'].forEach(q => {
      displayFormats.push({ quality: q, ext: selectedFormat.ext, type: 'video', filesize: null });
    });
  }

  displayFormats.forEach((fmt, i) => {
    const btn = document.createElement('button');
    btn.className = 'pill' + (i === 0 ? ' active' : '');
    btn.textContent = fmt.quality;
    btn.setAttribute('data-quality', fmt.quality);
    btn.setAttribute('data-filesize', fmt.filesize || '');

    btn.addEventListener('click', () => {
      qualityPillsEl.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      selectedQuality = fmt.quality;
      const size = formatFilesize(fmt.filesize);
      filesizeHint.textContent = size ? `Estimated size: ${size}` : '';
    });

    qualityPillsEl.appendChild(btn);

    if (i === 0) {
      selectedQuality = fmt.quality;
      const size = formatFilesize(fmt.filesize);
      filesizeHint.textContent = size ? `Estimated size: ${size}` : '';
    }
  });
}


// ── Download ──
downloadBtn.addEventListener('click', async () => {
  if (!currentVideo) return;

  const url = currentVideo.url;
  const ext = selectedFormat.ext;
  const type = selectedFormat.type;
  const quality = type === 'audio' ? 'best' : (selectedQuality || '720p');

  // UI — loading state
  downloadBtn.disabled = true;
  downloadBtnText.textContent = 'Preparing download...';
  setStatus('Contacting server...', '');
  newDownloadBtn.hidden = true;

  // Animate progress bar
  let fakeProgress = 0;
  const progressInterval = setInterval(() => {
    fakeProgress = Math.min(fakeProgress + Math.random() * 8, 85);
    downloadProgress.style.width = fakeProgress + '%';
  }, 400);

  try {
    setStatus('Downloading... this may take a moment.', '');

    const res = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, ext, quality, type })
    });

    clearInterval(progressInterval);

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: 'Download failed' }));
      setStatus(err.error || 'Download failed.', 'error');
      resetDownload();
      return;
    }

    // Get filename from header
    const disposition = res.headers.get('Content-Disposition') || '';
    let filename = 'download.' + ext;
    const match = disposition.match(/filename="?([^"]+)"?/);
    if (match) filename = match[1];

    // Stream to blob and trigger save
    downloadProgress.style.width = '95%';
    setStatus('Saving file...', '');

    const blob = await res.blob();
    downloadProgress.style.width = '100%';

    const blobUrl = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => { URL.revokeObjectURL(blobUrl); a.remove(); }, 2000);

    setStatus('✓ Download complete!', '');
    downloadBtnText.textContent = '✓ Downloaded!';
    newDownloadBtn.hidden = false;

  } catch (err) {
    clearInterval(progressInterval);
    setStatus('Error: ' + err.message, 'error');
    resetDownload();
  } finally {
    clearInterval(progressInterval);
    downloadBtn.disabled = false;
  }
});


// ── New Download ──
newDownloadBtn.addEventListener('click', () => {
  urlInput.value = '';
  setHint('');
  hidePreview();
  resetDownload();
  currentVideo = null;
  urlInput.focus();
});


// ── Smooth scroll for nav links ──
document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', e => {
    const href = link.getAttribute('href');
    if (href && href.startsWith('#') && href.length > 1) {
      e.preventDefault();
      const target = document.querySelector(href);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    link.classList.add('active');
  });
});


// ── Scroll-based navbar highlight ──
const sections = [
  { id: 'home', navId: 'nav-home' },
  { id: 'features', navId: 'nav-features' },
  { id: 'how-it-works', navId: 'nav-how' },
];

window.addEventListener('scroll', () => {
  const scrollY = window.scrollY + 80;
  sections.forEach(({ id, navId }) => {
    const el = document.getElementById(id);
    if (!el) return;
    const { offsetTop, offsetHeight } = el;
    const navEl = document.getElementById(navId);
    if (!navEl) return;
    if (scrollY >= offsetTop && scrollY < offsetTop + offsetHeight) {
      document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
      navEl.classList.add('active');
    }
  });
}, { passive: true });
