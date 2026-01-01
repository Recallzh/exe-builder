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
import colorsys
import urllib.request
import shutil
import subprocess
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from logging.handlers import TimedRotatingFileHandler
from collections import deque


# ================= 1. 配置与全局状态 =================
class Config:
    # 🔴【重要】请修改此处为您 PHP 后台 (admin.php) 中显示的 API 地址
    # 例如: "http://www.yourdomain.com/update/api.php"
    UPDATE_CHECK_URL = "http://api.moomt.top/update/api.php"

    CURRENT_VERSION = "1.0.1"  # 本地当前版本号
    DEFAULT_PORT = 16888
    MAX_PORT_RETRIES = 10
    LOG_FILE = "monitor.log"
    DATA_FILE = "monitor_data.json"
    LOG_BACKUP_DAYS = 10


# ================= 2. 日志系统 (内存+文件+控制台) =================
# 用于存储最近 100 行日志，供网页前端读取
memory_logs = deque(maxlen=100)


class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            memory_logs.append(msg)
        except Exception:
            self.handleError(record)


# 防止 PyInstaller 无控制台模式报错
if sys.stdout is None: sys.stdout = open(os.devnull, 'w')
if sys.stderr is None: sys.stderr = open(os.devnull, 'w')

# 1. 文件日志：每天切割，保留10天
file_handler = TimedRotatingFileHandler(
    filename=Config.LOG_FILE, when="midnight", interval=1,
    backupCount=Config.LOG_BACKUP_DAYS, encoding='utf-8'
)
file_handler.suffix = "%Y-%m-%d.log"
file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))

# 2. 内存日志：给网页控制台看
mem_handler = MemoryLogHandler()
mem_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))

# 3. 标准输出：调试用
stream_handler = logging.StreamHandler(sys.stdout)

logging.basicConfig(level=logging.INFO, handlers=[file_handler, mem_handler, stream_handler])
logger = logging.getLogger("WorkOrderMonitor")


# ================= 3. 数据持久化 =================
def load_state():
    default_state = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_count": 0, "source_counts": {}, "hourly_counts": [0] * 24
    }
    if not os.path.exists(Config.DATA_FILE): return default_state
    try:
        with open(Config.DATA_FILE, 'r', encoding='utf-8') as f:
            saved = json.load(f)
            if saved.get("date") != datetime.now().strftime("%Y-%m-%d"): return default_state
            # 兼容旧数据
            if "pending_count" in saved: saved["total_count"] = saved.pop("pending_count")
            if "source_counts" not in saved: saved["source_counts"] = {}
            return saved
    except:
        return default_state


def save_state():
    current_data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "total_count": STATE["total_count"],
        "source_counts": STATE["source_counts"],
        "hourly_counts": STATE["hourly_counts"]
    }
    try:
        with open(Config.DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(current_data, f, ensure_ascii=False)
    except:
        pass


STATE = load_state()
if "start_time" not in STATE: STATE["start_time"] = time.time()


# ================= 4. 核心工具 (重启与更新) =================
def find_free_port(start_port):
    for port in range(start_port, start_port + Config.MAX_PORT_RETRIES):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('localhost', port)) != 0: return port
    return start_port


def get_current_hour(): return datetime.now().hour


def restart_program():
    """重启自身"""
    logger.info("系统正在重启...")
    save_state()
    try:
        if getattr(sys, 'frozen', False):
            # EXE 模式
            subprocess.Popen([sys.executable] + sys.argv[1:])
        else:
            # 脚本模式
            python = sys.executable
            os.execl(python, python, *sys.argv)
    except Exception as e:
        logger.error(f"重启失败: {e}")
    os._exit(0)


