import pyautogui
from flask import Flask, render_template_string, request, Response, jsonify, session, redirect, url_for
import socket
import logging
import platform
import io
import threading
import time
import mss
import subprocess
import re
import random
import os
import datetime
import ctypes # Windows DPI Fix
from PIL import Image, ImageDraw

# --- WINDOWS SPECIFIC FIX: DPI AWARENESS ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Try to import psutil
try:
    import psutil
except ImportError:
    psutil = None

# System Config
HOSTNAME = socket.gethostname()
ACCESS_PIN = str(random.randint(1000, 9999))

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_PERMANENT'] = False 

# --- OPTIMIZED CURSOR SETTINGS ---
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0 

# --- GLOBALS ---
cursor_speed = 3.0
scroll_speed = 1.5
zoom_threshold = 40
last_net_bytes = 0
last_net_time = time.time()
fps_counter = 0
current_fps = 0
last_fps_time = time.time()

# --- UTILITY FUNCTIONS ---
def get_ssid():
    try:
        out = subprocess.check_output("netsh wlan show interfaces", shell=True).decode('utf-8', errors='ignore')
        for line in out.split('\n'):
            if "SSID" in line and "BSSID" not in line:
                parts = line.split(':')
                if len(parts) > 1: return parts[1].strip()
    except: pass
    return "WiFi Connected"

def get_uptime():
    if psutil:
        try:
            boot_time = psutil.boot_time()
            seconds = time.time() - boot_time
            m, s = divmod(seconds, 60)
            h, m = divmod(m, 60)
            return f"{int(h)}h {int(m)}m"
        except: pass
    return "--"

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try: s.connect(('8.8.8.8', 1)); IP = s.getsockname()[0]
    except: IP = '127.0.0.1'
    finally: s.close()
    return IP

def show_pin_popup():
    time.sleep(2) 
    ip_addr = get_ip()
    try:
        pyautogui.alert(text=f"PIN: {ACCESS_PIN}\n\nIP: {ip_addr}:5000", title='Magic Tracker Started', button='OK')
    except: 
        print(f"PIN IS: {ACCESS_PIN}")

# --- ENGINE (FIXED FOR WINDOWS) ---
class VideoStreamer:
    def __init__(self):
        self.current_frame = None
        self.lock = threading.Lock()
        self.running = False
        self.target_width = 854 
        self.jpeg_quality = 50
        # self.sct এখানে শুরু করা যাবে না (Windows error fix)

    def set_quality(self, level):
        if level == 1: self.target_width = 480; self.jpeg_quality = 30
        elif level == 2: self.target_width = 854; self.jpeg_quality = 50
        elif level == 3: self.target_width = 1280; self.jpeg_quality = 70
        elif level == 4: self.target_width = 1920; self.jpeg_quality = 90

    def start(self):
        if self.running: return
        self.running = True
        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False

    def update(self):
        global fps_counter, current_fps, last_fps_time
        
        # FIX: mss কে এই থ্রেডের ভেতরেই শুরু করতে হবে
        with mss.mss() as sct:
            monitor = sct.monitors[1] # প্রথম মনিটর সিলেক্ট করা হলো
            
            while self.running:
                try:
                    start_time = time.time()
                    fps_counter += 1
                    if start_time - last_fps_time >= 1.0:
                        current_fps = fps_counter
                        fps_counter = 0
                        last_fps_time = start_time

                    sct_img = sct.grab(monitor) # এখন আর ক্র্যাশ করবে না
                    
                    # Windows Color Fix (BGRA to RGB)
                    img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    
                    w, h = img.size
                    if self.target_width < w:
                        scale = self.target_width / w
                        new_h = int(h * scale)
                        img = img.resize((self.target_width, new_h), Image.Resampling.NEAREST)
                    else: scale = 1.0
                    
                    try:
                        mouse_x, mouse_y = pyautogui.position()
                        rel_x = mouse_x - monitor["left"]
                        rel_y = mouse_y - monitor["top"]
                        draw = ImageDraw.Draw(img)
                        cx = rel_x * scale; cy = rel_y * scale
                        cursor_size = 20 if self.target_width > 1200 else 16
                        draw.polygon([(cx, cy), (cx, cy + cursor_size), (cx + cursor_size * 0.6, cy + cursor_size * 0.6)], fill="white", outline="black")
                    except: pass

                    frame_bytes = io.BytesIO()
                    img.save(frame_bytes, format='JPEG', quality=self.jpeg_quality, optimize=False)
                    with self.lock: self.current_frame = frame_bytes.getvalue()
                    
                    elapsed = time.time() - start_time
                    if elapsed < 0.033: time.sleep(0.033 - elapsed)
                except Exception as e: 
                    # print(f"Stream Error: {e}") # এরর প্রিন্ট বন্ধ করে দিলাম যাতে টার্মিনাল ক্লিন থাকে
                    time.sleep(0.1)

