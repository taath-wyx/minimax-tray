"""
MiniMax Token Plan 任务栏监控工具
- 系统托盘图标 + 任务栏旁悬浮小组件
- 实时显示 5小时余量 & 周余量
"""

import os
import sys
import json
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import requests
import pystray
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path
import winreg
import webbrowser
from datetime import datetime
import ctypes
import ctypes.wintypes

# ===== 配置文件路径 =====
CONFIG_DIR = Path(os.environ.get("APPDATA", ".")) / "MiniMaxTray"
CONFIG_FILE = CONFIG_DIR / "config.json"
CONFIG_DIR.mkdir(parents=True, exist_ok=True)

# ===== API 端点 =====
API_URL = "https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains"

# ===== 默认配置 =====
DEFAULT_CONFIG = {
    "api_key": "",
    "refresh_interval": 60,
    "autostart": False,
    "widget_visible": True,
    "widget_mode": "compact",   # "compact"（精简，默认）或 "standard"（标准）
}

# ===== 颜色方案（Catppuccin Mocha 风格）=====
C = {
    "bg":        "#1E1E2E",
    "surface0":  "#313244",
    "surface1":  "#45475A",
    "surface2":  "#585B70",
    "overlay0":  "#6C7086",
    "text":      "#CDD6F4",
    "subtext0":  "#A6ADC8",
    "subtext1":  "#BAC2DE",
    "accent":    "#CBA6F7",   # Mauve
    "blue":      "#89B4FA",
    "green":     "#A6E3A1",
    "yellow":    "#F9E2AF",
    "peach":     "#FAB387",
    "red":       "#F38BA8",
    "sky":       "#89DCEB",
    "teal":      "#94E2D5",
    "rosewater": "#F5E0DC",
}

def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def pct_color(pct_remaining: float) -> str:
    """根据剩余百分比返回颜色"""
    if pct_remaining >= 50:
        return C["green"]
    elif pct_remaining >= 20:
        return C["yellow"]
    else:
        return C["red"]

def ms_to_hm(ms: int) -> str:
    """毫秒转可读时间"""
    if ms <= 0:
        return "已重置"
    s = ms // 1000
    h = s // 3600
    m = (s % 3600) // 60
    if h > 0:
        return f"{h}h {m:02d}m"
    return f"{m}m"

# ===== 配置读写 =====

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg = json.load(f)
                return {**DEFAULT_CONFIG, **cfg}
        except Exception:
            pass
    return dict(DEFAULT_CONFIG)


def save_config(cfg):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ===== 自启动管理 =====

def set_autostart(enable: bool):
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "MiniMaxTray"
    exe_path = sys.executable if getattr(sys, "frozen", False) else f'"{sys.executable}" "{os.path.abspath(__file__)}"'
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE)
        if enable:
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
        else:
            try:
                winreg.DeleteValue(key, app_name)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        print(f"自启动设置失败: {e}")
        return False


# ===== API 查询 =====

