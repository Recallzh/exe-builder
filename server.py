import threading
import tkinter as tk
import webbrowser
import socket
import logging
import sys
import uvicorn
import time
import json
import os
import multiprocessing  # 【新增】用于修复 Windows 打包后的进程问题
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from logging.handlers import RotatingFileHandler

# ================= 配置与全局状态 =================
class Config:
    DEFAULT_PORT = 16888
    MAX_PORT_RETRIES = 10
    LOG_FILE = "monitor.log"
    DATA_FILE = "monitor_data.json"  # 【新增】数据存储文件路径

# ================= 数据持久化工具 (功能点 1) =================
def load_state():
    """读取数据：如果文件存在且是今天的日期，则加载；否则重置为0"""
    default_state = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_today": 0,
        "hourly_counts": [0] * 24
    }
    
    if not os.path.exists(Config.DATA_FILE):
        return default_state
    
    try:
        with open(Config.DATA_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
            # 检查日期：如果存档日期不是今天，则重置
            if saved.get("date") != datetime.now().strftime("%Y-%m-%d"):
                return default_state
            return saved
    except Exception as e:
        print(f"数据加载失败，使用默认值: {e}")
        return default_state

def save_state():
    """保存数据：将当前内存中的计数写入文件"""
    current_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_today": STATE["total_today"],
        "hourly_counts": STATE["hourly_counts"]
    }
    try:
        with open(Config.DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"数据保存失败: {e}")

# ================= 初始化系统 =================
# 1. 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(Config.LOG_FILE, maxBytes=1024*1024, backupCount=3, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Monitor")

# 2. 初始化状态 (从文件加载)
saved_data = load_state()
STATE = {
    "start_time": time.time(),
    "total_today": saved_data["total_today"],
    "hourly_counts": saved_data["hourly_counts"]
}

# ================= 核心工具函数 =================
def find_free_port(start_port):
    """自动寻找可用端口"""
    for port in range(start_port, start_port + Config.MAX_PORT_RETRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
    return start_port

def get_current_hour():
    return datetime.now().hour

# ================= FastAPI 后端 =================
app = FastAPI(docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 前端 HTML ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN" data-bs-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>工单监控中心</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body {
            background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
            font-family: 'Segoe UI', sans-serif;
            min-height: 100vh;
            color: #fff;
            overflow-x: hidden;
        }
        .glass-panel {
            background: rgba(255, 255, 255, 0.05);
            backdrop-filter: blur(10px);
            -webkit-backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37);
        }
        .text-alert { color: #ff4500; text-shadow: 0 0 10px rgba(255, 69, 0, 0.5); }
    </style>
</head>
<body class="p-4">
    <div class="container" style="max-width: 900px;">
        <div class="d-flex justify-content-between align-items-center mb-4 glass-panel">
            <div class="d-flex align-items-center">
                <div class="spinner-grow text-success me-3" role="status" style="width: 1rem; height: 1rem;"></div>
                <h3 class="m-0 fw-bold">HEIMDALLR <span style="font-weight:300; font-size: 0.8em; opacity: 0.7;">监控系统</span></h3>
            </div>
            <div>
                <span class="badge bg-primary bg-opacity-25 border border-primary me-2" id="current-time">--:--</span>
                <span class="badge bg-success bg-opacity-25 text-success border border-success">RUNNING</span>
            </div>
        </div>

        <div class="row g-4 mb-4">
            <div class="col-md-6">
                <div class="glass-panel text-center h-100">
                    <h6 class="text-muted text-uppercase mb-3">今日拦截总量</h6>
                    <h1 class="display-3 fw-bold text-alert" id="total-today">0</h1>
                </div>
            </div>
            <div class="col-md-6">
                <div class="glass-panel d-flex flex-column justify-content-center gap-3 h-100">
                     <div class="d-flex justify-content-between px-4">
                        <span class="text-muted">运行时间</span>
                        <span class="fw-bold" id="uptime">--:--:--</span>
                     </div>
                     <button class="btn btn-danger w-100 bg-opacity-50 mx-auto" style="max-width:80%;" onclick="testAlarm()">
                        🔔 发送测试警报
                    </button>
                    <div class="text-center text-muted" style="font-size: 12px;">数据自动保存至本地 monitor_data.json</div>
                </div>
            </div>
        </div>

        <div class="glass-panel">
            <h6 class="mb-3 border-bottom border-secondary pb-2">今日工单分布 (00:00 - 23:00)</h6>
            <canvas id="dailyChart" height="100"></canvas>
        </div>
    </div>

    <script>
        const hours = Array.from({length: 24}, (_, i) => i + ":00");
        const ctx = document.getElementById('dailyChart').getContext('2d');
        const chart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: hours,
                datasets: [{
                    label: '工单数量',
                    data: Array(24).fill(0),
                    backgroundColor: 'rgba(0, 242, 255, 0.5)',
                    borderColor: '#00f2ff',
                    borderWidth: 1,
                    borderRadius: 4
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { 
                    y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { stepSize: 1 } },
                    x: { grid: { display: false } }
                }
            }
        });

        function formatTime(seconds) {
            const h = Math.floor(seconds / 3600);
            const m = Math.floor((seconds % 3600) / 60);
            const s = Math.floor(seconds % 60);
            return `${h.toString().padStart(2,'0')}:${m.toString().padStart(2,'0')}:${s.toString().padStart(2,'0')}`;
        }

        function updateData() {
            const now = new Date();
            document.getElementById('current-time').innerText = now.toLocaleTimeString();

            fetch('/api/status').then(r => r.json()).then(data => {
                document.getElementById('total-today').innerText = data.total_today;
                document.getElementById('uptime').innerText = formatTime(data.uptime);
                chart.data.datasets[0].data = data.hourly_counts;
                chart.update();
            });
        }

        function testAlarm() { fetch('/api/trigger_alarm'); }
        setInterval(updateData, 5000);
        updateData();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return HTML_TEMPLATE

