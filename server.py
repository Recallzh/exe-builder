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
import multiprocessing
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from logging.handlers import RotatingFileHandler

# ================= 1. 配置与全局状态 =================
class Config:
    DEFAULT_PORT = 16888
    MAX_PORT_RETRIES = 10
    LOG_FILE = "monitor.log"
    DATA_FILE = "monitor_data.json"  # 数据存储文件

# ================= 2. 数据持久化 (防丢失) =================
def load_state():
    """读取数据：如果文件存在且是今天的日期，则加载；否则重置"""
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
            if saved.get("date") != datetime.now().strftime("%Y-%m-%d"):
                return default_state
            return saved
    except Exception as e:
        print(f"数据加载失败，使用默认值: {e}")
        return default_state

def save_state():
    """保存当前状态到本地文件"""
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

# ================= 3. 初始化系统 =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(Config.LOG_FILE, maxBytes=1024*1024, backupCount=3, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("Monitor")

saved_data = load_state()
STATE = {
    "start_time": time.time(),
    "total_today": saved_data["total_today"],
    "hourly_counts": saved_data["hourly_counts"]
}

# ================= 4. 核心工具函数 =================
def find_free_port(start_port):
    for port in range(start_port, start_port + Config.MAX_PORT_RETRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0:
                return port
    return start_port

def get_current_hour():
    return datetime.now().hour

# ================= 5. FastAPI 后端 =================
app = FastAPI(docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
        body { background: linear-gradient(135deg, #0f0c29, #302b63, #24243e); font-family: 'Segoe UI', sans-serif; min-height: 100vh; color: #fff; }
        .glass-panel { background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 20px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37); }
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
            <div><span class="badge bg-primary bg-opacity-25 border border-primary me-2" id="current-time">--:--</span><span class="badge bg-success bg-opacity-25 text-success border border-success">RUNNING</span></div>
        </div>
        <div class="row g-4 mb-4">
            <div class="col-md-6"><div class="glass-panel text-center h-100"><h6 class="text-muted text-uppercase mb-3">今日拦截总量</h6><h1 class="display-3 fw-bold text-alert" id="total-today">0</h1></div></div>
            <div class="col-md-6"><div class="glass-panel d-flex flex-column justify-content-center gap-3 h-100"><div class="d-flex justify-content-between px-4"><span class="text-muted">运行时间</span><span class="fw-bold" id="uptime">--:--:--</span></div><button class="btn btn-danger w-100 bg-opacity-50 mx-auto" style="max-width:80%;" onclick="testAlarm()">🔔 发送测试警报</button><div class="text-center text-muted" style="font-size: 12px;">数据自动保存至本地 monitor_data.json</div></div></div>
        </div>
        <div class="glass-panel"><h6 class="mb-3 border-bottom border-secondary pb-2">今日工单分布</h6><canvas id="dailyChart" height="100"></canvas></div>
    </div>
    <script>
        const ctx = document.getElementById('dailyChart').getContext('2d');
        const chart = new Chart(ctx, { type: 'bar', data: { labels: Array.from({length: 24}, (_, i) => i + ":00"), datasets: [{ label: '工单数量', data: Array(24).fill(0), backgroundColor: 'rgba(0, 242, 255, 0.5)', borderColor: '#00f2ff', borderWidth: 1, borderRadius: 4 }] }, options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' } }, x: { grid: { display: false } } } } });
        function formatTime(s) { return `${Math.floor(s/3600).toString().padStart(2,'0')}:${Math.floor((s%3600)/60).toString().padStart(2,'0')}:${Math.floor(s%60).toString().padStart(2,'0')}`; }
        function updateData() { document.getElementById('current-time').innerText = new Date().toLocaleTimeString(); fetch('/api/status').then(r => r.json()).then(data => { document.getElementById('total-today').innerText = data.total_today; document.getElementById('uptime').innerText = formatTime(data.uptime); chart.data.datasets[0].data = data.hourly_counts; chart.update(); }); }
        function testAlarm() { fetch('/api/trigger_alarm'); }
        setInterval(updateData, 5000); updateData();
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def read_root():
    return HTML_TEMPLATE

@app.get("/api/status")
async def get_status():
    return { "uptime": time.time() - STATE["start_time"], "total_today": STATE["total_today"], "hourly_counts": STATE["hourly_counts"] }

@app.get("/api/trigger_alarm")
async def trigger_alarm_api():
    STATE["total_today"] += 1
    STATE["hourly_counts"][get_current_hour()] += 1
    save_state() # 立即保存
    logger.info(f"触发报警 - 当前总量: {STATE['total_today']}")
    if gui_root:
        gui_root.event_generate("<<Alarm>>")
    return {"status": "triggered"}

# ================= 6. 桌面端 GUI (左侧滑入 + 圆角 + 呼吸灯) =================
class ModernSlideAlert(tk.Toplevel):
    def __init__(self, parent, total_count):
        super().__init__(parent)
        self.overrideredirect(True)  # 无边框
        self.attributes('-topmost', True)  # 置顶
        
        # --- 窗口配置 ---
        self.w, self.h = 480, 220 # 更大的尺寸
        self.screen_h = self.winfo_screenheight()
        self.x_pos = -self.w  # 初始位置：屏幕左侧外
        self.target_x = 20    # 目标位置：左边缘稍往里
        self.y_pos = (self.screen_h - self.h) // 2 # 垂直居中
        self.geometry(f"{self.w}x{self.h}+{self.x_pos}+{self.y_pos}")

        # --- 透明背景 Hack (Windows圆角关键) ---
        self.transparent_color = "#000001" 
        self.attributes('-transparentcolor', self.transparent_color)
        self.configure(bg=self.transparent_color)

        # --- 画布与绘制 ---
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=self.transparent_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        # 颜色配置
        self.bg_color = "#1E1E1E"    # 磨砂黑
        self.text_color = "#FFFFFF"
        self.accent_color = "#FF4500" # 橙红
        
        # 绘制背景 (保存ID以便后续呼吸灯变色)
        self.rect_id = self.round_rectangle(5, 5, self.w-5, self.h-5, radius=25, fill=self.bg_color, outline="#FF0000", width=4)

        # --- 绘制内容 ---
        # 1. 标题
        self.canvas.create_text(40, 50, text="⚠️ 异常拦截警报", anchor="w", font=("Microsoft YaHei UI", 20, "bold"), fill=self.accent_color)
        # 2. 时间
        self.canvas.create_text(self.w-40, 50, text=datetime.now().strftime("%H:%M:%S"), anchor="e", font=("Consolas", 14, "bold"), fill="#888")
        # 3. 数据标签
        self.canvas.create_text(40, 100, text="今日拦截总量", anchor="w", font=("Microsoft YaHei UI", 12), fill="#AAA")
        # 4. 数据数值 (超大)
        self.canvas.create_text(40, 145, text=str(total_count), anchor="w", font=("Impact", 48), fill="#FFF")
        # 5. 操作提示
        self.canvas.create_text(self.w-30, 180, text="[ 按空格键关闭 ]", anchor="e", font=("Microsoft YaHei UI", 10), fill="#666")

        # --- 交互绑定 ---
        self.bind("<Return>", self.slide_out)
        self.bind("<space>", self.slide_out)
        self.bind("<Button-1>", self.slide_out)
        self.focus_force() # 抢占焦点

        # --- 启动动画 ---
        self.state = "in"
        self.slide_in_anim()
        self.pulse_border_anim(0)

    def round_rectangle(self, x1, y1, x2, y2, radius=25, **kwargs):
        """绘制圆角多边形"""
        points = [x1+radius, y1, x1+radius, y1, x2-radius, y1, x2-radius, y1, x2, y1, x2, y1+radius, x2, y1+radius,
                  x2, y2-radius, x2, y2-radius, x2, y2, x2-radius, y2, x2-radius, y2, x1+radius, y2, x1+radius, y2,
                  x1, y2, x1, y2-radius, x1, y2-radius, x1, y1+radius, x1, y1+radius, x1, y1]
        return self.canvas.create_polygon(points, **kwargs, smooth=True)

    def slide_in_anim(self):
        """平滑滑入动画"""
        if self.x_pos < self.target_x:
            step = (self.target_x - self.x_pos) * 0.25 + 2 # 缓动公式
            self.x_pos += step
            self.geometry(f"{self.w}x{self.h}+{int(self.x_pos)}+{self.y_pos}")
            self.after(16, self.slide_in_anim) # ~60fps
        else:
            self.geometry(f"{self.w}x{self.h}+{self.target_x}+{self.y_pos}")

    def slide_out(self, event=None):
        """平滑滑出动画并销毁"""
        if self.state == "out": return
        self.state = "out"
        self._slide_out_step()

    def _slide_out_step(self):
        if self.x_pos > -self.w:
            step = (self.x_pos - (-self.w)) * 0.2 + 5
            self.x_pos -= step
            self.geometry(f"{self.w}x{self.h}+{int(self.x_pos)}+{self.y_pos}")
            self.after(16, self._slide_out_step)
        else:
            self.destroy()

    def pulse_border_anim(self, step):
        """呼吸灯效果：在红、橙之间循环切换边框颜色"""
        if self.state == "out": return
        # 定义呼吸颜色表
        colors = ["#FF0000", "#FF1100", "#FF2200", "#FF3300", "#FF4500", "#FF3300", "#FF2200", "#FF1100"]
        self.canvas.itemconfig(self.rect_id, outline=colors[step % len(colors)])
        self.after(100, lambda: self.pulse_border_anim(step + 1))

def on_alarm_event(event):
    ModernSlideAlert(gui_root, STATE["total_today"])

def start_fastapi(port):
    logger.info(f"Web服务正在启动: http://localhost:{port}")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

# ================= 7. 程序入口 =================
if __name__ == "__main__":
    multiprocessing.freeze_support() # Windows打包必备
    sys.stdout.reconfigure(encoding='utf-8')
    
    print(">>> 监控系统启动中... (Ctrl+C 退出)")
    active_port = find_free_port(Config.DEFAULT_PORT)
    
    # 启动后端线程
    t = threading.Thread(target=start_fastapi, args=(active_port,), daemon=True)
    t.start()

    # 初始化 Tkinter (隐形主窗口)
    gui_root = tk.Tk()
    gui_root.withdraw()
    gui_root.bind("<<Alarm>>", on_alarm_event)
    
    # 自动打开浏览器
    def open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{active_port}")
    threading.Thread(target=open_browser, daemon=True).start()
    
    try:
        gui_root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        save_state()
        print(">>> 数据已保存，程序退出。")
