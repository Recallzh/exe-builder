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
import colorsys  # 【新增】用于实现丝滑的渐变色计算
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
    DATA_FILE = "monitor_data.json"

# ================= 2. 数据持久化 =================
def load_state():
    default_state = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "pending_count": 0, # 改名：更加语义化
        "hourly_counts": [0] * 24
    }
    
    if not os.path.exists(Config.DATA_FILE):
        return default_state
    
    try:
        with open(Config.DATA_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
            if saved.get("date") != datetime.now().strftime("%Y-%m-%d"):
                return default_state
            # 兼容旧数据的字段名读取
            if "total_today" in saved:
                saved["pending_count"] = saved.pop("total_today")
            return saved
    except Exception as e:
        return default_state

def save_state():
    current_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "pending_count": STATE["pending_count"],
        "hourly_counts": STATE["hourly_counts"]
    }
    try:
        with open(Config.DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        pass

# ================= 3. 初始化系统 =================
# 注意：在 -w 模式下，sys.stdout 可能为 None，StreamHandler 可能会 fallback 到 stderr 或忽略
# 为了防止 logging 初始化报错，可以加一个简单的判断，或者保持原样（通常 StreamHandler 能处理 None）
handlers_list = [
    RotatingFileHandler(Config.LOG_FILE, maxBytes=1024*1024, backupCount=3, encoding='utf-8')
]
if sys.stdout is not None:
    handlers_list.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=handlers_list
)
logger = logging.getLogger("WorkOrderMonitor")

