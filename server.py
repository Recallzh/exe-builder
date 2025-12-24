import http.server
import socketserver
import threading
import tkinter as tk
from tkinter import messagebox
import winsound
import urllib.parse
import sys
import logging
import json
import time
import ctypes
from datetime import datetime

# ================= 配置与状态 =================
PORT = 16888
LOG_FILE = "server.log"

# 全局状态存储
STATE = {
    "start_time": time.time(),
    "alarm_count": 0,
    "sound_enabled": True,
    "is_running": True
}

# ================= 嵌入式高颜值 HTML 前端 =================
# 这里使用了 f-string 将 Python 变量注入到 HTML 中
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>工单监控中控台</title>
    <style>
        :root {{
            --bg-color: #121212;
            --card-bg: #1E1E1E;
            --accent: #FF4500;
            --text-main: #FFFFFF;
            --text-sub: #AAAAAA;
            --success: #00FF7F;
        }}
        body {{
            font-family: 'Segoe UI', Microsoft YaHei, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
        }}
        .dashboard {{
            width: 400px;
            background: var(--card-bg);
            border-radius: 16px;
            padding: 30px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.5);
            border: 1px solid #333;
        }}
        .header {{
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 30px;
            border-bottom: 2px solid var(--accent);
            padding-bottom: 15px;
        }}
        .title {{ font-size: 20px; font-weight: bold; }}
        .status-dot {{
            height: 10px; width: 10px;
            background-color: var(--success);
            border-radius: 50%;
            box-shadow: 0 0 10px var(--success);
            animation: pulse 2s infinite;
        }}
        @keyframes pulse {{ 0% {{ opacity: 1; }} 50% {{ opacity: 0.5; }} 100% {{ opacity: 1; }} }}
        
        .stat-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 30px;
        }}
        .stat-box {{
            background: #252525;
            padding: 15px;
            border-radius: 10px;
            text-align: center;
        }}
        .stat-num {{ font-size: 24px; font-weight: bold; color: var(--accent); }}
        .stat-label {{ font-size: 12px; color: var(--text-sub); margin-top: 5px; }}

        .controls {{ display: flex; flex-direction: column; gap: 15px; }}
        .btn {{
            padding: 12px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-weight: bold;
            transition: 0.2s;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .btn-toggle {{ background: #333; color: white; }}
        .btn-toggle.active {{ background: var(--accent); }}
        .btn-danger {{ background: #8B0000; color: white; justify-content: center; margin-top: 10px; }}
        .btn:hover {{ opacity: 0.9; transform: translateY(-2px); }}

    </style>
</head>
<body>
    <div class="dashboard">
        <div class="header">
            <div class="title">SERVER DASHBOARD</div>
            <div class="status-dot"></div>
        </div>

        <div class="stat-grid">
            <div class="stat-box">
                <div class="stat-num" id="alarm-count">--</div>
                <div class="stat-label">已拦截工单</div>
            </div>
            <div class="stat-box">
                <div class="stat-num" id="uptime">--</div>
                <div class="stat-label">运行时间 (分钟)</div>
            </div>
        </div>

        <div class="controls">
            <button class="btn btn-toggle" id="btn-sound" onclick="toggleSound()">
                <span>🔊 声音提醒</span>
                <span id="sound-status">ON</span>
            </button>
            <button class="btn btn-toggle" onclick="testAlarm()">
                <span>🔔 测试弹窗</span>
                <span>TEST</span>
            </button>
            <button class="btn btn-danger" onclick="shutdown()">
                ❌ 关闭监控程序
            </button>
        </div>
    </div>

    <script>
        function updateStats() {{
            fetch('/api/status').then(r => r.json()).then(data => {{
                document.getElementById('alarm-count').innerText = data.alarm_count;
                document.getElementById('uptime').innerText = Math.floor(data.uptime / 60);
                
                const sndBtn = document.getElementById('btn-sound');
                const sndTxt = document.getElementById('sound-status');
                if(data.sound_enabled) {{
                    sndBtn.classList.add('active');
                    sndTxt.innerText = "ON";
                }} else {{
                    sndBtn.classList.remove('active');
                    sndTxt.innerText = "OFF";
                }}
            }});
        }}

        function toggleSound() {{ fetch('/api/toggle_sound').then(updateStats); }}
        function testAlarm() {{ fetch('/?mode=test_ui'); }}
        function shutdown() {{ 
            if(confirm('确定要彻底关闭服务吗？网页将无法再访问。')) {{
                fetch('/api/shutdown');
                document.body.innerHTML = "<h1 style='color:white;text-align:center;'>服务已断开</h1>";
            }}
        }}

        setInterval(updateStats, 2000); // 每2秒刷新一次数据
        updateStats();
    </script>
</body>
</html>
"""

# ================= 后端逻辑 =================

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger()

class ModernAlert(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg="#1E1E1E")
        w, h = 420, 240
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(screen_w-w)//2}+{(screen_h-h)//2}")
        self.attributes('-alpha', 0.0)
        self.setup_ui()
        if STATE["sound_enabled"]:
            self.play_sound()
        self.fade_in()

    def setup_ui(self):
        # 橙色装饰条
        tk.Frame(self, bg="#FF4500", height=8).pack(fill='x', side='top')
        
        content = tk.Frame(self, bg="#1E1E1E", padx=30, pady=20)
        content.pack(fill='both', expand=True)

        tk.Label(content, text="🚨 发现紧急工单", font=("Microsoft YaHei UI", 18, "bold"), 
                 bg="#1E1E1E", fg="white").pack(pady=(10,5))
        
        tk.Label(content, text="监测到新的待处理工单\n请立即前往处理！", font=("Microsoft YaHei UI", 11), 
                 bg="#1E1E1E", fg="#AAAAAA").pack(pady=10)

        btn = tk.Button(content, text="立即处理", command=self.close_anim,
                        font=("Microsoft YaHei UI", 12, "bold"),
                        bg="#FF4500", fg="white", relief="flat", padx=30, pady=8, cursor="hand2")
        btn.pack(pady=20)
        btn.bind("<Enter>", lambda e: btn.configure(bg="#FF6347"))
        btn.bind("<Leave>", lambda e: btn.configure(bg="#FF4500"))

    def play_sound(self):
        try: winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except: pass

    def fade_in(self):
        alpha = self.attributes("-alpha")
        if alpha < 1.0:
            self.attributes("-alpha", alpha + 0.05)
            self.after(20, self.fade_in)

    def close_anim(self):
        self.destroy()

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        path = parsed.path

        # 1. API: 状态查询 (JSON)
        if path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            data = {
                "uptime": time.time() - STATE["start_time"],
                "alarm_count": STATE["alarm_count"],
                "sound_enabled": STATE["sound_enabled"]
            }
            self.wfile.write(json.dumps(data).encode())
            return

        # 2. API: 切换声音
        elif path == '/api/toggle_sound':
            STATE["sound_enabled"] = not STATE["sound_enabled"]
            self.send_response(200)
            self.end_headers()
            return

        # 3. API: 关闭程序
        elif path == '/api/shutdown':
            self.send_response(200)
            self.end_headers()
            logger.info("收到远程关闭指令，即将退出...")
            root.after(100, lambda: root.destroy()) # 通知 UI 线程退出
            return

        # 4. API: 原始工单接口 / 测试接口
        elif 'mode' in query:
            mode = query['mode'][0]
            if mode == 'alarm':
                STATE["alarm_count"] += 1
                logger.warning("触发报警")
                root.event_generate("<<Alarm>>")
            elif mode == 'test_ui':
                root.event_generate("<<Alarm>>")
            elif mode == 'test':
                pass # 心跳
            
            self.send_response(200)
            self.end_headers()
            return

        # 5. 默认: 返回管理页面 HTML
        else:
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode('utf-8'))

def start_server():
    try:
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
            logger.info(f"Admin Dashboard: http://localhost:{PORT}")
            httpd.serve_forever()
    except Exception as e:
        logger.error(f"Error: {e}")
        root.after(0, root.destroy)

def on_alarm(event):
    ModernAlert(root)

# ================= 主程序 =================
if __name__ == "__main__":
    try: ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except: pass

    root = tk.Tk()
    root.withdraw() # 隐藏主窗口
    root.bind("<<Alarm>>", on_alarm)
    
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    
    root.mainloop()
    sys.exit()
