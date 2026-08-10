# Cake 面板

Cake 是一个基于 Flask 的轻量级服务器管理面板，提供系统监控、进程管理、文件管理、定时任务与远程桌面（VNC）等功能，并通过账户认证与加密通信保护管理操作。

## 功能特性

- **账户系统**：基于 SQLite 存储，使用 PBKDF2-SHA256（200,000 次迭代）哈希密码，支持添加、删除、列出与校验账户。
- **安全登录**：登录锁定（临时锁定时长可配置）、单账户锁定、系统级安全锁定（登录失败过多后拒绝所有请求）。
- **IP 访问控制**：仅允许配置的 IP 访问面板。
- **加密通信**：API 请求与响应使用 AES-256-GCM 加密，会话密钥通过 RSA-OAEP 密钥交换协商。
- **系统监控**：实时展示 CPU、内存、磁盘、网络、运行时间、进程数等系统信息。
- **进程管理**：按 CPU / 内存 / 名称排序查看进程，可终止指定进程。
- **文件管理**：浏览目录、上传 / 下载（文件夹自动打包为 ZIP）、新建 / 删除 / 重命名文件与目录。
- **定时任务**：支持一次性、每日、每周、每年、倒计时等调度类型，可开关、立即执行、自动删除。
- **远程桌面**：通过 websockify + noVNC 在浏览器中访问远程 VNC 桌面。

## 目录结构

```
cake/
├── cake.py          # Flask 主程序（Web 路由、API、调度器、VNC 代理）
├── pam.py           # 账户管理工具（PBKDF2 哈希、SQLite 存储）
├── config.json      # 配置文件（VNC、面板端口、IP 白名单、安全策略、密钥）
├── account.db       # 账户数据库（SQLite，运行时生成）
├── tasks.json       # 定时任务数据（运行时生成）
├── requirements.txt # Python 依赖
├── templates/       # HTML 页面模板及内置的 noVNC 前端
├── venv.bat         # Windows 虚拟环境激活脚本
└── venv.sh          # Linux / macOS 虚拟环境激活脚本
```

## 环境要求

- Python 3.8+
- 依赖：Flask、cryptography、psutil、websockify（见 `requirements.txt`）

## 安装与启动

```bash
# 1. 创建并激活虚拟环境
python -m venv venv
# Windows:
venv.bat
# Linux / macOS:
source venv.sh

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动面板
python cake.py
```

默认访问地址：`http://127.0.0.1:8050`

首次启动后需先创建一个账户：

```bash
python pam.py add <用户名> <密码>
```

常用账户命令：

```bash
python pam.py add <用户名> <密码>   # 添加用户
python pam.py remove <用户名>       # 删除用户
python pam.py list -v               # 列出所有用户
python pam.py verify <用户名>       # 校验账户（密码从 stdin 读取）
```

## 配置说明（config.json）

| 配置项 | 说明 | 默认值 |
| --- | --- | --- |
| `vnc.ip` | VNC 服务器 IP 地址 | `null` |
| `vnc.port` | VNC 服务器端口 | `null` |
| `vnc.wsport` | noVNC WebSocket 端口 | `6080` |
| `panel.ip` | 允许访问面板的 IP 列表 | `["127.0.0.1"]`（填入 `"0.0.0.0"` 表示不限制） |
| `panel.port` | 面板监听端口 | `8050` |
| `security.safety_warning.*` | 是否显示安全提示横幅（HTTPS / 锁定） | `true` |
| `security.lockout.max_attempts` | 触发临时锁定的失败次数（0 为关闭） | `5` |
| `security.lockout.lockout_duration` | 临时锁定时长（秒） | `30` |
| `security.lockout.lockdown_max_attempts` | 单账户永久锁定的失败次数 | `15` |
| `security.lockdown.max_attempts` | 触发系统安全锁定的失败次数（0 为关闭） | `0` |

> `secret_key` 由程序在首次运行时自动生成，请勿泄露。删除该配置项可重新生成。

## 使用 VNC 远程桌面

1. 在 `config.json` 中配置 `vnc.ip` 与 `vnc.port`（WebSocket 端口默认 `6080`）。
2. 登录面板后点击「远程桌面」，程序会自动启动 websockify 代理并在浏览器中打开 noVNC 客户端。

## 安全建议

- 请通过 HTTPS（反向代理，如 Nginx）访问面板，避免明文传输。
- 保持登录锁定与安全锁定策略开启，防止暴力破解。
- 将 `panel.ip` 限制为可信的内网 / 管理 IP。
- 定期更换账户密码，不要使用弱密码。

## 技术栈

- 后端：Python / Flask
- 安全：cryptography（RSA-OAEP、AES-256-GCM、PBKDF2-SHA256）
- 系统信息：psutil
- 远程桌面：websockify + noVNC
- 存储：SQLite
