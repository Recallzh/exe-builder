import http.server
import socketserver
import threading
import tkinter as tk
from tkinter import font
import urllib.parse
import winsound
import time

# 配置
PORT = 16888
WINDOW_WIDTH = 300
WINDOW_HEIGHT = 160

# 全局状态
current_count = 0
alarm_active = False

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        global current_count, alarm_active
        
        # 解析路径和参数
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        query = urllib.parse.parse_qs(parsed_path.query)

        if path == '/api/status':
            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')
            
        elif path == '/api/trigger_alarm':
            # 获取工单数量参数
            count_list = query.get('count', ['1'])
            try:
                current_count = int(count_list[0])
            except:
                current_count = 1

            self.send_response(200)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'{"status": "alarm_received"}')
            
            # 激活报警
            alarm_active = True
            update_gui_signal()
            
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # 禁用控制台日志

def start_server():
    with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
        print(f"Server started at http://localhost:{PORT}")
        httpd.serve_forever()

# --- GUI 逻辑 ---
root = None
label_info = None
label_count = None
frame_bg = None

def update_gui_signal():
    """UI 更新触发器"""
    if root:
        root.after(0, show_alarm_window)

def show_alarm_window():
    global alarm_active
    if not alarm_active:
        return

    # 更新文字
    label_count.config(text=f"{current_count}")
    
    # 播放声音 (异步)
    threading.Thread(target=lambda: winsound.Beep(1000, 500), daemon=True).start()
    
    # 显示窗口
    root.deiconify()
    root.attributes('-topmost', True)
    
    # 启动呼吸灯边框动效
    start_breathing_effect()

# 呼吸灯动效 (渐变边框)
hue = 0
breathing_job = None

def start_breathing_effect():
    global breathing_job, hue
    if breathing_job:
        root.after_cancel(breathing_job)
    
    # 颜色数组：模拟红色呼吸 (深红 <-> 亮红)
    # 你可以根据喜好修改这些 HEX 颜色
    colors = [
        "#880000", "#990000", "#aa0000", "#cc0000", "#ff0000", 
        "#ff3333", "#ff0000", "#cc0000", "#aa0000", "#990000"
    ]
    
    current_color = colors[hue % len(colors)]
    
    if frame_bg:
        frame_bg.config(bg=current_color)
    
    hue += 1
    # 100ms 切换一次颜色，形成流畅的呼吸感
    breathing_job = root.after(100, start_breathing_effect)

def stop_alarm():
    global alarm_active, breathing_job
    alarm_active = False
    if breathing_job:
        root.after_cancel(breathing_job)
        breathing_job = None
    root.withdraw() # 隐藏窗口

def create_gui():
    global root, label_info, label_count, frame_bg
    
    root = tk.Tk()
    root.title("工单监控")
    
    # 设置窗口位置 (右下角)
    screen_width = root.winfo_screenwidth()
    screen_height = root.winfo_screenheight()
    x = screen_width - WINDOW_WIDTH - 20
    y = screen_height - WINDOW_HEIGHT - 50
    root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}+{x}+{y}")
    
    # 无边框模式
    root.overrideredirect(True) 
    root.attributes('-alpha', 0.95)
    root.config(bg='#111111')

    # 【重要】外部边框容器 (用于做渐变/呼吸动效)
    frame_bg = tk.Frame(root, bg="#ff0000", padx=5, pady=5)
    frame_bg.pack(fill=tk.BOTH, expand=True)

    # 内容容器 (黑色背景，盖在渐变边框上，形成边框效果)
    content_frame = tk.Frame(frame_bg, bg="#222222")
    content_frame.pack(fill=tk.BOTH, expand=True)

    # 标题文字 (已修改：未处理工单量)
    f_title = font.Font(family="Microsoft YaHei", size=12, weight="bold")
    label_info = tk.Label(content_frame, text="未处理工单量", font=f_title, fg="#aaaaaa", bg="#222222")
    label_info.pack(pady=(15, 0))

    # 数量显示
    f_count = font.Font(family="Arial", size=40, weight="bold")
    label_count = tk.Label(content_frame, text="0", font=f_count, fg="#ff4d4f", bg="#222222")
    label_count.pack(pady=0)

    # 按钮
    btn = tk.Button(content_frame, text="我知道了 (隐藏)", command=stop_alarm, 
                    bg="#333", fg="white", bd=0, activebackground="#555", cursor="hand2")
    btn.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=10)

    # 默认隐藏
    root.withdraw()

    # 启动服务器线程
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    
    print("监控服务已启动...")
    # [已修改] 移除了 webbrowser.open，不再自动打开网页
    
    root.mainloop()

if __name__ == "__main__":
    create_gui()