saved_data = load_state()
STATE = {
    "start_time": time.time(),
    "pending_count": saved_data["pending_count"],
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

# 网页后台模板 (已修改文案)
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
        body { background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460); font-family: 'Segoe UI', sans-serif; min-height: 100vh; color: #fff; }
        .glass-panel { background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 20px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37); }
        .text-neon { color: #00f2ff; text-shadow: 0 0 10px rgba(0, 242, 255, 0.5); }
    </style>
</head>
<body class="p-4">
    <div class="container" style="max-width: 900px;">
        <div class="d-flex justify-content-between align-items-center mb-4 glass-panel">
            <div class="d-flex align-items-center">
                <div class="spinner-grow text-warning me-3" role="status" style="width: 1rem; height: 1rem;"></div>
                <h3 class="m-0 fw-bold">WORK ORDER <span style="font-weight:300; font-size: 0.8em; opacity: 0.7;">MONITOR</span></h3>
            </div>
            <div><span class="badge bg-primary bg-opacity-25 border border-primary me-2" id="current-time">--:--</span><span class="badge bg-success bg-opacity-25 text-success border border-success">LISTENING</span></div>
        </div>
        <div class="row g-4 mb-4">
            <div class="col-md-6"><div class="glass-panel text-center h-100"><h6 class="text-muted text-uppercase mb-3">今日未处理工单量</h6><h1 class="display-3 fw-bold text-neon" id="pending-count">0</h1></div></div>
            <div class="col-md-6"><div class="glass-panel d-flex flex-column justify-content-center gap-3 h-100"><div class="d-flex justify-content-between px-4"><span class="text-muted">运行时间</span><span class="fw-bold" id="uptime">--:--:--</span></div><button class="btn btn-warning w-100 bg-opacity-75 mx-auto fw-bold text-dark" style="max-width:80%;" onclick="testAlarm()">⚡ 模拟工单到达</button><div class="text-center text-muted" style="font-size: 12px;">Waiting for Tampermonkey request...</div></div></div>
        </div>
        <div class="glass-panel"><h6 class="mb-3 border-bottom border-secondary pb-2">工单时段分布</h6><canvas id="dailyChart" height="100"></canvas></div>
    </div>
    <script>
        const ctx = document.getElementById('dailyChart').getContext('2d');
        const chart = new Chart(ctx, { type: 'bar', data: { labels: Array.from({length: 24}, (_, i) => i + ":00"), datasets: [{ label: '工单量', data: Array(24).fill(0), backgroundColor: 'rgba(255, 206, 86, 0.5)', borderColor: '#ffce56', borderWidth: 1, borderRadius: 4 }] }, options: { responsive: true, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' } }, x: { grid: { display: false } } } } });
        function formatTime(s) { return `${Math.floor(s/3600).toString().padStart(2,'0')}:${Math.floor((s%3600)/60).toString().padStart(2,'0')}:${Math.floor(s%60).toString().padStart(2,'0')}`; }
        function updateData() { document.getElementById('current-time').innerText = new Date().toLocaleTimeString(); fetch('/api/status').then(r => r.json()).then(data => { document.getElementById('pending-count').innerText = data.pending_count; document.getElementById('uptime').innerText = formatTime(data.uptime); chart.data.datasets[0].data = data.hourly_counts; chart.update(); }); }
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
    return { "uptime": time.time() - STATE["start_time"], "pending_count": STATE["pending_count"], "hourly_counts": STATE["hourly_counts"] }

@app.get("/api/trigger_alarm")
async def trigger_alarm_api():
    STATE["pending_count"] += 1
    STATE["hourly_counts"][get_current_hour()] += 1
    save_state()
    logger.info(f"收到工单通知 - 当前累计: {STATE['pending_count']}")
    if gui_root:
        gui_root.event_generate("<<Alarm>>")
    return {"status": "triggered"}

# ================= 6. 桌面端 GUI (流光边框 + 任务风格) =================
class WorkOrderAlert(tk.Toplevel):
    def __init__(self, parent, count):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        
        # --- 窗口尺寸 ---
        self.w, self.h = 500, 240
        self.screen_h = self.winfo_screenheight()
        self.x_pos = -self.w
        self.target_x = 25
        self.y_pos = (self.screen_h - self.h) // 2
        self.geometry(f"{self.w}x{self.h}+{self.x_pos}+{self.y_pos}")

        # --- 透明背景配置 ---
        self.transparent_color = "#000001"
        self.attributes('-transparentcolor', self.transparent_color)
        self.configure(bg=self.transparent_color)

        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=self.transparent_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        
        # --- 颜色与样式 ---
        self.bg_color = "#121212"    # 极深灰背景
        self.text_color = "#E0E0E0"
        
        # 绘制背景 (保存ID用于流光特效)
        # width=5 让边框更粗，渐变效果更明显
        self.rect_id = self.round_rectangle(8, 8, self.w-8, self.h-8, radius=20, fill=self.bg_color, outline="#FF0000", width=6)

        # --- 绘制内容 (文案已修改) ---
        # 1. 顶部状态
        self.canvas.create_text(45, 50, text="🔔 发现新工单", anchor="w", font=("Microsoft YaHei UI", 22, "bold"), fill="#FFFFFF")
        
        # 2. 时间戳
        self.canvas.create_text(self.w-45, 52, text=datetime.now().strftime("%H:%M:%S"), anchor="e", font=("Consolas", 14), fill="#888")
        
        # 3. 分割线
        self.canvas.create_line(45, 80, self.w-45, 80, fill="#333", width=2)
        
        # 4. 核心指标
        self.canvas.create_text(45, 120, text="今日未处理工单量", anchor="w", font=("Microsoft YaHei UI", 12), fill="#AAA")
        self.canvas.create_text(45, 165, text=str(count), anchor="w", font=("Impact", 52), fill="#FFD700") # 金色数字

        # 5. 操作提示 (右下角)
        self.canvas.create_text(self.w-35, 200, text="[ 按空格键确认 ]", anchor="e", font=("Microsoft YaHei UI", 10), fill="#555")

        # --- 交互 ---
        self.bind("<Return>", self.slide_out)
        self.bind("<space>", self.slide_out)
        self.bind("<Button-1>", self.slide_out)
        self.focus_force()

        # --- 启动动画 ---
        self.state = "in"
        self.hue = 0.0 # 色相初始值
        self.slide_in_anim()
        self.rainbow_border_anim() # 启动流光渐变

    def round_rectangle(self, x1, y1, x2, y2, radius=25, **kwargs):
        points = [x1+radius, y1, x1+radius, y1, x2-radius, y1, x2-radius, y1, x2, y1, x2, y1+radius, x2, y1+radius,
                  x2, y2-radius, x2, y2-radius, x2, y2, x2-radius, y2, x2-radius, y2, x1+radius, y2, x1+radius, y2,
                  x1, y2, x1, y2-radius, x1, y2-radius, x1, y1+radius, x1, y1+radius, x1, y1]
        return self.canvas.create_polygon(points, **kwargs, smooth=True)

    def slide_in_anim(self):
        if self.x_pos < self.target_x:
            step = (self.target_x - self.x_pos) * 0.2 + 3
            self.x_pos += step
            self.geometry(f"{self.w}x{self.h}+{int(self.x_pos)}+{self.y_pos}")
            self.after(16, self.slide_in_anim)
        else:
            self.geometry(f"{self.w}x{self.h}+{self.target_x}+{self.y_pos}")

    def slide_out(self, event=None):
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

    def rainbow_border_anim(self):
        """流光渐变动效：在HSV色彩空间中循环，实现丝滑变色"""
        if self.state == "out": return
        
        # 1. 计算RGB颜色 (Hue, Saturation, Value) -> (R, G, B)
        # Hue 每次增加 0.01，实现颜色流动
        rgb = colorsys.hsv_to_rgb(self.hue, 1.0, 1.0) 
        # 转换为Hex格式 #RRGGBB
        color_hex = '#%02x%02x%02x' % (int(rgb[0]*255), int(rgb[1]*255), int(rgb[2]*255))
        
        # 2. 更新边框颜色
        self.canvas.itemconfig(self.rect_id, outline=color_hex)
        
        # 3. 循环 Hue (0.0 - 1.0)
        self.hue += 0.015
        if self.hue > 1.0: self.hue = 0.0
        
        self.after(20, self.rainbow_border_anim)

def on_alarm_event(event):
    WorkOrderAlert(gui_root, STATE["pending_count"])

def start_fastapi(port):
    logger.info(f"Web服务正在启动: http://localhost:{port}")
    # 在无控制台模式下，log_level设为warning或更高级别可减少控制台输出尝试
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")

# ================= 7. 程序入口 =================
if __name__ == "__main__":
    multiprocessing.freeze_support()
    
    # 【核心修复】
    # 当使用 pyinstaller -w 打包时，sys.stdout 为 None
    # 此时调用 reconfigure 会报错，因此必须加判断
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except AttributeError:
            pass # 双重保险
    
    print(">>> 工单监控伴侣启动中...")
    active_port = find_free_port(Config.DEFAULT_PORT)
    
    t = threading.Thread(target=start_fastapi, args=(active_port,), daemon=True)
    t.start()

    gui_root = tk.Tk()
    gui_root.withdraw()
    gui_root.bind("<<Alarm>>", on_alarm_event)
    
    def open_browser():
        time.sleep(1.5)
        # 在无界面模式下，print 是无效的，但不会报错（除非显式调用 flush 等）
        print(f"Opening browser at port {active_port}")
        webbrowser.open(f"http://localhost:{active_port}")
    
    threading.Thread(target=open_browser, daemon=True).start()
    
    try:
        gui_root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        save_state()
        print(">>> 退出程序")
