import http.server
import socketserver
import threading
import tkinter as tk
from tkinter import messagebox
import winsound
import urllib.parse
import sys
import logging
import time
import ctypes

# ================= 配置区域 =================
PORT = 16888
LOG_FILE = "server.log"
APP_TITLE = "工单监控系统"

# 颜色配置 (暗黑风)
COLOR_BG = "#1E1E1E"       # 深灰背景
COLOR_FG = "#FFFFFF"       # 白色文字
COLOR_ACCENT = "#FF4500"   # 橙红警示色
COLOR_HOVER = "#FF6347"    # 悬停高亮色
COLOR_GRAY = "#AAAAAA"     # 次要文字颜色

# ================= 日志系统初始化 =================
# 配置日志格式：[时间] [级别] 消息
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-d %H:%M:%S',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger()

# ================= 现代化 UI 类 =================
class ModernAlert(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.overrideredirect(True) # 去除系统自带边框
        self.attributes('-topmost', True) # 永远置顶
        self.configure(bg=COLOR_BG)
        
        # 窗口大小与居中
        w, h = 420, 240
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = (screen_w - w) // 2
        y = (screen_h - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        
        # 初始透明度为0 (用于淡入动画)
        self.attributes('-alpha', 0.0)
        
        # 构建界面
        self.setup_ui()
        
        # 播放声音
        self.play_sound()
        
        # 开始淡入动画
        self.fade_in()

    def setup_ui(self):
        # 1. 顶部装饰条 (兼拖动区域)
        self.title_bar = tk.Frame(self, bg=COLOR_ACCENT, height=10, cursor="fleur")
        self.title_bar.pack(fill='x', side='top')
        # 绑定拖动事件
        self.title_bar.bind("<Button-1>", self.start_move)
        self.title_bar.bind("<B1-Motion>", self.do_move)

        # 2. 内容容器
        content_frame = tk.Frame(self, bg=COLOR_BG, padx=30, pady=20)
        content_frame.pack(fill='both', expand=True)

        # 3. 标题
        lbl_title = tk.Label(content_frame, text="🚨 发现紧急工单", 
                             font=("Microsoft YaHei UI", 18, "bold"),
                             bg=COLOR_BG, fg=COLOR_FG)
        lbl_title.pack(pady=(10, 5))

        # 4. 说明文字
        lbl_desc = tk.Label(content_frame, text="系统监测到新的待处理工单\n请立即前往系统处理！", 
                            font=("Microsoft YaHei UI", 11),
                            bg=COLOR_BG, fg=COLOR_GRAY, justify="center")
        lbl_desc.pack(pady=10)

        # 5. 现代化按钮 (Flat Design)
        self.btn = tk.Button(content_frame, text="立即处理", 
                             command=self.close_animation,
                             font=("Microsoft YaHei UI", 12, "bold"),
                             bg=COLOR_ACCENT, fg=COLOR_FG,
                             relief="flat", borderwidth=0,
                             padx=30, pady=8, cursor="hand2")
        self.btn.pack(pady=20)
        
        # 按钮悬停动效
        self.btn.bind("<Enter>", lambda e: self.btn.configure(bg=COLOR_HOVER))
        self.btn.bind("<Leave>", lambda e: self.btn.configure(bg=COLOR_ACCENT))

    def play_sound(self):
        try:
            winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
        except:
            pass

    # --- 动效逻辑 ---
    def fade_in(self):
        alpha = self.attributes("-alpha")
        if alpha < 1.0:
            alpha += 0.05
            self.attributes("-alpha", alpha)
            self.after(20, self.fade_in)

    def close_animation(self):
        # 点击关闭时的淡出效果
        alpha = self.attributes("-alpha")
        if alpha > 0:
            alpha -= 0.1
            self.attributes("-alpha", alpha)
            self.after(20, self.close_animation)
        else:
            self.destroy()

    # --- 拖拽逻辑 ---
    def start_move(self, event):
        self.x = event.x
        self.y = event.y

    def do_move(self, event):
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.winfo_x() + deltax
        y = self.winfo_y() + deltay
        self.geometry(f"+{x}+{y}")

# ================= 网络服务逻辑 =================
class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        # 解析 URL
        parsed_path = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_path.query)
        
        # 快速返回 200
        self.send_response(200)
        self.end_headers()
        
        # 处理指令
        if 'mode' in query:
            mode = query['mode'][0]
            client_ip = self.client_address[0]
            
            if mode == 'test':
                logger.info(f"收到心跳检测 - 来自: {client_ip}")
            elif mode == 'alarm':
                logger.warning(f"收到报警指令! - 来自: {client_ip}")
                # 线程安全地触发 UI
                root.event_generate("<<Alarm>>")

def start_server():
    try:
        # 允许地址重用，防止重启时端口被占
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
            logger.info(f"服务启动成功 | 端口: {PORT} | 等待指令...")
            httpd.serve_forever()
    except OSError as e:
        logger.error(f"端口启动失败: {e}")
        messagebox.showerror("启动错误", f"端口 {PORT} 被占用！\n请检查是否有其他程序在运行。")
        sys.exit()

def on_alarm(event):
    ModernAlert(root)

# ================= 主程序入口 =================
if __name__ == "__main__":
    # 高分屏适配 (防止文字模糊)
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except:
        pass

    logger.info("正在初始化应用程序...")
    
    root = tk.Tk()
    root.withdraw() # 隐藏主窗口 (只在后台运行)
    
    # 绑定事件
    root.bind("<<Alarm>>", on_alarm)
    
    # 启动服务器线程
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    
    root.mainloop()
