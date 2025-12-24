import http.server
import socketserver
import threading
import tkinter as tk
from tkinter import messagebox
import winsound
import urllib.parse
import sys

PORT = 16888

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed_path.query)
        self.send_response(200)
        self.end_headers()
        if 'mode' in query:
            mode = query['mode'][0]
            if mode == 'test':
                print(f"[心跳] 客户端连接正常")
            elif mode == 'alarm':
                print(f"[报警] 收到工单！")
                root.event_generate("<<Alarm>>")

def start_server():
    try:
        with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
            print(f"服务已启动，监听端口: {PORT}")
            httpd.serve_forever()
    except:
        sys.exit()

def show_alarm(event=None):
    try:
        winsound.PlaySound("SystemHand", winsound.SND_ALIAS | winsound.SND_ASYNC)
    except: pass
    
    alarm_window = tk.Toplevel(root)
    alarm_window.title("工单提醒")
    alarm_window.geometry("400x250")
    alarm_window.configure(bg="#1E1E1E")
    alarm_window.attributes('-topmost', True)
    
    tk.Label(alarm_window, text="🚨 发现紧急工单", font=("Microsoft YaHei UI", 18, "bold"), 
             bg="#1E1E1E", fg="white").pack(pady=(20, 10))
    tk.Label(alarm_window, text="请立即前往处理！", font=("Microsoft YaHei UI", 12), 
             bg="#1E1E1E", fg="#CCCCCC").pack(pady=10)
    
    tk.Button(alarm_window, text="立即处理", command=alarm_window.destroy, 
              font=("Microsoft YaHei UI", 12, "bold"), bg="#FF4500", fg="white").pack(pady=20)

if __name__ == "__main__":
    root = tk.Tk()
    root.withdraw()
    root.bind("<<Alarm>>", show_alarm)
    threading.Thread(target=start_server, daemon=True).start()
    root.mainloop()
