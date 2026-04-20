# MiniMax Tray — Token Plan 用量监控工具

> Windows 任务栏实时监控 MiniMax Token Plan 余量的桌面小工具

## 功能特性

- 🖥 **系统托盘图标**：颜色随余量变化
  - 🟢 绿色：剩余 ≥ 50%（安全）
  - 🟡 黄色：剩余 20~50%（警告）
  - 🔴 红色：剩余 < 20%（告急）
- 📌 **任务栏悬浮小组件**（两种显示模式）
  - **精简模式**（默认）：40px 高度单行显示，固定在任务栏托盘左侧，展示 5H余量 + 周余量
  - **标准模式**：详细面板显示进度条、剩余量、重置倒计时
- 📊 **悬停 Tooltip** + **双击详情面板**：查看每个模型的用量
- 🔄 **自动刷新**：可配置间隔（最低 10 秒）
- ⚙ **设置界面**：API Key 安全存储于本机 AppData
- 🚀 **开机自启**：可选注册到注册表
- 🌐 **一键跳转**：直达 MiniMax Token Plan 页面

## 截图

### 精简模式（默认）

```
┌──────────────────────────────────┐
│  5H  78% (2h 15m)  │  W  62% (3d) │
└──────────────────────────────────┘
```

### 标准模式

```
┌──────────────────────────────────┐
│ ● ● ●  MiniMax  Token Plan  11:23│
├────────────────┬─────────────────┤
│  5H 窗口       │  本 周           │
│  78%           │  62%            │
│  剩余 780/1000 │  剩余 6200/10000│
│  ████████░░    │  ██████░░░░     │
│  重置 2h 15m   │  重置 3d 12h    │
└────────────────┴─────────────────┘
```

## 使用方法

### 方式一：直接运行

1. 下载 `dist/MiniMaxTray.exe`
2. 双击运行
3. 首次运行弹出设置窗口，填入 Token Plan 专属 API Key
4. 点击"测试连接"验证后保存

### 方式二：从源码运行

```bash
pip install pystray pillow requests
python minimax_tray.py
```

### 方式三：自行打包

```bat
build.bat
```

## API 接口

| 项目 | 内容 |
|------|------|
| 接口地址 | `GET https://www.minimaxi.com/v1/api/openplatform/coding_plan/remains` |
| 认证方式 | `Authorization: Bearer {API_KEY}` |

> ⚠ Token Plan API Key 需在 [MiniMax 平台](https://platform.minimaxi.com/user-center/token-plan) 获取，与按量计费 Key 不可互换

## 配置文件

`%APPDATA%\MiniMaxTray\config.json`

```json
{
  "api_key": "your-token-plan-api-key",
  "refresh_interval": 60,
  "autostart": false,
  "widget_visible": true,
  "widget_mode": "compact"
}
```

## 技术栈

- Python 3.12
- [pystray](https://github.com/moses-palmer/pystray) — 系统托盘
- [Pillow](https://python-pillow.org/) — 图标绘制
- [tkinter](https://docs.python.org/3/library/tkinter.html) — GUI 组件
- [PyInstaller](https://pyinstaller.org/) — 打包

## License

MIT
