# 雨课堂通用刷课工具 (yuketang-bot)

可复用的雨课堂自动刷课工具，支持本地网页控制台、扫码登录、课程发现、断点续刷；数据仅保存在本机（`127.0.0.1`）。

## 下载

**发布页：** [GitHub Releases v1.0.0](https://github.com/Diego-2024/GZHU-yuketang/releases/tag/v1.0.0)

- **[Windows 安装包（推荐）](https://github.com/Diego-2024/GZHU-yuketang/releases/download/v1.0.0/yuketang-bot-1.0.0-setup.exe)** → `yuketang-bot-1.0.0-setup.exe`
- **[Windows 便携版](https://github.com/Diego-2024/GZHU-yuketang/releases/download/v1.0.0/yuketang-bot.exe)** → `yuketang-bot.exe`（下载后双击即可）

> **便携版提示：** 建议新建一个空文件夹（如 `D:\yuketang-bot\`），把 `yuketang-bot.exe` 放进去再运行。程序会在同目录生成 `config.yaml`、`data/`、`profiles/` 等文件，避免散落在桌面或下载目录。

> 若 Windows SmartScreen 提示「已阻止」，点击「更多信息」→「仍要运行」。详细安装与使用步骤见下方。

## 声明

本项目**仅供学习与技术交流**使用，请勿用于任何违规、作弊或恶意用途。

- 使用者应自行遵守所在学校 / 平台的相关规定与法律法规
- 因不当使用本项目所产生的一切后果，由使用者本人承担，与项目作者无关
- 请合理、克制地使用；严禁批量滥用、破坏平台服务或侵犯他人权益

使用即表示你已阅读并同意上述声明。

## 功能截图

> 以下截图中的昵称已替换为「示例用户」，仅作功能演示。

### 概览

![概览](docs/screenshots/overview.png)

### 课程发现（自动标记无视频课程）

![课程发现](docs/screenshots/discover.png)

### 刷课任务清单

![刷课任务](docs/screenshots/run.png)

### 实时任务日志

![任务日志](docs/screenshots/logs.png)

### 账号与设置

![设置](docs/screenshots/settings.png)

## 功能特性

- **本地网页控制台**（推荐）：浏览器操作扫码登录、发现课程、刷课与实时日志
- CLI：`login` / `discover` / `run` / `status`
- SQLite 断点续刷，多账号 profile 隔离
- 自动跳过已看完视频，自动标记无视频课程

## 安装与使用

### 1. 下载并启动

**方式 A：安装包（推荐）**

1. 下载 [`yuketang-bot-1.0.0-setup.exe`](https://github.com/Diego-2024/GZHU-yuketang/releases/download/v1.0.0/yuketang-bot-1.0.0-setup.exe)
2. 双击安装，按向导完成（可选勾选「创建桌面快捷方式」）
3. 安装结束后勾选「立即启动」，或从桌面 / 开始菜单打开「雨课堂刷课工具」

**方式 B：便携版**

1. **新建一个空文件夹**（如 `D:\yuketang-bot\`），下载 [`yuketang-bot.exe`](https://github.com/Diego-2024/GZHU-yuketang/releases/download/v1.0.0/yuketang-bot.exe) 放入其中
2. 双击运行（首次会在同目录自动生成 `config.yaml`；之后还会出现 `data/`、`profiles/` 等数据目录）

> 不建议直接放在桌面或「下载」文件夹里运行，以免配置与缓存文件散落、不好清理。

> **首次启动较慢：** 单文件 exe 首次解压需要几秒到十几秒，请等待浏览器自动打开、托盘出现图标。

### 2. 控制台出现后怎么用

程序启动后会：

1. 在后台启动本地服务
2. 自动打开浏览器：`http://127.0.0.1:18765/`
3. 在系统托盘显示图标（右键可「打开控制台」/「退出」）

按下面四步操作即可刷课：

| 步骤 | 页面 | 操作 |
|------|------|------|
| ① 扫码登录 | **扫码登录** | 选择账号 → 点「开始登录」→ 用雨课堂 App 扫码 → 点「我已扫码」 |
| ② 发现课程 | **课程发现** | 点「开始发现」→ 勾选要刷的课程 → 点「爬取选中课程」 |
| ③ 开始刷课 | **刷课任务** | 点「开始刷课」，右侧/下方任务日志可看实时进度 |
| ④ 查看进度 | **概览 / 刷课任务** | 已刷完显示「已刷完」；无视频课显示「无视频」；可筛选待刷 / 已完成 |

### 3. 退出

右键系统托盘图标 → **退出**。不要只关浏览器标签页，否则后台服务可能仍在运行。

### 4. 常见问题

| 问题 | 处理 |
|------|------|
| 浏览器没自动打开 | 托盘图标右键「打开控制台」，或手动访问 `http://127.0.0.1:18765/` |
| 端口被占用 | 先退出旧进程；或结束任务管理器中的 `yuketang-bot.exe` 后再启动 |
| 没有课程 / 0 条视频 | 确认已登录；再点「开始发现」；无视频课会被标记为「无视频」 |
| 想换账号 / 加账号 | 在「设置」里「添加账号」，每个账号独立扫码登录 |

> 安装包 / 便携版**不包含**登录态与课程数据，首次使用需扫码登录并发现课程。数据保存在本机，不会上传。

## 安装（源码运行）

适合开发者或想改代码的用户：

```bash
pip install -r requirements.txt
copy config.example.yaml config.yaml   # Windows
python main.py web
```

浏览器访问 `http://127.0.0.1:18765/`，操作流程与上方「控制台出现后怎么用」相同。

```bash
# 其他常用命令
python main.py web --port 18765
python main.py web --no-browser
python main.py gui          # 托盘模式（与 exe 相同体验）
```

## CLI 用法

```bash
python main.py login
python main.py discover
python main.py run
python main.py run --account 账号1
python main.py status
python main.py reset --course <course_url>
```

## 配置说明

见 `config.example.yaml`：

| 字段 | 说明 |
|------|------|
| `base_url` | 雨课堂主站或学校子站 |
| `home_url` | 课程列表主页 |
| `accounts` | 多账号，每个独立 browser profile |
| `loop` | 心跳刷课参数 |
| `db_path` | SQLite 任务库路径 |
| `profiles_root` | 浏览器 profile 目录 |

## 项目结构

```
yuketang-bot/
├── main.py
├── config.yaml
└── yuketang_bot/
    ├── browser.py / discover.py / api.py / runner.py / store.py
    └── web/                 # 本地控制台
        ├── app.py           # FastAPI
        ├── jobs.py          # 后台任务 + SSE
        └── static/          # SPA 前端
```

## 依赖

- Python 3.8+
- requests / DrissionPage / PyYAML / FastAPI / Uvicorn
- Windows 优先（空格播放依赖窗口置前）

## 打包成 exe（Windows）

安装依赖后执行：

```bash
pip install -r requirements.txt
python build.py
```

打包完成后在 `dist/` 目录生成：

```
dist/
├── yuketang-bot.exe
└── config.example.yaml
```

本地也可用 Inno Setup 编译安装包：

```bash
# 需先安装 Inno Setup，并已生成 dist\yuketang-bot.exe
ISCC.exe setup.iss
```

发布到 GitHub Releases 时，可用 Actions 工作流自动构建并上传安装包 / 便携版。