def perform_update_logic(download_url):
    """下载更新并执行替换"""
    try:
        logger.info(f"开始下载更新: {download_url}")
        new_filename = "update_pkg.tmp"

        # 下载文件
        req = urllib.request.Request(download_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response, open(new_filename, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)

        current_file = os.path.abspath(sys.argv[0])

        # 判断运行环境
        if getattr(sys, 'frozen', False):
            # === EXE 模式更新 ===
            logger.info("检测到 EXE 环境，生成更新脚本...")
            # 创建一个 BAT 脚本：等待 -> 删除旧exe -> 重命名新exe -> 启动新exe -> 删除bat
            bat_script = f"""
@echo off
timeout /t 2 /nobreak > NUL
del "{current_file}"
move "{new_filename}" "{current_file}"
start "" "{current_file}"
del "%~f0"
            """
            bat_path = "update_installer.bat"
            with open(bat_path, "w") as f:
                f.write(bat_script)

            logger.info("启动更新脚本，主程序即将退出...")
            os.startfile(bat_path)
            os._exit(0)
        else:
            # === 脚本模式更新 (开发调试用) ===
            logger.info("检测到脚本环境，直接替换...")
            if os.path.exists(current_file + ".bak"): os.remove(current_file + ".bak")
            os.rename(current_file, current_file + ".bak")
            shutil.move(new_filename, current_file)
            logger.info("脚本替换完成，重启中...")
            restart_program()

    except Exception as e:
        logger.error(f"更新失败: {e}")
        return False
    return True


# ================= 5. FastAPI 后端 =================
app = FastAPI(docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 前端 HTML 模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN" data-bs-theme="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>工单监控中心 Pro</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: linear-gradient(135deg, #1a1a2e, #16213e, #0f3460); font-family: 'Segoe UI', sans-serif; min-height: 100vh; color: #fff; overflow-x: hidden; }
        .glass-panel { background: rgba(255, 255, 255, 0.05); backdrop-filter: blur(10px); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 20px; box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.37); transition: transform 0.2s; }
        .glass-panel:hover { transform: translateY(-2px); }
        .text-neon { color: #00f2ff; text-shadow: 0 0 10px rgba(0, 242, 255, 0.5); }
        .btn-glass { background: rgba(255,255,255,0.1); border: 1px solid rgba(255,255,255,0.2); color: white; }
        .btn-glass:hover { background: rgba(255,255,255,0.2); }

        #console-drawer {
            position: fixed; bottom: 0; left: 0; width: 100%; height: 300px;
            background: rgba(10, 10, 15, 0.95); border-top: 1px solid #333;
            transform: translateY(100%); transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            z-index: 9999; display: flex; flex-direction: column;
        }
        #console-drawer.open { transform: translateY(0); }
        #console-output {
            flex: 1; overflow-y: auto; padding: 15px;
            font-family: 'Consolas', monospace; font-size: 13px; color: #0f0;
            white-space: pre-wrap;
        }
        .console-header { padding: 8px 15px; background: #222; border-bottom: 1px solid #444; display: flex; justify-content: space-between; align-items: center; }

        #update-modal {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.8); z-index: 10000;
            display: none; justify-content: center; align-items: center;
        }
    </style>
</head>
<body class="p-4">
    <div class="container" style="max-width: 900px;">
        <div class="d-flex justify-content-between align-items-center mb-4 glass-panel">
            <div class="d-flex align-items-center">
                <div class="spinner-grow text-warning me-3" role="status" style="width: 1rem; height: 1rem;"></div>
                <div>
                    <h3 class="m-0 fw-bold">工单监控 <span style="font-weight:300; font-size: 0.8em; opacity: 0.7;">V<span id="app-version">1.0.0</span></span></h3>
                </div>
            </div>
            <div class="d-flex align-items-center gap-2">
                <button onclick="checkUpdate(true)" class="btn btn-sm btn-glass">⬆️ 检查更新</button>
                <button onclick="restartApp()" class="btn btn-sm btn-warning fw-bold text-dark">🔄 重启</button>
                <button onclick="toggleConsole()" class="btn btn-sm btn-dark border-secondary">📟 控制台</button>
                <button onclick="shutdownApp()" class="btn btn-sm btn-danger">🔴 关闭</button>
            </div>
        </div>

        <div class="row g-4 mb-4">
            <div class="col-md-5">
                <div class="glass-panel text-center h-100">
                    <h6 class="text-muted text-uppercase mb-3">今日总工单量</h6>
                    <h1 class="display-3 fw-bold text-neon" id="total-count">0</h1>
                    <div class="text-muted small mt-2">运行时间: <span id="uptime">--:--</span></div>
                </div>
            </div>
            <div class="col-md-7">
                <div class="glass-panel h-100">
                    <h6 class="text-muted text-uppercase mb-3 border-bottom border-secondary pb-2">来源统计</h6>
                    <div id="source-list" style="max-height: 130px; overflow-y: auto;">
                        <div class="text-center text-muted mt-4">等待数据...</div>
                    </div>
                </div>
            </div>
        </div>
        <div class="glass-panel"><canvas id="dailyChart" height="80"></canvas></div>
    </div>

    <div id="console-drawer">
        <div class="console-header">
            <span class="text-white fw-bold">🖥️ 系统日志 (实时)</span>
            <button onclick="toggleConsole()" class="btn btn-sm btn-secondary">🔽 隐藏</button>
        </div>
        <div id="console-output">正在连接日志流...</div>
    </div>

    <div id="update-modal">
        <div class="glass-panel text-center" style="width: 400px; background: #1a1a2e;">
            <h4 class="mb-3">🚀 发现新版本</h4>
            <div id="update-info" class="text-start bg-dark p-2 rounded mb-3 text-secondary" style="font-size:13px; max-height:100px; overflow-y:auto;"></div>
            <div class="d-grid gap-2">
                <button id="btn-do-update" onclick="performUpdate()" class="btn btn-success">立即更新</button>
                <button id="btn-cancel-update" onclick="closeUpdate()" class="btn btn-secondary">稍后</button>
            </div>
            <div id="update-progress" class="mt-3 text-warning" style="display:none;">正在下载并安装...程序即将重启</div>
        </div>
    </div>

    <script>
        const ctx = document.getElementById('dailyChart').getContext('2d');
        const chart = new Chart(ctx, { type: 'bar', data: { labels: Array.from({length: 24}, (_, i) => i + ":00"), datasets: [{ label: '工单', data: Array(24).fill(0), backgroundColor: '#00f2ff', borderRadius: 4 }] }, options: { plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, grid: { color: 'rgba(255,255,255,0.05)' } }, x: { grid: { display: false } } } } });

        function updateData() { 
            fetch('/api/status').then(r => r.json()).then(data => { 
                document.getElementById('app-version').innerText = data.version;
                document.getElementById('total-count').innerText = data.total_count; 
                document.getElementById('uptime').innerText = new Date(data.uptime * 1000).toISOString().substr(11, 8);
                const listDiv = document.getElementById('source-list');
                const sources = data.source_counts;
                if(Object.keys(sources).length > 0) {
                    let html = '';
                    for (const [name, count] of Object.entries(sources)) html += `<div class="d-flex justify-content-between mb-2 p-2 rounded bg-dark bg-opacity-50"><span>📡 ${name}</span><span class="badge bg-info">${count}</span></div>`;
                    listDiv.innerHTML = html;
                } else { listDiv.innerHTML = '<div class="text-center text-muted mt-4">暂无数据接入...</div>'; }
                chart.data.datasets[0].data = data.hourly_counts; 
                chart.update(); 
            }).catch(()=>{}); 
        }

        let consoleTimer = null;
        function toggleConsole() {
            const drawer = document.getElementById('console-drawer');
            drawer.classList.toggle('open');
            if(drawer.classList.contains('open')) {
                fetchLogs(); consoleTimer = setInterval(fetchLogs, 1000);
            } else { clearInterval(consoleTimer); }
        }
        function fetchLogs() {
            fetch('/api/logs').then(r => r.json()).then(data => {
                const out = document.getElementById('console-output');
                out.innerText = data.logs.join('\\n');
                out.scrollTop = out.scrollHeight;
            });
        }

        function shutdownApp() { if(confirm('确定关闭服务？')) fetch('/api/shutdown'); }
        function restartApp() { if(confirm('确定重启服务？')) fetch('/api/restart').then(() => setTimeout(()=>location.reload(), 3000)); }

        let updateUrl = '';
        function checkUpdate(isManual = false) {
            fetch('/api/check_update').then(r => r.json()).then(data => {
                if(data.has_update) {
                    updateUrl = data.url;
                    document.getElementById('update-info').innerHTML = `<strong>v${data.new_version}:</strong><br>${data.desc.replace(/\\n/g, '<br>')}`;
                    document.getElementById('update-modal').style.display = 'flex';
                    if(data.force) document.getElementById('btn-cancel-update').style.display = 'none';
                } else if(isManual) { alert('当前已是最新版本'); }
            });
        }
        function closeUpdate() { document.getElementById('update-modal').style.display = 'none'; }
        function performUpdate() {
            document.getElementById('btn-do-update').disabled = true;
            document.getElementById('update-progress').style.display = 'block';
            fetch('/api/perform_update?url=' + encodeURIComponent(updateUrl)).then(r => r.json()).then(res => {
                if(res.status === 'error') alert('更新失败');
            });
        }
        setInterval(updateData, 2000); updateData();
        setTimeout(() => checkUpdate(false), 3000);
    </script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
