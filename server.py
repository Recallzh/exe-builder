# ================= 桌面端 GUI (Tkinter) - 极客滑入版 =================
class ModernSlideAlert(tk.Toplevel):
    def __init__(self, parent, total_count):
        super().__init__(parent)
        self.overrideredirect(True)  # 无边框
        self.attributes('-topmost', True)  # 始终置顶
        
        # 1. 尺寸与初始位置
        self.w, self.h = 480, 220  # 加大尺寸
        self.screen_h = self.winfo_screenheight()
        
        # 初始位置在屏幕左侧外面 (隐藏)
        self.x_pos = -self.w 
        # 目标位置：屏幕左侧边缘往右一点点
        self.target_x = 20 
        # 垂直居中
        self.y_pos = (self.screen_h - self.h) // 2 
        
        self.geometry(f"{self.w}x{self.h}+{self.x_pos}+{self.y_pos}")

        # 2. 设置透明背景色 (Windows下实现圆角边框的关键)
        # 我们定义一种平时不用的颜色作为透明色，比如 #000001
        self.transparent_color = "#000001"
        self.attributes('-transparentcolor', self.transparent_color)
        self.configure(bg=self.transparent_color)

        # 3. 绘图画布 (实现圆角和质感)
        self.canvas = tk.Canvas(self, width=self.w, height=self.h, 
                                bg=self.transparent_color, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # 4. 颜色定义
        self.bg_color = "#1E1E1E"    # 深灰质感背景
        self.border_color = "#FF3333" # 初始警报红
        self.text_color = "#FFFFFF"
        self.accent_color = "#FF4500" # 橙红色高亮
        
        # 5. 绘制圆角矩形背景
        self.radius = 25
        self.rect_id = self.round_rectangle(5, 5, self.w-5, self.h-5, 
                                            radius=self.radius, fill=self.bg_color, 
                                            outline=self.border_color, width=3)

        # 6. 绘制内容
        # 标题
        self.canvas.create_text(40, 50, text="⚠️ 异常拦截警报", anchor="w",
                                font=("Microsoft YaHei UI", 20, "bold"), fill=self.accent_color)
        
        # 当前时间
        time_str = datetime.now().strftime("%H:%M:%S")
        self.canvas.create_text(self.w-40, 50, text=time_str, anchor="e",
                                font=("Consolas", 14), fill="#888")

        # 主要数据
        self.canvas.create_text(40, 100, text=f"今日拦截总量", anchor="w",
                                font=("Microsoft YaHei UI", 12), fill="#AAA")
        self.canvas.create_text(40, 140, text=str(total_count), anchor="w",
                                font=("Impact", 42), fill="#FFF") # 特大数字

        # 底部提示
        self.canvas.create_text(self.w-30, 180, text="[ 按空格键关闭 ]", anchor="e",
                                font=("Microsoft YaHei UI", 10), fill="#666")

        # 7. 绑定交互
        self.bind("<Return>", self.slide_out)
        self.bind("<space>", self.slide_out)
        self.bind("<Button-1>", self.slide_out) # 点击也能关
        self.focus_force()

        # 8. 启动动画
        self.state = "in" # in 或 out
        self.slide_in_anim()
        self.pulse_border_anim(0)

    def round_rectangle(self, x1, y1, x2, y2, radius=25, **kwargs):
        """在Canvas上绘制圆角矩形"""
        points = [x1+radius, y1,
                  x1+radius, y1,
                  x2-radius, y1,
                  x2-radius, y1,
                  x2, y1,
                  x2, y1+radius,
                  x2, y1+radius,
                  x2, y2-radius,
                  x2, y2-radius,
                  x2, y2,
                  x2-radius, y2,
                  x2-radius, y2,
                  x1+radius, y2,
                  x1+radius, y2,
                  x1, y2,
                  x1, y2-radius,
                  x1, y2-radius,
                  x1, y1+radius,
                  x1, y1+radius,
                  x1, y1]
        return self.canvas.create_polygon(points, **kwargs, smooth=True)

    def slide_in_anim(self):
        """从左侧滑入动画"""
        if self.x_pos < self.target_x:
            # 类似缓动效果，每次移动剩余距离的 20% + 2px
            step = (self.target_x - self.x_pos) * 0.2 + 2
            self.x_pos += step
            self.geometry(f"{self.w}x{self.h}+{int(self.x_pos)}+{self.y_pos}")
            self.after(10, self.slide_in_anim)
        else:
            # 修正最后位置
            self.geometry(f"{self.w}x{self.h}+{self.target_x}+{self.y_pos}")

    def slide_out(self, event=None):
        """向左滑出销毁"""
        if self.state == "out": return
        self.state = "out"
        self._slide_out_step()

    def _slide_out_step(self):
        if self.x_pos > -self.w:
            step = (self.x_pos - (-self.w)) * 0.15 + 5
            self.x_pos -= step
            self.geometry(f"{self.w}x{self.h}+{int(self.x_pos)}+{self.y_pos}")
            self.after(10, self._slide_out_step)
        else:
            self.destroy()

    def pulse_border_anim(self, step):
        """边框呼吸灯效果 (视觉警报)"""
        if self.state == "out": return
        
        # 在红色和暗红色之间循环
        colors = ["#FF0000", "#FF2200", "#FF4400", "#FF6600", "#FF4400", "#FF2200"]
        current_color = colors[step % len(colors)]
        
        self.canvas.itemconfig(self.rect_id, outline=current_color)
        
        self.after(150, lambda: self.pulse_border_anim(step + 1))

# 修改事件触发函数
def on_alarm_event(event):
    count = STATE["total_today"]
    # 每次触发时，如果是第一次则创建，如果已经有窗口了，可以考虑先销毁旧的再创建新的
    # 这里为了简单直接新建
    ModernSlideAlert(gui_root, count)