@app.get("/api/status")
async def get_status():
    return {
        "uptime": time.time() - STATE["start_time"],
        "total_today": STATE["total_today"],
        "hourly_counts": STATE["hourly_counts"]
    }

@app.get("/api/trigger_alarm")
async def trigger_alarm_api():
    # 增加计数
    STATE["total_today"] += 1
    STATE["hourly_counts"][get_current_hour()] += 1
    
    # 【重点】每次触发报警立即保存，防止突然断电数据丢失
    save_state()
    
    logger.info(f"触发报警 - 当前总量: {STATE['total_today']}")
    
    if gui_root:
        gui_root.event_generate("<<Alarm>>")
    
    return {"status": "triggered"}

# ================= 桌面端 GUI (Tkinter) =================
class ModernAlert(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg="#1a1a1a")
        
        w, h = 400, 180
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(screen_w-w)//2}+{(screen_h-h)//2}")
        self.attributes('-alpha', 0.0)
        
        tk.Frame(self, bg="#FF4500", height=4).pack(fill='x', side='top')
        
        content = tk.Frame(self, bg="#1a1a1a")
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        tk.Label(content, text="⚠️ 新工单提醒", font=("Microsoft YaHei UI", 16, "bold"), 
                 bg="#1a1a1a", fg="white").pack(pady=(5, 5))
                 
        btn = tk.Button(content, text="我知道了", command=self.close_anim,
                        font=("Microsoft YaHei UI", 10), bg="#333", fg="white", 
                        relief="flat", activebackground="#444", activeforeground="white",
                        width=20, pady=5)
        btn.pack(side="bottom", pady=10)

        self.fade_in()

    def fade_in(self):
        alpha = self.attributes("-alpha")
        if alpha < 0.95:
            self.attributes("-alpha", alpha + 0.1)
            self.after(20, self.fade_in)

    def close_anim(self):
        self.destroy()

def on_alarm_event(event):
    ModernAlert(gui_root)

def start_fastapi(port):
    logger.info(f"Web服务正在启动: http://localhost:{port}")
    # log_level设置为warning减少干扰，workers必须为1
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

# ================= 启动入口 =================
if __name__ == "__main__":
    # 【功能点 2】修复 Windows 打包多进程死循环问题 (必须放在第一行)
    multiprocessing.freeze_support()
    
    # 修复终端中文乱码
    sys.stdout.reconfigure(encoding='utf-8')
    
    print(">>> 正在初始化监控系统...")
    
    # 1. 查找端口
    active_port = find_free_port(Config.DEFAULT_PORT)
    
    # 2. 启动服务线程
    server_thread = threading.Thread(target=start_fastapi, args=(active_port,), daemon=True)
    server_thread.start()

    # 3. 初始化 GUI
    gui_root = tk.Tk()
    gui_root.withdraw()
    gui_root.bind("<<Alarm>>", on_alarm_event)
    
    # 4. 自动打开浏览器
    def open_browser():
        time.sleep(1.5)
        url = f"http://localhost:{active_port}"
        print(f">>> 控制台地址: {url}")
        webbrowser.open(url)
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    print(">>> 服务运行中。关闭此窗口即可退出。")
    
    try:
        gui_root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        # 【重点】正常退出时也保存一次数据
        save_state()
        logger.info("程序退出，数据已保存。")