async def read_root(): return HTML_TEMPLATE


@app.get("/api/status")
async def get_status():
    return {
        "version": Config.CURRENT_VERSION,
        "uptime": time.time() - STATE["start_time"],
        "total_count": STATE["total_count"],
        "source_counts": STATE["source_counts"],
        "hourly_counts": STATE["hourly_counts"]
    }


@app.get("/api/logs")
async def get_logs():
    return {"logs": list(memory_logs)}


@app.get("/api/restart")
async def api_restart():
    threading.Thread(target=restart_program).start()
    return {"status": "restarting"}


@app.get("/api/trigger_alarm")
async def trigger_alarm_api(count: int = 1, source: str = "默认脚本"):
    STATE["total_count"] += 1
    STATE["hourly_counts"][get_current_hour()] += 1
    if source not in STATE["source_counts"]: STATE["source_counts"][source] = 0
    STATE["source_counts"][source] += 1

    # 记录本次触发信息供弹窗使用
    STATE["last_trigger_count"] = count
    STATE["last_trigger_source"] = source
    save_state()

    logger.info(f"触发报警 [来源:{source}] [数量:{count}]")
    if gui_root: gui_root.event_generate("<<Alarm>>")
    return {"status": "triggered"}


@app.get("/api/check_update")
async def check_update_api():
    try:
        req = urllib.request.Request(Config.UPDATE_CHECK_URL, headers={'User-Agent': 'MonitorApp'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode())

        # 简单版本比较 (字符比较: 1.0.2 > 1.0.1)
        if data.get("version", "0.0.0") > Config.CURRENT_VERSION:
            logger.info(f"检测到新版本: {data['version']}")
            return {
                "has_update": True,
                "new_version": data["version"],
                "url": data["url"],
                "force": data.get("force", False),
                "desc": data.get("desc", "常规更新")
            }
    except Exception as e:
        logger.warning(f"检查更新失败: {e}")
    return {"has_update": False}


@app.get("/api/perform_update")
async def perform_update_api(url: str):
    def update_task():
        success = perform_update_logic(url)
        if not success: logger.error("更新任务执行失败")

    threading.Thread(target=update_task).start()
    return {"status": "updating"}


@app.get("/api/shutdown")
async def shutdown_api():
    if gui_root: gui_root.event_generate("<<Quit>>")
    return {"status": "closing"}


# ================= 6. GUI 弹窗 =================
class WorkOrderAlert(tk.Toplevel):
    def __init__(self, parent, count, source_name):
        super().__init__(parent)
        self.overrideredirect(True)
        self.attributes('-topmost', True)
        self.w, self.h = 500, 240
        self.screen_h = self.winfo_screenheight()
        self.x_pos, self.target_x, self.y_pos = -self.w, 25, (self.screen_h - self.h) // 2
        self.geometry(f"{self.w}x{self.h}+{self.x_pos}+{self.y_pos}")

        self.transparent_color = "#000001"
        self.attributes('-transparentcolor', self.transparent_color)
        self.configure(bg=self.transparent_color)

        self.canvas = tk.Canvas(self, width=self.w, height=self.h, bg=self.transparent_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # 绘制背景
        self.rect_id = self.round_rectangle(8, 8, self.w - 8, self.h - 8, radius=20, fill="#121212", outline="#FF0000",
                                            width=6)

        # 文本
        self.canvas.create_text(45, 50, text=f"🔔 {source_name}", anchor="w", font=("Microsoft YaHei UI", 22, "bold"),
                                fill="#FFFFFF")
        self.canvas.create_text(self.w - 45, 52, text=datetime.now().strftime("%H:%M:%S"), anchor="e",
                                font=("Consolas", 14), fill="#888")
        self.canvas.create_line(45, 80, self.w - 45, 80, fill="#333", width=2)
        self.canvas.create_text(45, 120, text="本次待办数量", anchor="w", font=("Microsoft YaHei UI", 12), fill="#AAA")
        self.canvas.create_text(45, 165, text=str(count), anchor="w", font=("Impact", 52), fill="#FFD700")
        self.canvas.create_text(self.w - 35, 200, text="[ 按空格键确认 ]", anchor="e", font=("Microsoft YaHei UI", 10),
                                fill="#555")

        self.bind("<Return>", self.slide_out);
        self.bind("<space>", self.slide_out);
        self.bind("<Button-1>", self.slide_out)
        self.focus_force();
        self.state = "in";
        self.hue = 0.0;
        self.slide_in_anim();
        self.rainbow_border_anim()

    def round_rectangle(self, x1, y1, x2, y2, radius=25, **kwargs):
        points = [x1 + radius, y1, x1 + radius, y1, x2 - radius, y1, x2 - radius, y1, x2, y1, x2, y1 + radius, x2,
                  y1 + radius, x2, y2 - radius, x2, y2 - radius, x2, y2, x2 - radius, y2, x2 - radius, y2, x1 + radius,
                  y2, x1 + radius, y2, x1, y2, x1, y2 - radius, x1, y2 - radius, x1, y1 + radius, x1, y1 + radius, x1,
                  y1]
        return self.canvas.create_polygon(points, **kwargs, smooth=True)

    def slide_in_anim(self):
        if self.x_pos < self.target_x:
            self.x_pos += (self.target_x - self.x_pos) * 0.2 + 3
            self.geometry(f"{self.w}x{self.h}+{int(self.x_pos)}+{self.y_pos}")
            self.after(16, self.slide_in_anim)
        else:
            self.geometry(f"{self.w}x{self.h}+{self.target_x}+{self.y_pos}")

    def slide_out(self, event=None):
        if self.state == "out": return
        self.state = "out";
        self._slide_out_step()

    def _slide_out_step(self):
        if self.x_pos > -self.w:
            self.x_pos -= (self.x_pos - (-self.w)) * 0.2 + 5
            self.geometry(f"{self.w}x{self.h}+{int(self.x_pos)}+{self.y_pos}")
            self.after(16, self._slide_out_step)
        else:
            self.destroy()

    def rainbow_border_anim(self):
        if self.state == "out": return
        rgb = colorsys.hsv_to_rgb(self.hue, 1.0, 1.0)
        self.canvas.itemconfig(self.rect_id,
                               outline='#%02x%02x%02x' % (int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)))
        self.hue = (self.hue + 0.015) % 1.0;
        self.after(20, self.rainbow_border_anim)


def on_alarm_event(event):
    count = STATE.get("last_trigger_count", 1)
    source = STATE.get("last_trigger_source", "新工单")
    WorkOrderAlert(gui_root, count, source)


# ================= 7. 主程序入口 =================
if __name__ == "__main__":
    multiprocessing.freeze_support()

    print(">>> 工单监控伴侣启动中...")
    active_port = find_free_port(Config.DEFAULT_PORT)

    # 启动后端线程
    t = threading.Thread(target=lambda: uvicorn.run(app, host="0.0.0.0", port=active_port, log_level="warning"),
                         daemon=True)
    t.start()

    # 启动 GUI (隐形Root)
    gui_root = tk.Tk()
    gui_root.withdraw()
    gui_root.bind("<<Alarm>>", on_alarm_event)
    gui_root.bind("<<Quit>>", lambda e: gui_root.destroy())

    # 启动浏览器
    threading.Thread(target=lambda: (time.sleep(1.5), webbrowser.open(f"http://localhost:{active_port}")),
                     daemon=True).start()

    try:
        gui_root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        save_state()