def fetch_usage(api_key: str) -> dict:
    """
    返回格式:
    {
        "ok": True,
        "models": [
            {
                "model_name": str,
                # 5h 窗口
                "interval_total": int,
                "interval_used": int,
                "interval_remaining": int,
                "interval_pct_remaining": float,
                "interval_reset_ms": int,      # 距重置毫秒
                # 周
                "weekly_total": int,
                "weekly_used": int,
                "weekly_remaining": int,
                "weekly_pct_remaining": float,
                "weekly_reset_ms": int,
            }
        ],
        "raw": dict,
        "fetched_at": str,
    }
    """
    try:
        resp = requests.get(
            API_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        if resp.status_code == 401:
            return {"ok": False, "error": "API Key 无效或已过期"}
        if resp.status_code != 200:
            return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

        data = resp.json()
        # 检查业务状态码
        base = data.get("base_resp", {})
        sc = base.get("status_code", data.get("status_code", 0))
        if sc not in (0, None, ""):
            msg = base.get("status_msg", data.get("status_msg", f"code={sc}"))
            return {"ok": False, "error": f"接口错误: {msg}"}

        model_remains = data.get("model_remains", [])
        models = []
        for item in model_remains:
            i_total   = int(item.get("current_interval_total_count") or 0)
            # usage_count 字段实际含义是「余量」而非已用量
            i_remain  = max(0, int(item.get("current_interval_usage_count") or 0))
            i_used    = max(0, i_total - i_remain)
            i_pct     = (i_remain / i_total * 100) if i_total > 0 else 0
            i_reset   = int(item.get("remains_time") or 0)

            w_total   = int(item.get("current_weekly_total_count") or 0)
            # usage_count 字段实际含义是「余量」而非已用量
            w_remain  = max(0, int(item.get("current_weekly_usage_count") or 0))
            w_used    = max(0, w_total - w_remain)
            w_pct     = (w_remain / w_total * 100) if w_total > 0 else 0
            w_reset   = int(item.get("weekly_remains_time") or 0)

            models.append({
                "model_name": item.get("model_name", "未知模型"),
                "interval_total":          i_total,
                "interval_used":           i_used,
                "interval_remaining":      i_remain,
                "interval_pct_remaining":  i_pct,
                "interval_reset_ms":       i_reset,
                "weekly_total":            w_total,
                "weekly_used":             w_used,
                "weekly_remaining":        w_remain,
                "weekly_pct_remaining":    w_pct,
                "weekly_reset_ms":         w_reset,
            })

        models.sort(key=lambda x: -x["interval_total"])

        return {
            "ok": True,
            "models": models,
            "raw": data,
            "fetched_at": datetime.now().strftime("%H:%M:%S"),
        }

    except requests.exceptions.ConnectionError:
        return {"ok": False, "error": "网络连接失败"}
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "请求超时"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ===== 聚合：所有模型汇总 =====

def aggregate(models: list) -> dict:
    """把所有模型数据汇总为一组总量"""
    if not models:
        return None
    i_total  = sum(m["interval_total"] for m in models)
    i_used   = sum(m["interval_used"] for m in models)
    i_remain = sum(m["interval_remaining"] for m in models)
    i_pct    = (i_remain / i_total * 100) if i_total > 0 else 0
    i_reset  = max((m["interval_reset_ms"] for m in models), default=0)

    w_total  = sum(m["weekly_total"] for m in models)
    w_used   = sum(m["weekly_used"] for m in models)
    w_remain = sum(m["weekly_remaining"] for m in models)
    w_pct    = (w_remain / w_total * 100) if w_total > 0 else 0
    w_reset  = max((m["weekly_reset_ms"] for m in models), default=0)

    return {
        "interval_total":         i_total,
        "interval_remaining":     i_remain,
        "interval_pct_remaining": i_pct,
        "interval_reset_ms":      i_reset,
        "weekly_total":           w_total,
        "weekly_remaining":       w_remain,
        "weekly_pct_remaining":   w_pct,
        "weekly_reset_ms":        w_reset,
    }


# ===== 托盘图标生成 =====

def create_tray_icon(state: str = "unknown", percent: float = 0.0) -> Image.Image:
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    state_colors = {
        "healthy": hex_to_rgb(C["green"]) + (255,),
        "warning": hex_to_rgb(C["yellow"]) + (255,),
        "danger":  hex_to_rgb(C["red"]) + (255,),
        "unknown": (128, 128, 128, 200),
        "loading": (160, 160, 200, 200),
    }
    fill_color = state_colors.get(state, state_colors["unknown"])
    bg_rgba = hex_to_rgb(C["bg"]) + (240,)

    draw.rounded_rectangle([2, 2, 62, 62], radius=12, fill=bg_rgba)

    if state in ("loading", "unknown"):
        label = "..." if state == "loading" else "MM"
        draw.text((16, 20), label, fill=fill_color)
    else:
        rem = percent   # percent 传入的就是余量百分比
        try:
            font_big = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 20)
            font_sm  = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 11)
        except Exception:
            font_big = font_sm = ImageFont.load_default()

        # 进度条（余量进度）
        draw.rounded_rectangle([8, 44, 56, 56], radius=4, fill=(60, 60, 80, 255))
        bar_w = int(rem / 100 * 48)
        if bar_w > 0:
            draw.rounded_rectangle([8, 44, 8 + bar_w, 56], radius=4, fill=fill_color)

        txt = f"{int(rem)}%"
        bb = draw.textbbox((0, 0), txt, font=font_big)
        tw = bb[2] - bb[0]
        draw.text(((size - tw) // 2, 14), txt, fill=fill_color, font=font_big)

        lbl = "余量"
        bb2 = draw.textbbox((0, 0), lbl, font=font_sm)
        tw2 = bb2[2] - bb2[0]
        draw.text(((size - tw2) // 2, 36), lbl, fill=(180, 180, 200, 200), font=font_sm)

    return img


# ===== 悬浮小组件 =====

class FloatWidget:
    """
    停靠在任务栏托盘区域左侧的半透明小组件
    无标题栏、无边框、始终置顶、鼠标可穿透可关闭
    """

    WIDGET_W = 260
    WIDGET_H = 110
    PADDING_RIGHT = 8    # 距屏幕右边留白（托盘区域右侧通常有留白）
    PADDING_BOTTOM = 8   # 距屏幕底部留白

    def __init__(self, app):
        self.app = app
        self.root = None
        self._visible = False
        self._drag_start = None
        # 允许用户拖拽自定义位置
        self._custom_x = None
        self._custom_y = None

    def _get_taskbar_height(self) -> int:
        """获取 Windows 任务栏高度"""
        try:
            APPBARDATA = ctypes.Structure
            class APPBARDATA_S(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.wintypes.DWORD),
                    ("hWnd", ctypes.wintypes.HWND),
                    ("uCallbackMessage", ctypes.wintypes.UINT),
                    ("uEdge", ctypes.wintypes.UINT),
                    ("rc", ctypes.wintypes.RECT),
                    ("lParam", ctypes.wintypes.LPARAM),
                ]
            abd = APPBARDATA_S()
            abd.cbSize = ctypes.sizeof(abd)
            SPI_GETWORKAREA = 0x0030
            work_rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work_rect), 0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)
            return screen_h - work_rect.bottom
        except Exception:
            return 40

    def _calc_position(self):
        """计算小组件位置：默认停在屏幕右下角（托盘左侧）"""
        if self._custom_x is not None and self._custom_y is not None:
            return self._custom_x, self._custom_y
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        tb_h = self._get_taskbar_height()
        x = sw - self.WIDGET_W - self.PADDING_RIGHT
        y = sh - tb_h - self.WIDGET_H - self.PADDING_BOTTOM
        return x, y

    def show(self):
        if self._visible and self.root and self.root.winfo_exists():
            self.root.lift()
            self.update_data()
            return
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def hide(self):
        self._visible = False
        if self.root:
            try:
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass
            self.root = None

    def toggle(self):
        if self._visible and self.root and self.root.winfo_exists():
            self.hide()
        else:
            self.show()

    def _run(self):
        self._visible = True
        self.root = tk.Tk()
        root = self.root

        root.overrideredirect(True)          # 无边框无标题栏
        root.attributes("-topmost", True)    # 始终置顶
        root.attributes("-alpha", 0.93)      # 微透明
        root.configure(bg=C["bg"])

        # 设置圆角（Windows 11 DWM API）
        try:
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWM_WINDOW_CORNER_PREFERENCE_ROUND = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.windll.user32.GetParent(root.winfo_id()),
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(ctypes.c_int(DWM_WINDOW_CORNER_PREFERENCE_ROUND)),
                ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

        root.update_idletasks()
        x, y = self._calc_position()
        root.geometry(f"{self.WIDGET_W}x{self.WIDGET_H}+{x}+{y}")

        self._build_ui(root)
        self.update_data()

        # 拖拽
        root.bind("<ButtonPress-1>",   self._on_drag_start)
        root.bind("<B1-Motion>",       self._on_drag_motion)
        root.bind("<ButtonRelease-1>", self._on_drag_end)
        # 双击关闭
        root.bind("<Double-Button-1>", lambda e: self.hide())
        # 右键菜单
        root.bind("<Button-3>", self._on_right_click)

        root.mainloop()
        self._visible = False
        self.root = None

    def _build_ui(self, root):
        """构建小组件 UI"""
        # ── 顶部标题条 ──────────────────────────────────
        title_bar = tk.Frame(root, bg=C["surface0"], height=26)
        title_bar.pack(fill="x")
        title_bar.pack_propagate(False)

        # Logo 点
        dot_frame = tk.Frame(title_bar, bg=C["surface0"])
        dot_frame.pack(side="left", padx=(8, 4), pady=6)
        for color in (C["red"], C["yellow"], C["green"]):
            tk.Frame(dot_frame, bg=color, width=8, height=8).pack(side="left", padx=2)

        tk.Label(title_bar, text="MiniMax  Token Plan",
                 font=("微软雅黑", 8, "bold"), bg=C["surface0"], fg=C["subtext0"]
                 ).pack(side="left", padx=2)

        # 刷新时间
        self._time_lbl = tk.Label(title_bar, text="",
                                  font=("Consolas", 8), bg=C["surface0"], fg=C["overlay0"])
        self._time_lbl.pack(side="right", padx=8)

        # ── 内容区 ───────────────────────────────────────
        body = tk.Frame(root, bg=C["bg"])
        body.pack(fill="both", expand=True, padx=8, pady=(6, 6))

        # 左：5h 窗口
        left = tk.Frame(body, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True)

        tk.Label(left, text="5H 窗口", font=("微软雅黑", 7),
                 bg=C["bg"], fg=C["overlay0"]).pack(anchor="w")

        self._i_pct_lbl = tk.Label(left, text="—",
                                   font=("Consolas", 22, "bold"),
                                   bg=C["bg"], fg=C["green"])
        self._i_pct_lbl.pack(anchor="w")

        self._i_remain_lbl = tk.Label(left, text="剩余 —",
                                      font=("微软雅黑", 8),
                                      bg=C["bg"], fg=C["subtext0"])
        self._i_remain_lbl.pack(anchor="w")

        # 进度条 5h
        self._i_bar_bg = tk.Frame(left, bg=C["surface1"], height=4)
        self._i_bar_bg.pack(fill="x", pady=(3, 0))
        self._i_bar_fg = tk.Frame(self._i_bar_bg, bg=C["green"], height=4)
        self._i_bar_fg.place(x=0, y=0, relwidth=0, relheight=1)

        self._i_reset_lbl = tk.Label(left, text="重置 —",
                                     font=("微软雅黑", 7),
                                     bg=C["bg"], fg=C["overlay0"])
        self._i_reset_lbl.pack(anchor="w", pady=(2, 0))

        # 分隔线
        tk.Frame(body, bg=C["surface1"], width=1).pack(side="left", fill="y", padx=8)

        # 右：周余量
        right = tk.Frame(body, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)

        tk.Label(right, text="本 周", font=("微软雅黑", 7),
                 bg=C["bg"], fg=C["overlay0"]).pack(anchor="w")

        self._w_pct_lbl = tk.Label(right, text="—",
                                   font=("Consolas", 22, "bold"),
                                   bg=C["bg"], fg=C["green"])
        self._w_pct_lbl.pack(anchor="w")

        self._w_remain_lbl = tk.Label(right, text="剩余 —",
                                      font=("微软雅黑", 8),
                                      bg=C["bg"], fg=C["subtext0"])
        self._w_remain_lbl.pack(anchor="w")

        # 进度条 周
        self._w_bar_bg = tk.Frame(right, bg=C["surface1"], height=4)
        self._w_bar_bg.pack(fill="x", pady=(3, 0))
        self._w_bar_fg = tk.Frame(self._w_bar_bg, bg=C["green"], height=4)
        self._w_bar_fg.place(x=0, y=0, relwidth=0, relheight=1)

        self._w_reset_lbl = tk.Label(right, text="重置 —",
                                     font=("微软雅黑", 7),
                                     bg=C["bg"], fg=C["overlay0"])
        self._w_reset_lbl.pack(anchor="w", pady=(2, 0))

    def update_data(self):
        """刷新小组件显示数据（可从任意线程调用）"""
        if not self._visible or not self.root:
            return
        try:
            self.root.after(0, self._do_update)
        except Exception:
            pass

    def _do_update(self):
        if not self.root or not self.root.winfo_exists():
            return

        data = self.app.usage_data
        err  = self.app.last_error

        if err or not data:
            tip = err or "等待数据…"
            self._i_pct_lbl.config(text="ERR" if err else "…", fg=C["red"] if err else C["overlay0"])
            self._w_pct_lbl.config(text="—", fg=C["overlay0"])
            self._i_remain_lbl.config(text=tip[:22])
            self._w_remain_lbl.config(text="")
            self._i_reset_lbl.config(text="")
            self._w_reset_lbl.config(text="")
            self._time_lbl.config(text="")
            return

        agg = aggregate(data.get("models", []))
        if not agg:
            return

        # 5h 窗口
        i_pct = agg["interval_pct_remaining"]
        i_clr = pct_color(i_pct)
        self._i_pct_lbl.config(text=f"{i_pct:.0f}%", fg=i_clr)
        self._i_remain_lbl.config(text=f"剩余 {agg['interval_remaining']:,} / {agg['interval_total']:,}")
        self._i_reset_lbl.config(text=f"重置 {ms_to_hm(agg['interval_reset_ms'])}")
        self._i_bar_fg.config(bg=i_clr)
        self._i_bar_fg.place(relwidth=i_pct / 100)

        # 周
        w_pct = agg["weekly_pct_remaining"]
        w_clr = pct_color(w_pct)
        self._w_pct_lbl.config(text=f"{w_pct:.0f}%", fg=w_clr)
        self._w_remain_lbl.config(text=f"剩余 {agg['weekly_remaining']:,} / {agg['weekly_total']:,}")
        self._w_reset_lbl.config(text=f"重置 {ms_to_hm(agg['weekly_reset_ms'])}")
        self._w_bar_fg.config(bg=w_clr)
        self._w_bar_fg.place(relwidth=w_pct / 100)

        self._time_lbl.config(text=data.get("fetched_at", ""))

    # ── 拖拽 ──────────────────────────────────────────

    def _on_drag_start(self, e):
        self._drag_start = (e.x_root, e.y_root,
                            self.root.winfo_x(), self.root.winfo_y())

    def _on_drag_motion(self, e):
        if self._drag_start is None:
            return
        sx, sy, ox, oy = self._drag_start
        dx, dy = e.x_root - sx, e.y_root - sy
        nx, ny = ox + dx, oy + dy
        self.root.geometry(f"+{nx}+{ny}")

    def _on_drag_end(self, e):
        if self._drag_start is not None:
            ox, oy = self.root.winfo_x(), self.root.winfo_y()
            self._custom_x = ox
            self._custom_y = oy
        self._drag_start = None

    # ── 右键菜单 ──────────────────────────────────────

    def _on_right_click(self, e):
        menu = tk.Menu(self.root, tearoff=0, bg=C["surface0"], fg=C["text"],
                       activebackground=C["surface1"], activeforeground=C["text"],
                       bd=0, relief="flat")
        menu.add_command(label="🔄 立即刷新", command=self._refresh)
        menu.add_command(label="📊 详细用量", command=lambda: self.app._show_detail_window())
        menu.add_separator()
        menu.add_command(label="📌 恢复默认位置", command=self._reset_position)
        menu.add_separator()
        menu.add_command(label="切换精简模式", command=self._switch_to_compact)
        menu.add_separator()
        menu.add_command(label="✕  关闭组件", command=self.hide)
        menu.post(e.x_root, e.y_root)

    def _refresh(self):
        t = threading.Thread(target=self.app._do_fetch, daemon=True)
        t.start()

    def _reset_position(self):
        self._custom_x = None
        self._custom_y = None
        if self.root:
            x, y = self._calc_position()
            self.root.geometry(f"{self.WIDGET_W}x{self.WIDGET_H}+{x}+{y}")

    def _switch_to_compact(self):
        """切换到精简模式"""
        self.app.config["widget_mode"] = "compact"
        save_config(self.app.config)
        self.hide()
        self.app.compact_widget.show()


# ===== 精简模式悬浮小组件 =====

class CompactFloatWidget:
    """
    精简版小组件：更矮、更紧凑，固定在任务栏托盘区域左侧
    单行显示 5H余量 | 周余量，不可拖拽，固定位置
    """

    WIDGET_W = 230
    WIDGET_H = 36
    PAD_R = 200    # 距屏幕右侧留出空间，避开系统托盘/时钟区域
    PAD_B = 0      # 紧贴任务栏上沿

    def __init__(self, app):
        self.app = app
        self.root = None
        self._visible = False

    def _get_taskbar_height(self) -> int:
        try:
            class APPBARDATA_S(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.wintypes.DWORD),
                    ("hWnd", ctypes.wintypes.HWND),
                    ("uCallbackMessage", ctypes.wintypes.UINT),
                    ("uEdge", ctypes.wintypes.UINT),
                    ("rc", ctypes.wintypes.RECT),
                    ("lParam", ctypes.wintypes.LPARAM),
                ]
            SPI_GETWORKAREA = 0x0030
            work_rect = ctypes.wintypes.RECT()
            ctypes.windll.user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work_rect), 0)
            screen_h = ctypes.windll.user32.GetSystemMetrics(1)
            return screen_h - work_rect.bottom
        except Exception:
            return 40

    def _reposition(self):
        """重新计算并设置位置（任务栏变化时调用）"""
        if not self.root or not self._visible:
            return
        try:
            x, y = self._calc_position()
            self.root.geometry(f"{self.WIDGET_W}x{self.WIDGET_H}+{x}+{y}")
        except Exception:
            pass

    def _calc_position(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        tb_h = self._get_taskbar_height()
        x = sw - self.WIDGET_W - self.PAD_R
        y = sh - tb_h - self.WIDGET_H - self.PAD_B
        return x, y

    def show(self):
        if self._visible and self.root and self.root.winfo_exists():
            self.root.lift()
            self.update_data()
            return
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def hide(self):
        self._visible = False
        if self.root:
            try:
                self.root.quit()
                self.root.destroy()
            except Exception:
                pass
            self.root = None

    def toggle(self):
        if self._visible and self.root and self.root.winfo_exists():
            self.hide()
        else:
            self.show()

    def _run(self):
        self._visible = True
        self.root = tk.Tk()
        root = self.root

        root.overrideredirect(True)
        root.attributes("-topmost", True)
        root.attributes("-alpha", 0.92)
        root.configure(bg=C["bg"])

        # Windows 11 圆角
        try:
            DWMWA_WINDOW_CORNER_PREFERENCE = 33
            DWM_WINDOW_CORNER_PREFERENCE_ROUND = 2
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.windll.user32.GetParent(root.winfo_id()),
                DWMWA_WINDOW_CORNER_PREFERENCE,
                ctypes.byref(ctypes.c_int(DWM_WINDOW_CORNER_PREFERENCE_ROUND)),
                ctypes.sizeof(ctypes.c_int)
            )
        except Exception:
            pass

        root.update_idletasks()
        x, y = self._calc_position()
        root.geometry(f"{self.WIDGET_W}x{self.WIDGET_H}+{x}+{y}")

        self._build_ui(root)
        self.update_data()

        # 定时重新定位（应对任务栏大小变化、DPI变化等）
        root.after(5000, self._periodic_reposition)

        # 右键菜单
        root.bind("<Button-3>", self._on_right_click)

        root.mainloop()
        self._visible = False
        self.root = None

    def _periodic_reposition(self):
        """每30秒检查并重新定位"""
        if not self._visible or not self.root or not self.root.winfo_exists():
            return
        self._reposition()
        self.root.after(30000, self._periodic_reposition)

    def _build_ui(self, root):
        """精简 UI：单行显示 5H余量 | 周余量"""
        container = tk.Frame(root, bg=C["bg"])
        container.pack(fill="both", expand=True, padx=10, pady=6)

        # 左侧：5H 余量
        left = tk.Frame(container, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True)

        tk.Label(left, text="5H", font=("Consolas", 8, "bold"),
                 bg=C["bg"], fg=C["overlay0"]).pack(side="left", padx=(0, 4))
        self._i_pct_lbl = tk.Label(left, text="—",
                                   font=("Consolas", 13, "bold"),
                                   bg=C["bg"], fg=C["green"])
        self._i_pct_lbl.pack(side="left")
        self._i_reset_lbl = tk.Label(left, text="",
                                     font=("Consolas", 7),
                                     bg=C["bg"], fg=C["overlay0"])
        self._i_reset_lbl.pack(side="left", padx=(4, 0))

        # 分隔
        tk.Frame(container, bg=C["surface1"], width=1).pack(side="left", fill="y", padx=8)

        # 右侧：周余量
        right = tk.Frame(container, bg=C["bg"])
        right.pack(side="left", fill="both", expand=True)

        tk.Label(right, text="W", font=("Consolas", 8, "bold"),
                 bg=C["bg"], fg=C["overlay0"]).pack(side="left", padx=(0, 4))
        self._w_pct_lbl = tk.Label(right, text="—",
                                   font=("Consolas", 13, "bold"),
                                   bg=C["bg"], fg=C["green"])
        self._w_pct_lbl.pack(side="left")
        self._w_reset_lbl = tk.Label(right, text="",
                                     font=("Consolas", 7),
                                     bg=C["bg"], fg=C["overlay0"])
        self._w_reset_lbl.pack(side="left", padx=(4, 0))

    def update_data(self):
        if not self._visible or not self.root:
            return
        try:
            self.root.after(0, self._do_update)
        except Exception:
            pass

    def _do_update(self):
        if not self.root or not self.root.winfo_exists():
            return

        data = self.app.usage_data
        err  = self.app.last_error

        if err or not data:
            self._i_pct_lbl.config(text="ERR" if err else "…", fg=C["red"] if err else C["overlay0"])
            self._w_pct_lbl.config(text="—", fg=C["overlay0"])
            self._i_reset_lbl.config(text="")
            self._w_reset_lbl.config(text="")
            return

        agg = aggregate(data.get("models", []))
        if not agg:
            return

        # 5h 窗口
        i_pct = agg["interval_pct_remaining"]
        self._i_pct_lbl.config(text=f"{i_pct:.0f}%", fg=pct_color(i_pct))
        self._i_reset_lbl.config(text=f"({ms_to_hm(agg['interval_reset_ms'])})")

        # 周
        w_pct = agg["weekly_pct_remaining"]
        self._w_pct_lbl.config(text=f"{w_pct:.0f}%", fg=pct_color(w_pct))
        self._w_reset_lbl.config(text=f"({ms_to_hm(agg['weekly_reset_ms'])})")

    def _on_right_click(self, e):
        menu = tk.Menu(self.root, tearoff=0, bg=C["surface0"], fg=C["text"],
                       activebackground=C["surface1"], activeforeground=C["text"],
                       bd=0, relief="flat")
        menu.add_command(label="🔄 立即刷新", command=self._refresh)
        menu.add_command(label="📊 详细用量", command=lambda: self.app._show_detail_window())
        menu.add_separator()
        menu.add_command(label="切换标准模式", command=self._switch_to_standard)
        menu.add_separator()
        menu.add_command(label="✕ 隐藏组件", command=self.hide)
        menu.post(e.x_root, e.y_root)

    def _refresh(self):
        t = threading.Thread(target=self.app._do_fetch, daemon=True)
        t.start()

    def _switch_to_standard(self):
        """切换到标准模式"""
        self.app.config["widget_mode"] = "standard"
        save_config(self.app.config)
        self.hide()
        self.app.widget.show()


