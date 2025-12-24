import threading
import tkinter as tk
import winsound
import webbrowser
import socket
import logging
import sys
import uvicorn
import time
import json
import random
from collections import deque
from datetime import datetime
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# ================= 配置与全局状态 =================
class Config:
    DEFAULT_PORT = 16888
    MAX_PORT_RETRIES = 10
    LOG_LIMIT = 50  # Web端保留最近50条日志

# 全局状态 (线程安全需注意，这里简化处理)
STATE = {
    "start_time": time.time(),
    "alarm_count": 0,
    "sound_enabled": True,
    "logs": deque(maxlen=Config.LOG_LIMIT),
    "history_data": deque(maxlen=20) # 存储最近20个时间点的数据用于绘图
}

# 初始化图表数据
for i in range(20):
    STATE["history_data"].append(0)

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger("Monitor")

def add_web_log(message):
    """同时记录到控制台和Web内存日志"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = {"time": timestamp, "msg": message}
    STATE["logs"].appendleft(log_entry) # 最新在最前
    logger.info(message)

# ================= 核心工具函数 =================
def find_free_port(start_port):
    """自动寻找可用端口"""
    for port in range(start_port, start_port + Config.MAX_PORT_RETRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
    return start_port # 如果都失败，硬着头皮用原端口（或抛异常）

# ================= FastAPI 后端 =================
app = FastAPI(docs_url=None, redoc_url=None) # 关闭文档以隐藏

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 极简高颜值前端 HTML (内嵌) ---
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
        .stat-card {
            transition: transform 0.3s;
        }
        .stat-card:hover { transform: translateY(-5px); }
        .text-neon { color: #00f2ff; text-shadow: 0 0 10px rgba(0, 242, 255, 0.5); }
        .text-alert { color: #ff4500; text-shadow: 0 0 10px rgba(255, 69, 0, 0.5); }
        
        /* 滚动条美化 */
        ::-webkit-scrollbar { width: 8px; }
        ::-webkit-scrollbar-track { background: rgba(0,0,0,0.1); }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.2); border-radius: 4px; }
    </style>
</head>
<body class="p-4">
    <div class="container" style="max-width: 900px;">
        <div class="d-flex justify-content-between align-items-center mb-4 glass-panel">
            <div class="d-flex align-items-center">
                <div class="spinner-grow text-success me-3" role="status" style="width: 1rem; height: 1rem;"></div>
                <h3 class="m-0 fw-bold">HEIMDALLR <span style="font-weight:300; font-size: 0.8em; opacity: 0.7;">工单监控系统</span></h3>
            </div>
            <div class="text-end">
                <small class="text-muted d-block">System Status</small>
                <span class="badge bg-success bg-opacity-25 text-success border border-success">ONLINE</span>
            </div>
        </div>

        <div class="row g-4 mb-4">
            <div class="col-md-4">
                <div class="glass-panel stat-card text-center h-100">
                    <h6 class="text-muted text-uppercase mb-3">已拦截工单</h6>
                    <h1 class="display-4 fw-bold text-alert" id="alarm-count">--</h1>
                </div>
            </div>
            <div class="col-md-4">
                <div class="glass-panel stat-card text-center h-100">
                    <h6 class="text-muted text-uppercase mb-3">系统运行时间</h6>
                    <h2 class="fw-bold mt-2" id="uptime">--:--:--</h2>
                </div>
            </div>
            <div class="col-md-4">
                <div class="glass-panel stat-card d-flex flex-column justify-content-center gap-2 h-100">
                    <button class="btn btn-outline-light w-100" id="btn-sound" onclick="toggleSound()">
                        🔊 声音: <span id="sound-status">ON</span>
                    </button>
                    <button class="btn btn-danger w-100 bg-opacity-50" onclick="testAlarm()">
                        🔔 发送测试警报
                    </button>
                </div>
            </div>
        </div>

        <div class="row g-4">
            <div class="col-md-8">
                <div class="glass-panel h-100">
                    <h6 class="mb-3 border-bottom border-secondary pb-2">实时工单密度</h6>
                    <canvas id="trafficChart" height="200"></canvas>
                </div>
            </div>
            
            <div class="col-md-4">
                <div class="glass-panel h-100 d-flex flex-column" style="max-height: 330px;">
                    <h6 class="mb-3 border-bottom border-secondary pb-2">系统日志</h6>
                    <div id="log-container" style="overflow-y: auto; flex: 1; font-size: 12px; font-family: monospace;">
                        </div>
                </div>
            </div>
        </div>
    </div>

    <script>
        const ctx = document.getElementById('trafficChart').getContext('2d');
        const chart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: Array(20).fill(''),
                datasets: [{
                    label: '工单活动',
                    data: Array(20).fill(0),
                    borderColor: '#00f2ff',
                    backgroundColor: 'rgba(0, 242, 255, 0.1)',
                    tension: 0.4,
                    fill: true,
                    pointRadius: 0
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: { 
                    x: { display: false },
                    y: { grid: { color: 'rgba(255,255,255,0.05)' } }
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
            fetch('/api/status').then(r => r.json()).then(data => {
                // 更新数字
                document.getElementById('alarm-count').innerText = data.alarm_count;
                document.getElementById('uptime').innerText = formatTime(data.uptime);
                
                // 更新声音按钮
                const sndStat = document.getElementById('sound-status');
                const sndBtn = document.getElementById('btn-sound');
                if (data.sound_enabled) {
                    sndStat.innerText = "ON";
                    sndBtn.classList.remove('btn-secondary');
                    sndBtn.classList.add('btn-outline-light');
                } else {
                    sndStat.innerText = "OFF";
                    sndBtn.classList.add('btn-secondary');
                    sndBtn.classList.remove('btn-outline-light');
                }

                // 更新日志
                const logDiv = document.getElementById('log-container');
                logDiv.innerHTML = data.logs.map(l => 
                    `<div class="mb-1"><span class="text-secondary">[${l.time}]</span> ${l.msg}</div>`
                ).join('');

                // 更新图表 (模拟数据移动)
                chart.data.datasets[0].data = data.history;
                chart.update();
            });
        }

        function toggleSound() { fetch('/api/toggle_sound').then(updateData); }
        function testAlarm() { fetch('/api/trigger_alarm'); }

        setInterval(updateData, 1500);
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
        "alarm_count": STATE["alarm_count"],
        "sound_enabled": STATE["sound_enabled"],
        "logs": list(STATE["logs"]),
        "history": list(STATE["history_data"])
    }

@app.get("/api/toggle_sound")
async def toggle_sound():
    STATE["sound_enabled"] = not STATE["sound_enabled"]
    add_web_log(f"声音状态切换为: {STATE['sound_enabled']}")
    return {"status": "ok"}

@app.get("/api/trigger_alarm")
async def trigger_alarm_api(request: Request):
    # 可以在这里增加逻辑，比如 ?msg=xxx
    STATE["alarm_count"] += 1
    
    # 模拟图表数据波动
    current_val = list(STATE["history_data"])[-1]
    STATE["history_data"].append(current_val + 5) # 突增
    
    add_web_log(">>> 触发报警指令")
    
    # 线程安全地触发 Tkinter 事件
    if gui_root:
        gui_root.event_generate("<<Alarm>>")
    
    return {"status": "triggered"}

@app.get("/heartbeat")
async def heartbeat():
    # 维持图表平滑，如果没有报警，数据慢慢回落
    data = STATE["history_data"]
    last = data[-1]
    if last > 0:
        data.append(max(0, last - 1))
    else:
        data.append(0)
    return {"status": "alive"}

# ================= 桌面端 GUI (Tkinter) =================
class ModernAlert(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.configure(bg="#1a1a1a")
        
        # 居中显示
        w, h = 400, 220
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(screen_w-w)//2}+{(screen_h-h)//2}")
        
        # 初始透明度
        self.attributes('-alpha', 0.0)
        
        # UI
        tk.Frame(self, bg="#FF4500", height=4).pack(fill='x', side='top')
        
        content = tk.Frame(self, bg="#1a1a1a")
        content.pack(fill='both', expand=True, padx=20, pady=20)
        
        tk.Label(content, text="⚠️ 新工单提醒", font=("Microsoft YaHei UI", 16, "bold"), 
                 bg="#1a1a1a", fg="white").pack(pady=(5, 5))
        
        tk.Label(content, text="检测到高优先级任务，请立即处理", font=("Microsoft YaHei UI", 10), 
                 bg="#1a1a1a", fg="#888").pack(pady=5)
                 
        btn = tk.Button(content, text="我知道了", command=self.close_anim,
                        font=("Microsoft YaHei UI", 10), bg="#333", fg="white", 
                        relief="flat", activebackground="#444", activeforeground="white",
                        width=20, pady=5)
        btn.pack(side="bottom", pady=10)

        if STATE["sound_enabled"]:
            threading.Thread(target=lambda: winsound.Beep(1000, 400), daemon=True).start()

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
    add_web_log(f"服务启动，监听端口: {port}")
    # uvicorn.run 是阻塞的，所以必须放在独立线程
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="error")

# ================= 启动入口 =================
if __name__ == "__main__":
    # 1. 解决端口问题
    active_port = find_free_port(Config.DEFAULT_PORT)
    
    # 2. 启动 Web 线程
    server_thread = threading.Thread(target=start_fastapi, args=(active_port,), daemon=True)
    server_thread.start()

    # 3. 启动 GUI
    gui_root = tk.Tk()
    gui_root.withdraw() # 隐藏主窗口
    gui_root.bind("<<Alarm>>", on_alarm_event)
    
    add_web_log("系统初始化完成")
    
    # 自动打开浏览器
    time.sleep(1) # 等待服务器启动
    webbrowser.open(f"http://localhost:{active_port}")

    # 心跳定时器 (用于模拟数据波动)
    def heartbeat_loop():
        # 简单的模拟数据衰减，保持图表在动
        last = STATE["history_data"][-1]
        if last > 0:
            STATE["history_data"].append(max(0, last - random.uniform(0, 2)))
        else:
            STATE["history_data"].append(0)
        gui_root.after(2000, heartbeat_loop)
    
    heartbeat_loop()
    
    try:
        gui_root.mainloop()
    except KeyboardInterrupt:
        sys.exit()