streamer = VideoStreamer()

# --- HTML TEMPLATES ---
login_html = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Security Check</title>
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;500;700&display=swap" rel="stylesheet">
    <style>
        body { background-color: #000000; background: radial-gradient(circle at center, #1a1a1a 0%, #000000 100%); height: 100vh; margin: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; font-family: 'Poppins', sans-serif; color: white; overflow: hidden; }
        .card { background: rgba(255, 255, 255, 0.05); padding: 40px 30px; border-radius: 30px; text-align: center; width: 85%; max-width: 350px; border: 1px solid rgba(255, 255, 255, 0.1); backdrop-filter: blur(15px); box-shadow: 0 0 60px rgba(0, 210, 255, 0.15); transition: opacity 0.5s ease; }
        h2 { margin: 0 0 20px; font-weight: 700; letter-spacing: 1px; color: white; text-shadow: 0 0 10px rgba(0,210,255,0.5); }
        input { width: 100%; padding: 15px; border-radius: 15px; border: 1px solid rgba(255,255,255,0.1); background: rgba(0,0,0,0.6); color: #00d2ff; text-align: center; font-size: 24px; font-weight: bold; letter-spacing: 5px; outline: none; box-sizing: border-box; margin-bottom: 20px; }
        button { width: 100%; padding: 15px; border-radius: 30px; border: none; background: #00d2ff; color: #000; font-weight: bold; font-size: 16px; cursor: pointer; transition: 0.3s; box-shadow: 0 5px 15px rgba(0, 210, 255, 0.4); }
        button:active { transform: scale(0.95); }
        .footer { margin-top: 30px; font-size: 10px; color: rgba(255,255,255,0.4); letter-spacing: 1px; }
        .error { color: #ff4444; font-size: 13px; margin-bottom: 15px; font-weight: bold; display: none; }
        #welcome-screen { position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: black; z-index: 9999; display: none; align-items: center; justify-content: center; flex-direction: column; opacity: 0; transition: opacity 1s ease-in-out; }
        .wel-small { font-size: 14px; letter-spacing: 2px; color: #888; margin-bottom: 10px; }
        .wel-big { font-size: 32px; font-weight: 700; letter-spacing: 1px; color: #fff; text-shadow: 0 0 20px rgba(0, 210, 255, 0.8), 0 0 40px rgba(0, 210, 255, 0.4); margin-bottom: 15px; text-align: center; }
        .wel-name { font-size: 12px; letter-spacing: 1px; color: #00d2ff; opacity: 0.8; }
    </style>
</head>
<body>
    <div id="welcome-screen"><div class="wel-small">Welcome to</div><div class="wel-big">MAGIC TRACKER</div><div class="wel-name">by Anupam Sahoo</div></div>
    <div class="card" id="login-card">
        <h2>MAGIC TRACKER</h2><div id="error-msg" class="error">INCORRECT PIN</div><input type="tel" id="pin" maxlength="4" placeholder="••••"><button onclick="checkPin()">ENTER SECURELY</button>
    </div>
    <div class="footer" id="login-footer">Secured by ANUPAM SAHOO</div>
    <script>
        function checkPin() {
            let pin = document.getElementById('pin').value;
            fetch('/check_pin?p=' + pin).then(r => r.json()).then(d => {
                if(d.valid) {
                    document.getElementById('login-card').style.opacity = '0';
                    document.getElementById('login-footer').style.opacity = '0';
                    let ws = document.getElementById('welcome-screen');
                    ws.style.display = 'flex';
                    setTimeout(() => { ws.style.opacity = '1'; }, 100);
                    setTimeout(() => { ws.style.opacity = '0'; setTimeout(() => { window.location.href = "/"; }, 800); }, 2500); 
                } else { 
                    document.getElementById('error-msg').style.display = 'block'; 
                    document.getElementById('pin').value = ''; 
                    document.getElementById('pin').focus();
                }
            });
        }
    </script>
</body>
</html>
"""

main_html = """
<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Magic Tracker Ultimate</title>
    <link href="https://fonts.googleapis.com/icon?family=Material+Icons" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=Poppins:wght@300;500;700&display=swap" rel="stylesheet">
    <style>
        @keyframes fadeInZoom { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: scale(1); } }
        :root { --glass-bg: rgba(255, 255, 255, 0.06); --glass-border: 1px solid rgba(255, 255, 255, 0.12); --neon-blue: #00d2ff; }
        html, body { margin: 0; padding: 0; width: 100%; height: 100%; background-color: #000; background: radial-gradient(circle at center, #1a1a1a 0%, #000000 100%); overflow: hidden; position: fixed; font-family: 'Poppins', sans-serif; touch-action: none; user-select: none; display: flex; flex-direction: column; align-items: center; justify-content: center; animation: fadeInZoom 1s ease-out forwards; }
        #video-container { position: absolute; width: 100%; height: 100%; display: flex; align-items: center; justify-content: center; z-index: 0; }
        #video-bg { max-width: 100%; max-height: 100%; opacity: 0; transition: opacity 0.4s; position: relative; box-shadow: 0 0 50px rgba(0,0,0,0.8); }
        body.landscape-mode #video-container { position: fixed; top: 0; left: 0; width: 100vh; height: 100vw; transform: rotate(90deg); transform-origin: top left; margin-left: 100vw; z-index: 500; background: #000; }
        body.landscape-mode #video-bg { width: 100%; height: 100%; object-fit: contain; top: 0 !important; }
        body.landscape-mode .header, body.landscape-mode .control-bar, body.landscape-mode #trackpad, body.landscape-mode #fs-btn-main, body.landscape-mode #kbd-btn, body.landscape-mode .footer { display: none !important; }
        .header { position: absolute; top: 20px; left: 20px; font-size: 16px; font-weight: 700; color: rgba(255, 255, 255, 0.9); z-index: 150; cursor: pointer; background: var(--glass-bg); padding: 8px 20px; border-radius: 30px; backdrop-filter: blur(12px); border: var(--glass-border); box-shadow: 0 4px 15px rgba(0,0,0,0.4); }
        .control-bar { position: absolute; top: 20px; right: 20px; display: flex; gap: 10px; z-index: 150; }
        .icon-btn { background: var(--glass-bg); color: #fff; width: 45px; height: 45px; border-radius: 50%; display: flex; align-items: center; justify-content: center; cursor: pointer; backdrop-filter: blur(12px); border: var(--glass-border); box-shadow: 0 5px 15px rgba(0,0,0,0.5); transition: all 0.2s; }
        .icon-btn:active { color: var(--neon-blue); transform: scale(0.95); }
        .active-cam { border: 1px solid #ff4444; color: #ff4444; background: rgba(255, 68, 68, 0.15); }
        .active-lock { border: 1px solid var(--neon-blue); color: var(--neon-blue); background: rgba(0, 210, 255, 0.15); }
        #trackpad { position: absolute; width: 90%; height: 55%; z-index: 10; border-radius: 35px; background: rgba(255, 255, 255, 0.02); border: var(--glass-border); backdrop-filter: blur(8px); box-shadow: inset 0 0 40px rgba(0,0,0,0.4), 0 10px 30px rgba(0,0,0,0.3); display: flex; flex-direction: column; align-items: center; justify-content: center; }
        .touch-indicator { font-size: 60px; color: rgba(255, 255, 255, 0.1); animation: pulse 3s infinite; pointer-events: none; }
        #suggestion-box { position: absolute; bottom: 80px; width: 100%; text-align: center; font-size: 10px; letter-spacing: 1px; color: var(--neon-blue); opacity: 0.6; pointer-events: none; transition: opacity 0.5s; }
        #fs-btn-main, #kbd-btn { position: absolute; bottom: 85px; width: 55px; height: 55px; border-radius: 50%; background: linear-gradient(145deg, #1e1e1e, #111); border: var(--glass-border); color: #ccc; display: flex; align-items: center; justify-content: center; box-shadow: 0 10px 25px rgba(0,0,0,0.7); z-index: 30; }
        #fs-btn-main { left: 25px; } #kbd-btn { right: 25px; }
        .footer { position: absolute; bottom: 20px; font-size: 10px; color: rgba(255, 255, 255, 0.5); background: var(--glass-bg); padding: 8px 15px; border-radius: 30px; z-index: 20; backdrop-filter: blur(10px); border: var(--glass-border); box-shadow: 0 4px 15px rgba(0,0,0,0.4); }
        .footer span { color: var(--neon-blue); font-weight: 700; }
        #fs-controls { display: none; position: fixed; top: 50%; right: 20px; transform: translateY(-50%) rotate(90deg); z-index: 10000; gap: 30px; transform-origin: center right; }
        body.landscape-mode #fs-controls { display: flex; }
        .mini-btn { width: 45px; height: 45px; border-radius: 50%; background: rgba(0,0,0,0.6); color: white; border: 1px solid rgba(255,255,255,0.2); display: flex; align-items: center; justify-content: center; backdrop-filter: blur(8px); cursor: pointer; box-shadow: 0 5px 15px rgba(0,0,0,0.8); }
        #fs-brand { display: none; position: fixed; left: -48vh; top: 50%; transform: rotate(90deg); width: 100vh; text-align: center; font-size: 9px; color: rgba(255,255,255,0.3); pointer-events: none; z-index: 2000; font-weight: 500; letter-spacing: 1px; }
        body.landscape-mode #fs-brand { display: block; }
        #settings-panel { display: none; position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); width: 85%; max-height: 85vh; overflow-y: auto; background: rgba(18, 18, 18, 0.95); border: var(--glass-border); border-radius: 30px; padding: 25px; z-index: 9999; text-align: center; color: white; box-shadow: 0 40px 90px rgba(0,0,0,1); backdrop-filter: blur(30px); }
        .slider-container { margin: 12px 0; text-align: left; }
        .slider-label { font-size: 11px; color: var(--neon-blue); display: block; margin-bottom: 5px; letter-spacing: 1px; }
        input[type=range] { width: 100%; accent-color: var(--neon-blue); height: 5px; }
        .status-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; margin-bottom: 15px; }
        .status-box { background: rgba(255,255,255,0.05); padding: 8px; border-radius: 12px; text-align: left; border: 1px solid rgba(255,255,255,0.05); }
        .status-label { font-size: 9px; color: #888; display: block; margin-bottom: 2px; }
        .status-val { font-size: 11px; color: #fff; font-weight: 600; display: flex; align-items: center; gap: 5px; }
        .full-width { grid-column: span 2; display:flex; justify-content: space-between; align-items: center; }
        .power-row { display:flex; justify-content:space-between; margin:15px 0; gap:10px; }
        .power-btn { width:100%; padding:12px; border-radius:15px; border:none; font-weight:bold; cursor:pointer; color:white; font-size:12px; transition:0.2s; }
        .btn-sleep { background:rgba(255,165,0,0.2); border:1px solid orange; color:orange; }
        .btn-sleep:active { background:orange; color:black; }
        .btn-shut { background:rgba(255,68,68,0.2); border:1px solid #ff4444; color:#ff4444; }
        .btn-shut:active { background:#ff4444; color:white; }
        .logout-btn { background: rgba(255, 255, 255, 0.1); color: #ccc; border: 1px solid #666; padding: 10px 30px; border-radius: 20px; font-weight: bold; margin-top: 10px; cursor: pointer; display: block; width: 100%; box-sizing: border-box; }
        #features-modal { display: none; position: absolute; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0, 0, 0, 0.95); z-index: 9999; backdrop-filter: blur(20px); align-items: center; justify-content: center; }
        .modal-content { background: rgba(20, 20, 20, 0.95); padding: 30px; border-radius: 30px; width: 85%; max-width: 400px; border: var(--glass-border); box-shadow: 0 0 60px rgba(0, 210, 255, 0.2); }
        .spec-list li { margin: 12px 0; color: #ccc; font-size: 11px; display: flex; align-items: center; border-bottom: 1px solid rgba(255,255,255,0.05); padding-bottom: 8px; font-family: 'Courier New', monospace; }
        .linkedin-btn { background: #0077b5; color: white; border-radius: 50%; width: 30px; height: 30px; display: flex; align-items: center; justify-content: center; text-decoration: none; box-shadow: 0 4px 10px rgba(0, 119, 181, 0.4); margin-left: 10px; }
        #hidden-input { opacity: 0; position: absolute; top: -5000px; }
        @keyframes pulse { 0% { opacity: 0.1; } 50% { opacity: 0.25; } 100% { opacity: 0.1; } }
        @keyframes fadeInfo { 0% { opacity: 0; transform: translateY(5px); } 20% { opacity: 1; transform: translateY(0); } 80% { opacity: 1; transform: translateY(0); } 100% { opacity: 0; transform: translateY(-5px); } }
        .animate-text { animation: fadeInfo 3s forwards; }
    </style>
</head>
<body>
    <div id="video-container"><img id="video-bg" src=""></div>
    <div class="header" onclick="openFeatures()">MAGIC TRACKER</div>
    <div class="control-bar">
        <div class="icon-btn" id="lock-btn" onclick="toggleDrag()"><span class="material-icons">lock_open</span></div>
        <div class="icon-btn" id="cam-btn" onclick="toggleVideo()"><span class="material-icons">videocam_off</span></div>
        <div class="icon-btn" onclick="openSettings()"><span class="material-icons">settings</span></div>
    </div>
    <div id="suggestion-box"></div>
    <div id="trackpad"><div class="touch-indicator"><span class="material-icons" style="font-size: 70px;">fingerprint</span></div></div>
    <div id="fs-btn-main" onclick="toggleFullScreen()"><span class="material-icons">fullscreen</span></div>
    <div id="kbd-btn" onclick="toggleKeyboard()"><span class="material-icons">keyboard</span></div>
    <div class="footer">Magic Tracker by <span>ANUPAM SAHOO</span></div>
    <div id="fs-controls"><div class="mini-btn" onclick="toggleFullScreen()"><span class="material-icons" style="font-size: 20px;">fullscreen_exit</span></div><div class="mini-btn" onclick="openSettings()"><span class="material-icons" style="font-size: 18px;">settings</span></div></div>
    <div id="fs-brand">Magic Tracker by Anupam Sahoo</div>
    <div id="settings-panel">
        <h3 style="color:#fff; margin-top:0; font-size:16px;">SYSTEM MONITOR</h3>
        <div class="status-grid">
            <div class="status-box full-width"><div><span class="status-label">DEVICE</span><span class="status-val" id="host-val">Loading...</span></div><div><span class="material-icons" style="color:var(--neon-blue)">laptop_windows</span></div></div>
            <div class="status-box"><span class="status-label">BATTERY</span><span class="status-val" id="bat-val">--%</span></div>
            <div class="status-box"><span class="status-label">FPS / LATENCY</span><span class="status-val" id="fps-val">--</span></div>
            <div class="status-box full-width"><span class="status-label">NETWORK</span><span class="status-val" id="net-val">--</span></div>
            <div class="status-box full-width"><span class="status-label">UPLOAD</span><span class="status-val" id="up-val">0 KB/s</span></div>
        </div>
        <div class="slider-container"><span class="slider-label">SYSTEM VOLUME</span><input type="range" min="0" max="100" step="2" value="50" oninput="updateVolume(this.value)"></div>
        <div class="slider-container"><span class="slider-label">VIDEO QUALITY</span><input type="range" min="1" max="4" step="1" value="2" oninput="updateQuality(this.value)"><div style="display:flex; justify-content:space-between; font-size:10px; color:#666; margin-top:5px;"><span>Low</span><span>Med</span><span>High</span><span style="color:#ff4444">Extreme</span></div></div>
        <div class="slider-container"><span class="slider-label">CURSOR SPEED</span><input type="range" min="1.0" max="6.0" step="0.5" value="3.0" oninput="updateVal('cursor', this.value)"></div>
        <div class="slider-container"><span class="slider-label">SCROLL SPEED</span><input type="range" min="0.5" max="4.0" step="0.5" value="1.5" oninput="updateVal('scroll', this.value)"></div>
        <div class="slider-container"><span class="slider-label">ZOOM THRESHOLD</span><input type="range" min="10" max="100" step="5" value="40" oninput="updateVal('zoom', this.value)"></div>
        <div class="slider-container"><span class="slider-label">VIDEO POSITION Y</span><input type="range" min="-200" max="200" step="10" value="0" oninput="updateVal('pos', this.value)"></div>
        <div class="power-row"><button class="power-btn btn-sleep" onclick="triggerPower('sleep')">SLEEP 🌙</button><button class="power-btn btn-shut" onclick="triggerPower('shutdown')">SHUTDOWN 🛑</button></div>
        <div style="display:flex; gap:10px; margin-top:10px;"><button onclick="closeSettings()" style="flex:1; background:var(--neon-blue); color:black; border:none; padding:10px; border-radius:20px; font-weight:bold;">CLOSE</button><button onclick="doLogout()" class="logout-btn" style="flex:1; margin-top:0;">LOG OUT</button></div>
    </div>
    <div id="features-modal" onclick="closeFeatures()">
        <div class="modal-content" onclick="event.stopPropagation()">
            <h2 style="color:white; margin:0 0 10px 0;">ENGINEERING <span style="color:#00d2ff;">SPECS</span></h2>
            <ul class="spec-list">
                <li><span class="material-icons">code</span> <div><b>Architecture:</b> Flask Asynchronous Server</div></li>
                <li><span class="material-icons">memory</span> <div><b>Pipeline:</b> MSS Direct Memory Access</div></li>
                <li><span class="material-icons">speed</span> <div><b>Latency:</b> Low Latency TCP/IP Socket</div></li>
                <li><span class="material-icons">compress</span> <div><b>Codec:</b> JPEG Turbo (Subsampling 0)</div></li>
                <li><span class="material-icons">touch_app</span> <div><b>HID:</b> PyAutoGUI + Native Calls</div></li>
                <li><span class="material-icons">monitor_heart</span> <div><b>Telemetry:</b> PSUtil Hardware Monitor</div></li>
            </ul>
            <div style="display:flex; align-items:center; justify-content:center; margin-top:20px; color:#777; font-size:13px;">Magic Tracker by <b style="color:#fff; margin-left:5px;">ANUPAM SAHOO</b><a href="https://www.linkedin.com/in/anupam-sahoo-39a694355" target="_blank" class="linkedin-btn"><span class="material-icons" style="font-size: 18px;">info</span></a></div>
            <div style="text-align:center; margin-top:20px;"><button onclick="closeFeatures()" style="background:transparent; color:#00d2ff; border:1px solid #00d2ff; padding:8px 30px; border-radius:20px;">CLOSE</button></div>
        </div>
    </div>
    <input type="text" id="hidden-input">
    <script>
        let cursorSpeed = 3.0, scrollSpeed = 1.5, zoomThreshold = 40;
        const trackpad = document.getElementById('trackpad'), videoBg = document.getElementById('video-bg');
        function openFeatures() { document.getElementById('features-modal').style.display = 'flex'; }
        function closeFeatures() { document.getElementById('features-modal').style.display = 'none'; }
        function openSettings() { document.getElementById('settings-panel').style.display = 'block'; }
        function closeSettings() { document.getElementById('settings-panel').style.display = 'none'; }
        function updateQuality(val) { fetch('/set_quality?level=' + val); }
        function doLogout() { window.location.href = "/logout"; }
        let lastVol = 50;
        function updateVolume(val) {
            let diff = val - lastVol;
            let steps = Math.ceil(Math.abs(diff) / 2); 
            for(let i=0; i<steps; i++) { setTimeout(() => { if(diff > 0) fetch('/volume?act=up'); else fetch('/volume?act=down'); }, i * 20); }
            lastVol = val;
        }
        function triggerPower(act) { if(confirm('Are you sure you want to ' + act + ' the system?')) { fetch('/power?act=' + act); } }
        function updateVal(type, val) {
            if (type === 'cursor') cursorSpeed = parseFloat(val); 
            if (type === 'scroll') scrollSpeed = parseFloat(val);
            if (type === 'zoom') zoomThreshold = parseInt(val); 
            if (type === 'pos') videoBg.style.top = val + "px";
        }
        const suggestions = ["Tap to Click", "2 Fingers to Scroll", "Pinch to Zoom", "Long Press to Drag", "3 Fingers Down to Screenshot"];
        let suggIndex = 0; const suggBox = document.getElementById('suggestion-box');
        function showSuggestion() {
            if (document.body.classList.contains('landscape-mode')) suggBox.style.display = 'none';
            else { suggBox.style.display = 'block'; suggBox.innerText = suggestions[suggIndex]; suggBox.classList.remove('animate-text'); void suggBox.offsetWidth; suggBox.classList.add('animate-text'); suggIndex = (suggIndex + 1) % suggestions.length; }
        }
        setInterval(showSuggestion, 4000); showSuggestion();
        setInterval(() => {
            if(document.getElementById('settings-panel').style.display === 'block') {
                const start = Date.now();
                fetch('/status').then(r => r.json()).then(d => {
                    const ping = Date.now() - start;
                    document.getElementById('host-val').innerText = d.host;
                    let batText = d.battery; if(d.plugged) batText += " ⚡";
                    const batElem = document.getElementById('bat-val'); batElem.innerText = batText + ' (Up: ' + d.uptime + ')'; batElem.style.color = (parseInt(d.battery) > 20) ? '#0f0' : '#f00';
                    const fpsElem = document.getElementById('fps-val'); fpsElem.innerText = `${d.fps} FPS / ${ping}ms`; fpsElem.style.color = (d.fps > 25 && ping < 100) ? '#0f0' : '#f00';
                    document.getElementById('net-val').innerText = `${d.ssid}`; document.getElementById('up-val').innerText = d.upload_speed;
                });
            }
        }, 1500);
        let isFullScreen = false;
        function toggleFullScreen() {
            isFullScreen = !isFullScreen; const body = document.body;
            if(isFullScreen) { if (document.documentElement.requestFullscreen) document.documentElement.requestFullscreen(); body.classList.add('landscape-mode'); }
            else { if (document.exitFullscreen) document.exitFullscreen(); body.classList.remove('landscape-mode'); }
        }
        let isVideoOn = false;
        function toggleVideo() {
            isVideoOn = !isVideoOn; const btn = document.getElementById('cam-btn');
            if(isVideoOn) {
                fetch('/start_stream'); videoBg.src = "/video_feed"; videoBg.style.opacity = "1"; btn.innerHTML = '<span class="material-icons">videocam</span>'; btn.classList.add('active-cam'); document.querySelector('.touch-indicator').style.display = 'none'; trackpad.style.background = 'transparent'; trackpad.style.boxShadow = 'none'; trackpad.style.border = 'none'; trackpad.style.backdropFilter = 'none'; suggBox.style.display = 'none';
            } else {
                fetch('/stop_stream'); videoBg.src = ""; videoBg.style.opacity = "0"; btn.innerHTML = '<span class="material-icons">videocam_off</span>'; btn.classList.remove('active-cam'); document.querySelector('.touch-indicator').style.display = 'block'; trackpad.style.background = 'rgba(255, 255, 255, 0.02)'; trackpad.style.boxShadow = 'inset 0 0 40px rgba(0,0,0,0.4), 0 10px 30px rgba(0,0,0,0.3)'; trackpad.style.border = '1px solid rgba(255, 255, 255, 0.1)'; trackpad.style.backdropFilter = 'blur(8px)'; suggBox.style.display = 'block';
            }
        }
        let isDragMode = false;
        function toggleDrag() {
            isDragMode = !isDragMode; const btn = document.getElementById('lock-btn');
            if(isDragMode) { fetch('/mouse_down'); btn.innerHTML = '<span class="material-icons">lock</span>'; btn.classList.add('active-lock'); }
            else { fetch('/mouse_up'); btn.innerHTML = '<span class="material-icons">lock_open</span>'; btn.classList.remove('active-lock'); }
        }
        let lastMoveTime = 0; const MOVE_THROTTLE = 12; let lastX = 0, lastY = 0, startDist = 0, touchStartTime = 0, isDragging = false, startY_3 = 0, maxFingers = 0;
        document.body.addEventListener('touchstart', (e) => {
            if(e.target.closest('.icon-btn, #fs-btn-main, #kbd-btn, input, button, .mini-btn')) return;
            maxFingers = Math.max(maxFingers, e.touches.length);
            if(e.touches.length === 1) { lastX = e.touches[0].clientX; lastY = e.touches[0].clientY; touchStartTime = new Date().getTime(); isDragging = false; maxFingers = 1; }
            else if (e.touches.length === 2) { startDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); lastY = e.touches[0].clientY; }
            else if (e.touches.length === 3) { startY_3 = e.touches[0].clientY; }
        }, {passive: false});
        document.body.addEventListener('touchmove', (e) => {
            if(e.target.closest('.icon-btn, #fs-btn-main, #kbd-btn, input, button, .mini-btn')) return;
            e.preventDefault(); maxFingers = Math.max(maxFingers, e.touches.length);
            const now = Date.now(); if (now - lastMoveTime < MOVE_THROTTLE) return; lastMoveTime = now;
            if(e.touches.length === 1) { 
                let curX = e.touches[0].clientX, curY = e.touches[0].clientY, dx, dy;
                if (isFullScreen) { dx = (curY - lastY) * cursorSpeed; dy = -(curX - lastX) * cursorSpeed; lastX = curX; lastY = curY; }
                else { dx = (curX - lastX) * cursorSpeed; dy = (curY - lastY) * cursorSpeed; lastX = curX; lastY = curY; }
                if (Math.abs(dx) > 1 || Math.abs(dy) > 1) { fetch(`/move?x=${dx}&y=${dy}`, {keepalive: true}); isDragging = true; } 
            }
            else if (e.touches.length === 2) {
                let newDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY);
                let distChange = newDist - startDist;
                if (Math.abs(distChange) > zoomThreshold) { if (distChange > 0) fetch('/zoom?dir=in'); else fetch('/zoom?dir=out'); startDist = newDist; }
                else {
                    let scrollY = isFullScreen ? -(e.touches[0].clientX - lastX) : (e.touches[0].clientY - lastY);
                    if (!isFullScreen) lastY = e.touches[0].clientY; else lastX = e.touches[0].clientX;
                    if (Math.abs(scrollY) > 2) fetch(`/scroll?dy=${scrollY * scrollSpeed}`);
                }
            }
            else if (e.touches.length === 3) {
                let currentY = e.touches[0].clientY;
                if ((currentY - startY_3) > 150) { fetch('/screenshot'); startY_3 = 9999; if(navigator.vibrate) navigator.vibrate(100); }
            }
        }, {passive: false});
        document.body.addEventListener('touchend', (e) => {
            if(e.target.closest('.icon-btn, #fs-btn-main, #kbd-btn, input, button, .mini-btn')) return;
            let timeDiff = new Date().getTime() - touchStartTime;
            if (!isDragging && timeDiff < 300) { if (maxFingers === 1) fetch('/click?type=left'); else if (maxFingers === 2) fetch('/click?type=right'); }
            if (e.touches.length === 0) maxFingers = 0;
        });
        const inputField = document.getElementById('hidden-input');
        function toggleKeyboard() { inputField.focus(); inputField.click(); }
        inputField.addEventListener('input', () => { if(inputField.value.length > 0) { fetch('/type?text=' + encodeURIComponent(inputField.value)); inputField.value = ""; } });
        inputField.addEventListener('keydown', (e) => { if(e.key === 'Backspace') fetch('/key?k=backspace'); if(e.key === 'Enter') fetch('/key?k=enter'); });
    </script>
</body>
</html>
"""

# --- ROUTES ---
@app.before_request
def require_login():
    allowed = ['login', 'check_pin', 'static']
    if request.endpoint not in allowed and 'logged_in' not in session: return redirect(url_for('login'))
@app.route('/login')
def login(): return render_template_string(login_html)
@app.route('/logout')
def logout(): session.pop('logged_in', None); return redirect(url_for('login'))
@app.route('/check_pin')
def check_pin(): 
    if request.args.get('p', '').strip() == ACCESS_PIN: session['logged_in'] = True; session.permanent = False; return jsonify({'valid': True})
    return jsonify({'valid': False})
@app.route('/')
def home(): return render_template_string(main_html)
@app.route('/power')
def power_action():
    act = request.args.get('act')
    if act == 'shutdown': os.system("shutdown /s /t 1")
    elif act == 'sleep': os.system("rundll32.exe powrprof.dll,SetSuspendState 0,1,0")
    return ""
@app.route('/volume')
def set_volume():
    action = request.args.get('act')
    if action == 'up': pyautogui.press('volumeup')
    elif action == 'down': pyautogui.press('volumedown')
    return ""
@app.route('/screenshot')
def take_screenshot():
    try:
        filename = f"MagicTracker_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        full_path = os.path.join(os.getcwd(), filename)
        pyautogui.screenshot(full_path)
    except: pass
    return ""
@app.route('/click')
def click_mouse():
    t = request.args.get('type')
    if t == 'left': pyautogui.click()
    elif t == 'right': pyautogui.rightClick()
    return ""
@app.route('/status')
def get_status():
    global last_net_bytes, last_net_time
    bat_info = "N/A"; is_plugged = False; uptime = "--"; speed_str = "0 KB/s"
    if psutil:
        try:
            battery = psutil.sensors_battery()
            if battery: bat_info = f"{int(battery.percent)}%"; is_plugged = battery.power_plugged
            uptime = get_uptime()
            now = time.time(); current_bytes = psutil.net_io_counters().bytes_sent
            if last_net_time > 0:
                delta = now - last_net_time
                if delta > 0: speed = (current_bytes - last_net_bytes) / delta; speed_str = f"{speed/(1024*1024):.1f} MB/s" if speed > 1024*1024 else f"{speed/1024:.0f} KB/s"
            last_net_bytes = current_bytes; last_net_time = now
        except: pass
    return jsonify({'battery': bat_info, 'plugged': is_plugged, 'uptime': uptime, 'host': HOSTNAME, 'ssid': get_ssid(), 'fps': current_fps, 'upload_speed': speed_str})
def generate_frames_from_streamer():
    while True:
        with streamer.lock: frame = streamer.current_frame
        if frame: yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
        else: time.sleep(0.01)
@app.route('/start_stream')
def start_stream(): streamer.start(); return "started"
@app.route('/stop_stream')
def stop_stream(): return "stopped"
@app.route('/video_feed')
def video_feed(): streamer.start(); return Response(generate_frames_from_streamer(), mimetype='multipart/x-mixed-replace; boundary=frame')
@app.route('/set_quality')
def set_quality(): 
    try: streamer.set_quality(int(request.args.get('level'))); return ""
    except: return ""
@app.route('/move')
def move_mouse():
    try: pyautogui.moveRel(float(request.args.get('x')), float(request.args.get('y')), _pause=False); return ""
    except: return ""
@app.route('/mouse_down')
def mouse_down(): pyautogui.mouseDown(); return ""
@app.route('/mouse_up')
def mouse_up(): pyautogui.mouseUp(); return ""
@app.route('/scroll')
def scroll_screen():
    try: pyautogui.scroll(int(float(request.args.get('dy')) * 4)); return ""
    except: return ""
@app.route('/zoom')
def zoom_screen():
    d = request.args.get('dir'); key = '+' if d == 'in' else '-'; pyautogui.hotkey('ctrl', key); return ""
@app.route('/type')
def type_text(): pyautogui.write(request.args.get('text')); return ""
@app.route('/key')
def special_key(): pyautogui.press(request.args.get('k')); return ""

if __name__ == '__main__':
    threading.Thread(target=show_pin_popup, daemon=True).start()
    streamer.start()
    app.run(host='0.0.0.0', port=5000, threaded=True)