# ===== 主应用类 =====

class MinimaxTrayApp:
    def __init__(self):
        self.config = load_config()
        self.usage_data = None
        self.last_error = None
        self._stop_event = threading.Event()
        self._tray_icon = None
        self._fetch_lock = threading.Lock()
        self._current_state = "unknown"
        self._current_percent = 0.0

        self.widget = FloatWidget(self)
        self.compact_widget = CompactFloatWidget(self)

    # ── 数据刷新 ─────────────────────────────────────

    def _refresh_loop(self):
        while not self._stop_event.is_set():
            if self.config.get("api_key"):
                self._do_fetch()
            interval = max(10, int(self.config.get("refresh_interval", 60)))
            self._stop_event.wait(interval)

    def _do_fetch(self):
        with self._fetch_lock:
            api_key = self.config.get("api_key", "").strip()
            if not api_key:
                return
            result = fetch_usage(api_key)
            if result["ok"]:
                self.usage_data = result
                self.last_error = None
                models = result.get("models", [])
                if models:
                    agg = aggregate(models)
                    pct_rem = agg["interval_pct_remaining"]
                    if pct_rem >= 50:
                        state = "healthy"
                    elif pct_rem >= 20:
                        state = "warning"
                    else:
                        state = "danger"
                    self._current_state = state
                    self._current_percent = pct_rem   # 余量百分比
                else:
                    self._current_state = "unknown"
                    self._current_percent = 0
            else:
                self.usage_data = None
                self.last_error = result.get("error", "未知错误")
                self._current_state = "danger"
                self._current_percent = 0

            self._update_icon()
            # 通知小组件刷新
            self.widget.update_data()
            self.compact_widget.update_data()

    def _update_icon(self):
        if self._tray_icon is None:
            return
        new_img = create_tray_icon(self._current_state, self._current_percent)
        self._tray_icon.icon = new_img
        self._update_tooltip()

    def _update_tooltip(self):
        if self._tray_icon is None:
            return
        if self.last_error:
            tip = f"MiniMax Token Plan\n⚠ {self.last_error}"
        elif self.usage_data:
            agg = aggregate(self.usage_data.get("models", []))
            if agg:
                tip = (
                    f"MiniMax Token Plan  {self.usage_data.get('fetched_at', '')}\n"
                    f"5h窗口: {agg['interval_remaining']:,} 剩余 ({agg['interval_pct_remaining']:.0f}%)  重置 {ms_to_hm(agg['interval_reset_ms'])}\n"
                    f"本  周: {agg['weekly_remaining']:,} 剩余 ({agg['weekly_pct_remaining']:.0f}%)  重置 {ms_to_hm(agg['weekly_reset_ms'])}"
                )
            else:
                tip = "MiniMax Token Plan\n暂无数据"
        else:
            tip = "MiniMax Token Plan\n请先配置 API Key"
        self._tray_icon.title = tip

    # ── 托盘菜单 ─────────────────────────────────────

    def _build_menu(self):
        return pystray.Menu(
            pystray.MenuItem("📊 查看详细用量", self._show_detail_window, default=True),
            pystray.MenuItem("🔲 显示/隐藏小组件", self._toggle_widget),
            pystray.MenuItem("🔄 立即刷新", self._manual_refresh),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("⚙ 设置", self._show_settings_window),
            pystray.MenuItem("🌐 打开 MiniMax 平台", self._open_platform),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ 退出", self._quit),
        )

    def _toggle_widget(self, icon=None, item=None):
        mode = self.config.get("widget_mode", "compact")
        if mode == "compact":
            self.compact_widget.toggle()
            self.config["widget_visible"] = self.compact_widget._visible
        else:
            self.widget.toggle()
            self.config["widget_visible"] = self.widget._visible
        save_config(self.config)

    def _manual_refresh(self, icon=None, item=None):
        t = threading.Thread(target=self._do_fetch, daemon=True)
        t.start()

    def _open_platform(self, icon=None, item=None):
        webbrowser.open("https://platform.minimaxi.com/user-center/token-plan")

    def _quit(self, icon=None, item=None):
        self._stop_event.set()
        self.widget.hide()
        self.compact_widget.hide()
        if self._tray_icon:
            self._tray_icon.stop()

    # ── 详情窗口 ─────────────────────────────────────

    def _show_detail_window(self, icon=None, item=None):
        t = threading.Thread(target=self._open_detail_window, daemon=True)
        t.start()

    def _open_detail_window(self):
        root = tk.Tk()
        root.title("MiniMax Token Plan 用量详情")
        root.configure(bg=C["bg"])
        root.resizable(False, False)
        root.geometry("500x560")
        root.lift()
        root.focus_force()

        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"500x560+{(sw-500)//2}+{(sh-560)//2}")

        # 标题行
        title_row = tk.Frame(root, bg=C["bg"], pady=12)
        title_row.pack(fill="x", padx=20)
        tk.Label(title_row, text="MiniMax Token Plan 用量",
                 font=("微软雅黑", 14, "bold"), bg=C["bg"], fg=C["accent"]).pack(side="left")

        def do_refresh():
            threading.Thread(target=self._do_fetch, daemon=True).start()
            root.after(800, lambda: render_content(content_frame))

        tk.Button(title_row, text="🔄 刷新", command=do_refresh,
                  bg=C["surface0"], fg=C["text"], relief="flat",
                  padx=8, pady=3, cursor="hand2").pack(side="right")

        # ── 汇总卡片 ──
        summary_frame = tk.Frame(root, bg=C["bg"])
        summary_frame.pack(fill="x", padx=16, pady=(0, 4))
        self._summary_frame = summary_frame

        # ── 滚动内容区 ──
        canvas = tk.Canvas(root, bg=C["bg"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        content_frame = tk.Frame(canvas, bg=C["bg"])
        content_frame.bind("<Configure>",
                           lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=content_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=(0, 10))
        scrollbar.pack(side="right", fill="y", pady=(0, 10))

        def render_content(frame):
            for w in frame.winfo_children():
                w.destroy()
            for w in summary_frame.winfo_children():
                w.destroy()

            if self.last_error:
                tk.Label(frame, text=f"⚠ {self.last_error}",
                         font=("微软雅黑", 11), bg=C["bg"], fg=C["red"],
                         wraplength=440, justify="left").pack(pady=20, padx=20, anchor="w")
                return
            if not self.usage_data:
                tk.Label(frame, text="尚未获取数据，请配置 API Key 后等待刷新",
                         font=("微软雅黑", 11), bg=C["bg"], fg=C["subtext0"],
                         wraplength=440).pack(pady=30)
                return

            tk.Label(frame, text=f"最后更新: {self.usage_data.get('fetched_at', '—')}",
                     font=("微软雅黑", 9), bg=C["bg"], fg=C["overlay0"]
                     ).pack(anchor="w", padx=20, pady=(4, 8))

            # 汇总卡片
            agg = aggregate(self.usage_data.get("models", []))
            if agg:
                self._render_summary_card(summary_frame, agg)

            for model in self.usage_data.get("models", []):
                self._render_model_card(frame, model)

        render_content(content_frame)

        # 底部按钮
        btn_row = tk.Frame(root, bg=C["bg"], pady=10)
        btn_row.pack(fill="x", padx=20)
        tk.Button(btn_row, text="⚙ 设置",
                  command=lambda: [root.destroy(), self._show_settings_window()],
                  bg=C["surface0"], fg=C["text"], relief="flat",
                  padx=12, pady=5, cursor="hand2").pack(side="left")
        tk.Button(btn_row, text="🌐 打开平台", command=self._open_platform,
                  bg=C["surface0"], fg=C["text"], relief="flat",
                  padx=12, pady=5, cursor="hand2").pack(side="left", padx=8)
        tk.Button(btn_row, text="关闭", command=root.destroy,
                  bg=C["accent"], fg=C["bg"], relief="flat",
                  padx=12, pady=5, cursor="hand2",
                  font=("微软雅黑", 10, "bold")).pack(side="right")

        root.mainloop()

    def _render_summary_card(self, parent, agg: dict):
        """汇总卡片：同时展示5h和周余量"""
        card = tk.Frame(parent, bg=C["surface0"], pady=10, padx=14)
        card.pack(fill="x", pady=4)

        tk.Label(card, text="全部模型汇总",
                 font=("微软雅黑", 9, "bold"), bg=C["surface0"], fg=C["subtext0"]
                 ).pack(anchor="w", pady=(0, 6))

        cols = tk.Frame(card, bg=C["surface0"])
        cols.pack(fill="x")

        def col_block(parent, title, pct, remaining, total, reset_ms, bar_clr):
            f = tk.Frame(parent, bg=C["surface0"])
            f.pack(side="left", expand=True, fill="x", padx=(0, 8))

            tk.Label(f, text=title, font=("微软雅黑", 8),
                     bg=C["surface0"], fg=C["subtext0"]).pack(anchor="w")
            tk.Label(f, text=f"{pct:.0f}%",
                     font=("Consolas", 18, "bold"), bg=C["surface0"], fg=bar_clr
                     ).pack(anchor="w")
            tk.Label(f, text=f"剩余 {remaining:,} / {total:,}",
                     font=("微软雅黑", 8), bg=C["surface0"], fg=C["subtext0"]
                     ).pack(anchor="w")
            # 进度条
            bar_bg = tk.Frame(f, bg=C["surface1"], height=5)
            bar_bg.pack(fill="x", pady=(3, 2))
            tk.Frame(bar_bg, bg=bar_clr, height=5).place(
                x=0, y=0, relwidth=pct/100, relheight=1)
            tk.Label(f, text=f"重置 {ms_to_hm(reset_ms)}",
                     font=("微软雅黑", 7), bg=C["surface0"], fg=C["overlay0"]
                     ).pack(anchor="w")

        col_block(cols, "5H 窗口",
                  agg["interval_pct_remaining"],
                  agg["interval_remaining"], agg["interval_total"],
                  agg["interval_reset_ms"],
                  pct_color(agg["interval_pct_remaining"]))

        tk.Frame(cols, bg=C["surface1"], width=1).pack(side="left", fill="y", padx=4)

        col_block(cols, "本  周",
                  agg["weekly_pct_remaining"],
                  agg["weekly_remaining"], agg["weekly_total"],
                  agg["weekly_reset_ms"],
                  pct_color(agg["weekly_pct_remaining"]))

    def _render_model_card(self, parent, model: dict):
        """单个模型卡片"""
        card = tk.Frame(parent, bg=C["surface0"], pady=8, padx=14)
        card.pack(fill="x", padx=16, pady=4)

        # 模型名称
        tk.Label(card, text=model["model_name"],
                 font=("微软雅黑", 10, "bold"), bg=C["surface0"], fg=C["text"]
                 ).pack(anchor="w", pady=(0, 6))

        row = tk.Frame(card, bg=C["surface0"])
        row.pack(fill="x")

        def mini_block(parent, title, pct, remaining, total, reset_ms):
            f = tk.Frame(parent, bg=C["surface0"])
            f.pack(side="left", expand=True, fill="x", padx=(0, 6))
            clr = pct_color(pct)
            tk.Label(f, text=title, font=("微软雅黑", 7),
                     bg=C["surface0"], fg=C["subtext0"]).pack(anchor="w")
            tk.Label(f, text=f"{pct:.0f}%",
                     font=("Consolas", 14, "bold"), bg=C["surface0"], fg=clr
                     ).pack(anchor="w")
            tk.Label(f, text=f"{remaining:,} / {total:,}",
                     font=("Consolas", 8), bg=C["surface0"], fg=C["subtext0"]
                     ).pack(anchor="w")
            bar_bg = tk.Frame(f, bg=C["surface1"], height=4)
            bar_bg.pack(fill="x", pady=(2, 1))
            tk.Frame(bar_bg, bg=clr, height=4).place(
                x=0, y=0, relwidth=pct/100, relheight=1)
            tk.Label(f, text=f"重置 {ms_to_hm(reset_ms)}",
                     font=("微软雅黑", 7), bg=C["surface0"], fg=C["overlay0"]
                     ).pack(anchor="w")

        mini_block(row, "5H 窗口",
                   model["interval_pct_remaining"],
                   model["interval_remaining"], model["interval_total"],
                   model["interval_reset_ms"])

        tk.Frame(row, bg=C["surface1"], width=1).pack(side="left", fill="y", padx=4)

        mini_block(row, "本  周",
                   model["weekly_pct_remaining"],
                   model["weekly_remaining"], model["weekly_total"],
                   model["weekly_reset_ms"])

    # ── 设置窗口 ─────────────────────────────────────

    def _show_settings_window(self, icon=None, item=None):
        t = threading.Thread(target=self._open_settings_window, daemon=True)
        t.start()

    def _open_settings_window(self):
        root = tk.Tk()
        root.title("MiniMax Tray 设置")
        root.configure(bg=C["bg"])
        root.resizable(False, False)
        root.geometry("420x380")
        root.lift()
        root.focus_force()

        root.update_idletasks()
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"420x380+{(sw-420)//2}+{(sh-380)//2}")

        tk.Label(root, text="⚙ 设置", font=("微软雅黑", 14, "bold"),
                 bg=C["bg"], fg=C["accent"]).pack(pady=(18, 10))

        form = tk.Frame(root, bg=C["bg"])
        form.pack(padx=30, fill="x")

        # API Key
        tk.Label(form, text="Token Plan API Key", font=("微软雅黑", 10),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w", pady=(10, 2))
        api_key_var = tk.StringVar(value=self.config.get("api_key", ""))
        api_entry = tk.Entry(form, textvariable=api_key_var, show="*",
                             font=("Consolas", 10), bg=C["surface0"], fg=C["text"],
                             insertbackground=C["text"], relief="flat", bd=0)
        api_entry.pack(fill="x", ipady=6)
        tk.Frame(form, bg=C["surface1"], height=1).pack(fill="x")

        show_var = tk.BooleanVar(value=False)
        def toggle_show():
            api_entry.config(show="" if show_var.get() else "*")
        tk.Checkbutton(form, text="显示 API Key", variable=show_var, command=toggle_show,
                       bg=C["bg"], fg=C["subtext0"], selectcolor=C["surface0"],
                       activebackground=C["bg"], font=("微软雅黑", 9)).pack(anchor="w", pady=(2, 8))

        # 刷新间隔
        tk.Label(form, text="自动刷新间隔（秒，最低10）", font=("微软雅黑", 10),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w", pady=(6, 2))
        interval_var = tk.StringVar(value=str(self.config.get("refresh_interval", 60)))
        tk.Entry(form, textvariable=interval_var, width=10,
                 font=("Consolas", 10), bg=C["surface0"], fg=C["text"],
                 insertbackground=C["text"], relief="flat", bd=0
                 ).pack(anchor="w", ipady=6)
        tk.Frame(form, bg=C["surface1"], height=1).pack(fill="x", pady=(0, 8))

        # 开机自启
        autostart_var = tk.BooleanVar(value=self.config.get("autostart", False))
        tk.Checkbutton(form, text="开机自动启动", variable=autostart_var,
                       bg=C["bg"], fg=C["text"], selectcolor=C["surface0"],
                       activebackground=C["bg"], font=("微软雅黑", 10)).pack(anchor="w", pady=4)

        # 启动时显示小组件
        widget_var = tk.BooleanVar(value=self.config.get("widget_visible", True))
        tk.Checkbutton(form, text="启动时显示小组件", variable=widget_var,
                       bg=C["bg"], fg=C["text"], selectcolor=C["surface0"],
                       activebackground=C["bg"], font=("微软雅黑", 10)).pack(anchor="w", pady=2)

        # 小组件显示模式
        tk.Label(form, text="小组件显示模式", font=("微软雅黑", 10),
                 bg=C["bg"], fg=C["text"]).pack(anchor="w", pady=(8, 2))
        mode_var = tk.StringVar(value=self.config.get("widget_mode", "compact"))
        mode_frame = tk.Frame(form, bg=C["bg"])
        mode_frame.pack(anchor="w")
        for val, txt in [("compact", "精简（单行紧凑）"), ("standard", "标准（详细面板）")]:
            tk.Radiobutton(mode_frame, text=txt, variable=mode_var, value=val,
                           bg=C["bg"], fg=C["text"], selectcolor=C["surface0"],
                           activebackground=C["bg"], font=("微软雅黑", 9)
                           ).pack(side="left", padx=(0, 16))

        status_var = tk.StringVar(value="")
        tk.Label(form, textvariable=status_var, font=("微软雅黑", 9),
                 bg=C["bg"], fg=C["green"]).pack(anchor="w")

        btn_row = tk.Frame(root, bg=C["bg"])
        btn_row.pack(side="bottom", pady=16, padx=30, fill="x")

        def save():
            key = api_key_var.get().strip()
            try:
                interval = int(interval_var.get())
                if interval < 10:
                    raise ValueError
            except ValueError:
                messagebox.showerror("输入错误", "刷新间隔须为不小于10的整数", parent=root)
                return
            self.config["api_key"] = key
            self.config["refresh_interval"] = interval
            self.config["autostart"] = autostart_var.get()
            self.config["widget_visible"] = widget_var.get()
            self.config["widget_mode"] = mode_var.get()
            save_config(self.config)
            set_autostart(autostart_var.get())
            # 根据设置显示/隐藏小组件
            mode = mode_var.get()
            if widget_var.get():
                # 先隐藏两个 widget
                self.widget.hide()
                self.compact_widget.hide()
                # 再显示对应的
                if mode == "compact":
                    self.compact_widget.show()
                else:
                    self.widget.show()
            else:
                self.widget.hide()
                self.compact_widget.hide()
            status_var.set("✓ 已保存，立即刷新中…")
            threading.Thread(target=self._do_fetch, daemon=True).start()
            root.after(1200, root.destroy)

        def test_api():
            key = api_key_var.get().strip()
            if not key:
                messagebox.showwarning("提示", "请先输入 API Key", parent=root)
                return
            status_var.set("⏳ 测试中…")
            root.update()
            result = fetch_usage(key)
            if result["ok"]:
                agg = aggregate(result.get("models", []))
                if agg:
                    status_var.set(f"✓ 成功！5h余量 {agg['interval_remaining']:,}  周余量 {agg['weekly_remaining']:,}")
                else:
                    status_var.set("✓ 连接成功（暂无模型数据）")
            else:
                status_var.set(f"✗ {result.get('error', '未知错误')}")

        tk.Button(btn_row, text="测试连接", command=test_api,
                  bg=C["surface0"], fg=C["text"], relief="flat",
                  padx=12, pady=6, cursor="hand2").pack(side="left")
        tk.Button(btn_row, text="取消", command=root.destroy,
                  bg=C["surface0"], fg=C["text"], relief="flat",
                  padx=12, pady=6, cursor="hand2").pack(side="right")
        tk.Button(btn_row, text="保存", command=save,
                  bg=C["accent"], fg=C["bg"], relief="flat",
                  padx=16, pady=6, cursor="hand2",
                  font=("微软雅黑", 10, "bold")).pack(side="right", padx=8)

        root.mainloop()

    # ── 启动 ─────────────────────────────────────────

    def run(self):
        if not self.config.get("api_key"):
            threading.Thread(target=self._open_settings_window, daemon=True).start()

        # 启动后台刷新
        threading.Thread(target=self._refresh_loop, daemon=True).start()

        # 首次立即刷新
        if self.config.get("api_key"):
            threading.Thread(target=self._do_fetch, daemon=True).start()

        # 按配置决定是否显示小组件
        if self.config.get("widget_visible", True):
            mode = self.config.get("widget_mode", "compact")
            if mode == "compact":
                threading.Thread(target=self.compact_widget.show, daemon=True).start()
            else:
                threading.Thread(target=self.widget.show, daemon=True).start()

        # 托盘图标
        icon_img = create_tray_icon("loading")
        self._tray_icon = pystray.Icon(
            name="minimax_tray",
            icon=icon_img,
            title="MiniMax Token Plan",
            menu=self._build_menu(),
        )
        self._tray_icon.run()


# ===== 入口 =====

if __name__ == "__main__":
    app = MinimaxTrayApp()
    app.run()
