import atexit
import json
import io, os, zipfile, re
import subprocess
import sys
import time
import platform
import getpass
import socket
import signal
import threading
import uuid
import datetime
import calendar
import shutil
import stat
import mimetypes
import psutil
from flask import Flask, jsonify, render_template, request, redirect, send_from_directory, send_file, abort, session

app = Flask(__name__)
app.secret_key = os.urandom(32).hex()

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import base64 as b64

_rsa_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_rsa_public = _rsa_private.public_key()
_rsa_public_pem = _rsa_public.public_bytes(
    encoding=serialization.Encoding.PEM,
    format=serialization.PublicFormat.SubjectPublicKeyInfo
).decode()

@app.route('/api/crypto-key')
def crypto_key():
    return jsonify({"ok": True, "key": _rsa_public_pem})

@app.route('/api/crypto-session', methods=['POST'])
def crypto_session():
    data = request.get_json()
    if not data or 'key' not in data:
        return jsonify({"ok": False, "error": "Missing key"}), 400
    try:
        encrypted_key = b64.b64decode(data['key'])
        aes_key = _rsa_private.decrypt(
            encrypted_key,
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None)
        )
        session['aes_key'] = b64.b64encode(aes_key).decode()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

CRYPTO_SKIP = ('/api/crypto-key', '/api/crypto-session')

@app.before_request
def decrypt_request():
    if not request.path.startswith('/api/') or request.path in CRYPTO_SKIP:
        return
    aes_b64 = session.get('aes_key')
    if not aes_b64:
        return
    if request.method in ('POST', 'PUT'):
        raw = request.get_json(silent=True)
        if raw and 'ct' in raw and 'nonce' in raw:
            try:
                key = b64.b64decode(aes_b64)
                nonce = b64.b64decode(raw['nonce'])
                ct = b64.b64decode(raw['ct'])
                plain = AESGCM(key).decrypt(nonce, ct, None)
                request._cached_json = (json.loads(plain), json.loads(plain))
            except Exception:
                return jsonify({"ok": False, "error": "Decryption failed"}), 400

@app.after_request
def encrypt_response(response):
    if not request.path.startswith('/api/') or request.path in CRYPTO_SKIP:
        return response
    aes_b64 = session.get('aes_key')
    if not aes_b64 or 'application/json' not in (response.content_type or ''):
        return response
    try:
        key = b64.b64decode(aes_b64)
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, response.get_data(), None)
        response.set_data(json.dumps({"ct": b64.b64encode(ct).decode(), "nonce": b64.b64encode(nonce).decode()}))
        response.content_type = 'application/json'
    except Exception:
        pass
    return response

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
NOVNC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates", "noVNC")
if platform.system() == "Windows":
    WEBSOCKIFY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "Scripts", "websockify.exe")
else:
    WEBSOCKIFY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "venv", "bin", "websockify")

DEFAULT_CONFIG = {
    "vnc": {
        "ip": None,
        "port": None,
        "wsport": 6080
    },
    "panel": {
        "ip": ["127.0.0.1"],
        "port": 8050
    },
    "security": {
        "safety_warning": True
    }
}

_websockify_proc = None


def ensure_config():
    if not os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CONFIG, f, indent=4)
        return DEFAULT_CONFIG
    try:
        with open(CONFIG_PATH, encoding="utf-8") as f:
            content = json.load(f)
        changed = False
        for key, val in DEFAULT_CONFIG.items():
            if key not in content:
                content[key] = val
                changed = True
            elif isinstance(val, dict):
                for k, v in val.items():
                    if k not in content[key]:
                        content[key][k] = v
                        changed = True
        if changed:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(content, f, indent=4)
        return content
    except Exception:
        return DEFAULT_CONFIG


def load_panel_config():
    cfg = ensure_config()
    panel = cfg.get("panel", {})
    ips = panel.get("ip", ["127.0.0.1"])
    port = panel.get("port", 8050)
    return ips, port


def load_security_config():
    cfg = ensure_config()
    sec = cfg.get("security", {})
    return sec.get("safety_warning", True)


@app.context_processor
def inject_safety_warning():
    show = load_security_config() and not request.is_secure
    return {"safety_warning": show}


@app.before_request
def check_ip():
    ips, _ = load_panel_config()
    if "0.0.0.0" in ips:
        return
    remote = request.remote_addr
    if remote in ips:
        return
    if remote and remote.startswith("::ffff:") and remote[7:] in ips:
        return
    if remote == "127.0.0.1" and "127.0.0.1" in ips:
        return
    if remote and remote.startswith("::1") and ("::1" in ips or "127.0.0.1" in ips):
        return
    abort(403)


def _cleanup_websockify():
    global _websockify_proc
    if _websockify_proc and _websockify_proc.poll() is None:
        _websockify_proc.terminate()
        try:
            _websockify_proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            _websockify_proc.kill()
    _websockify_proc = None


atexit.register(_cleanup_websockify)

TASKS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tasks.json")
_tasks_lock = threading.Lock()


def load_tasks():
    if not os.path.exists(TASKS_PATH):
        return {"tasks": []}
    try:
        with open(TASKS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"tasks": []}


def save_tasks(data):
    with open(TASKS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4, ensure_ascii=False)


def compute_next_run(task):
    now = datetime.datetime.now()
    t = task["type"]

    if t == "manual":
        return None

    if t == "once":
        try:
            dt = datetime.datetime(
                int(task["year"]), int(task["month"]), int(task["day"]),
                int(task["hour"]), int(task["minute"]), int(task["second"])
            )
            return dt if dt > now else None
        except Exception:
            return None

    elif t == "yearly":
        try:
            month = int(task["month"])
            day = int(task["day"])
            hour = int(task["hour"])
            minute = int(task["minute"])
            second = int(task["second"])
            this_yr = datetime.datetime(now.year, month, day, hour, minute, second)
            return this_yr if this_yr > now else this_yr.replace(year=now.year + 1)
        except Exception:
            return None

    elif t == "weekly":
        try:
            weekday = int(task["weekday"])
            hour = int(task["hour"])
            minute = int(task["minute"])
            second = int(task["second"])
            days_ahead = (weekday - now.weekday()) % 7
            if days_ahead == 0:
                cand = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
                if cand > now:
                    return cand
                days_ahead = 7
            return (now.replace(hour=hour, minute=minute, second=second, microsecond=0)
                    + datetime.timedelta(days=days_ahead))
        except Exception:
            return None

    elif t == "daily":
        try:
            hour = int(task["hour"])
            minute = int(task["minute"])
            second = int(task["second"])
            cand = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
            return cand if cand > now else cand + datetime.timedelta(days=1)
        except Exception:
            return None

    elif t == "countdown":
        try:
            seconds = int(task["countdown_seconds"])
            last = task.get("last_run")
            if last is not None:
                base = datetime.datetime.fromtimestamp(last)
            else:
                base = now
            nxt = base + datetime.timedelta(seconds=seconds)
            if nxt <= now:
                nxt = now + datetime.timedelta(seconds=seconds)
            return nxt
        except Exception:
            return None

    return None


def execute_task(task):
    try:
        subprocess.Popen(task["command"], shell=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def scheduler_loop():
    while True:
        time.sleep(1)
        try:
            with _tasks_lock:
                data = load_tasks()
                changed = False
                now_ts = time.time()
                to_remove = []
                for task in data["tasks"]:
                    if not task.get("enabled", True):
                        continue
                    if task.get("next_run") is None:
                        nr = compute_next_run(task)
                        if nr is not None:
                            task["next_run"] = nr.timestamp()
                            changed = True
                        continue
                    if task["next_run"] <= now_ts:
                        execute_task(task)
                        if task.get("auto_delete") and task["type"] == "once":
                            to_remove.append(task)
                        else:
                            task["last_run"] = now_ts
                            nr = compute_next_run(task)
                            task["next_run"] = nr.timestamp() if nr is not None else None
                            if task["type"] == "once":
                                task["enabled"] = False
                        changed = True
                if to_remove:
                    data["tasks"] = [t for t in data["tasks"] if t not in to_remove]
                if changed:
                    save_tasks(data)
        except Exception:
            pass


_scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    _scheduler_thread.start()


def load_vnc_config():
    cfg = ensure_config()
    vnc = cfg.get("vnc", {})
    ip = vnc.get("ip")
    port = vnc.get("port")
    wsport = vnc.get("wsport", 6080)
    return ip, port, wsport


def validate_vnc_config():
    ip, port, wsport = load_vnc_config()
    errors = []
    ip_empty = ip is None or (isinstance(ip, str) and ip.strip() == "")
    port_empty = port is None
    if ip_empty and port_empty:
        errors.append("此计算机未开启远程连接功能")
        return ip, port, wsport, errors
    if ip_empty:
        errors.append("VNC IP 地址未设置")
    else:
        try:
            socket.getaddrinfo(str(ip), None)
        except (socket.gaierror, OSError):
            errors.append(f"无效的 IP 地址: {ip}")
    if port_empty:
        errors.append("VNC 端口未设置")
    else:
        try:
            port_num = int(port)
            if port_num < 1 or port_num > 65535:
                errors.append(f"无效的端口: {port}（端口范围 1-65535）")
        except (ValueError, TypeError):
            errors.append(f"无效的端口: {port}")
    if wsport is not None:
        try:
            wsport_num = int(wsport)
            if wsport_num < 1 or wsport_num > 65535:
                errors.append(f"无效的 WebSocket 端口: {wsport}（端口范围 1-65535）")
        except (ValueError, TypeError):
            errors.append(f"无效的 WebSocket 端口: {wsport}")
    return ip, port, wsport, errors


def start_websockify(ip, port, wsport):
    global _websockify_proc
    if _websockify_proc and _websockify_proc.poll() is None:
        return True
    try:
        _websockify_proc = subprocess.Popen(
            [WEBSOCKIFY, "--web", NOVNC_DIR, str(wsport), f"{ip}:{port}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        time.sleep(0.5)
        return _websockify_proc.poll() is None
    except Exception:
        _websockify_proc = None
        return False

def get_sys_info():
    cpu_percent = psutil.cpu_percent(interval=0.5)

    system = platform.system()
    if system == "Windows":
        os_name = f"Windows {platform.version()}"
    elif system == "Linux":
        os_name = "Linux"
        try:
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        os_name = line.split("=", 1)[1].strip().strip('"')
                        break
        except Exception:
            pass
    else:
        os_name = f"{system} {platform.release()}"

    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    boot = psutil.boot_time()
    uptime_sec = time.time() - boot

    days = int(uptime_sec // 86400)
    hours = int((uptime_sec % 86400) // 3600)
    mins = int((uptime_sec % 3600) // 60)
    uptime_str = f"{days}天 {hours}时 {mins}分"

    cpu_freq = psutil.cpu_freq()
    freq_current = round(cpu_freq.current) if cpu_freq else 0

    return {
        "system": {
            "os": os_name,
            "machine": platform.machine(),
            "user": getpass.getuser(),
            "hostname": platform.node(),
        },
        "cpu": {
            "percent": cpu_percent,
            "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(logical=True),
            "freq": freq_current,
        },
        "mem": {
            "total": round(mem.total / (1024**3), 2),
            "used": round(mem.used / (1024**3), 2),
            "percent": mem.percent,
        },
        "disk": {
            "total": round(disk.total / (1024**3), 2),
            "used": round(disk.used / (1024**3), 2),
            "percent": disk.percent,
        },
        "net": {
            "sent": round(net.bytes_sent / (1024**2), 2),
            "recv": round(net.bytes_recv / (1024**2), 2),
        },
        "uptime": uptime_str,
        "processes": len(psutil.pids()),
    }


@app.route("/")
def index():
    return render_template("hub.html")


@app.route("/monitor")
def monitor():
    return render_template("monitor.html")


@app.route("/processes")
def processes():
    return render_template("processes.html")


@app.route("/tasks")
def tasks():
    return render_template("tasks.html")


@app.route("/api/tasks")
def api_tasks():
    with _tasks_lock:
        data = load_tasks()
        result = []
        for t in data["tasks"]:
            item = dict(t)
            if item.get("next_run"):
                item["next_run_iso"] = datetime.datetime.fromtimestamp(item["next_run"]).isoformat()
            if item.get("last_run"):
                item["last_run_iso"] = datetime.datetime.fromtimestamp(item["last_run"]).isoformat()
            result.append(item)
        return jsonify({"tasks": result})


@app.route("/api/tasks", methods=["POST"])
def api_create_task():
    body = request.get_json(force=True)
    task = {
        "id": str(uuid.uuid4()),
        "name": body.get("name", ""),
        "command": body.get("command", ""),
        "type": body.get("type", "once"),
        "year": body.get("year"),
        "month": body.get("month"),
        "day": body.get("day"),
        "weekday": body.get("weekday"),
        "hour": body.get("hour", 0),
        "minute": body.get("minute", 0),
        "second": body.get("second", 0),
        "countdown_seconds": body.get("countdown_seconds", 60),
        "auto_delete": body.get("auto_delete", False),
        "enabled": True,
        "last_run": None,
        "next_run": None,
    }
    nr = compute_next_run(task)
    if nr is not None:
        task["next_run"] = nr.timestamp()
    with _tasks_lock:
        data = load_tasks()
        data["tasks"].append(task)
        save_tasks(data)
    return jsonify({"ok": True, "task": task})


@app.route("/api/tasks/<task_id>/delete", methods=["POST"])
def api_delete_task(task_id):
    with _tasks_lock:
        data = load_tasks()
        data["tasks"] = [t for t in data["tasks"] if t["id"] != task_id]
        save_tasks(data)
    return jsonify({"ok": True})


@app.route("/api/tasks/<task_id>/toggle", methods=["POST"])
def api_toggle_task(task_id):
    with _tasks_lock:
        data = load_tasks()
        for t in data["tasks"]:
            if t["id"] == task_id:
                t["enabled"] = not t.get("enabled", True)
                if t["enabled"] and t.get("next_run") is None:
                    nr = compute_next_run(t)
                    if nr is not None:
                        t["next_run"] = nr.timestamp()
                save_tasks(data)
                return jsonify({"ok": True, "enabled": t["enabled"]})
    return jsonify({"ok": False}), 404


@app.route("/api/tasks/<task_id>/update", methods=["PUT"])
def api_update_task(task_id):
    body = request.get_json(force=True)
    with _tasks_lock:
        data = load_tasks()
        for t in data["tasks"]:
            if t["id"] != task_id:
                continue
            t["name"] = body.get("name", t.get("name", ""))
            t["command"] = body.get("command", t.get("command", ""))
            t["type"] = body.get("type", t.get("type", "once"))
            t["year"] = body.get("year", t.get("year"))
            t["month"] = body.get("month", t.get("month"))
            t["day"] = body.get("day", t.get("day"))
            t["weekday"] = body.get("weekday", t.get("weekday"))
            t["hour"] = body.get("hour", t.get("hour", 0))
            t["minute"] = body.get("minute", t.get("minute", 0))
            t["second"] = body.get("second", t.get("second", 0))
            t["countdown_seconds"] = body.get("countdown_seconds", t.get("countdown_seconds", 60))
            t["auto_delete"] = body.get("auto_delete", t.get("auto_delete", False))
            nr = compute_next_run(t)
            t["next_run"] = nr.timestamp() if nr is not None else None
            if t["type"] == "once" and t["next_run"] is None:
                t["enabled"] = False
            save_tasks(data)
            return jsonify({"ok": True, "task": t})
    return jsonify({"ok": False}), 404


@app.route("/api/tasks/<task_id>/run", methods=["POST"])
def api_run_task(task_id):
    with _tasks_lock:
        data = load_tasks()
        for t in data["tasks"]:
            if t["id"] != task_id:
                continue
            execute_task(t)
            t["last_run"] = time.time()
            save_tasks(data)
            return jsonify({"ok": True, "message": "任务已执行"})
    return jsonify({"ok": False}), 404


@app.route("/api/info")
def api_info():
    return jsonify(get_sys_info())


@app.route("/api/processes")
def api_processes():
    sort_key = request.args.get("sort", "cpu")
    sort_dir = request.args.get("dir", "desc")
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "status", "username"]):
        try:
            info = p.info
            procs.append({
                "pid": info["pid"],
                "name": info["name"] or "-",
                "cpu": round(info["cpu_percent"] or 0, 1),
                "mem": round(info["memory_percent"] or 0, 1),
                "status": info["status"],
                "user": info["username"] or "-",
            })
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    reverse = sort_dir == "desc"
    procs.sort(key=lambda x: x.get(sort_key, 0) if sort_key != "name" else x[sort_key].lower(), reverse=reverse)
    return jsonify({"processes": procs, "total": len(procs)})


@app.route("/api/processes/<int:pid>/kill", methods=["POST"])
def api_kill_process(pid):
    try:
        p = psutil.Process(pid)
        p.terminate()
        return jsonify({"ok": True, "message": f"已终止进程 {pid}"})
    except psutil.NoSuchProcess:
        return jsonify({"ok": False, "message": "进程不存在"}), 404
    except psutil.AccessDenied:
        return jsonify({"ok": False, "message": "权限不足"}), 403
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route("/api/files/drives")
def api_file_drives():
    drives = []
    if platform.system() == "Windows":
        import string
        for letter in string.ascii_uppercase:
            path = letter + ":\\"
            if os.path.exists(path):
                try:
                    usage = psutil.disk_usage(path)
                    drives.append({"name": letter + ":", "path": path, "total": usage.total, "used": usage.used, "free": usage.free, "percent": usage.percent, "type": "logical"})
                except:
                    drives.append({"name": letter + ":", "path": path, "type": "logical"})
        # Physical disks via wmic
        try:
            import subprocess
            result = subprocess.run(["wmic", "diskdrive", "get", "size,model,deviceid", "/format:csv"], capture_output=True, text=True, timeout=5)
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                for line in lines[1:]:
                    parts = line.strip().split(",")
                    if len(parts) >= 4:
                        deviceid = parts[1]
                        model = parts[2]
                        size_str = parts[3]
                        try:
                            total = int(size_str)
                        except:
                            total = 0
                        m = re.search(r'PHYSICALDRIVE(\d+)', deviceid, re.IGNORECASE)
                        name = "磁盘 " + m.group(1) if m else deviceid
                        drives.append({"name": name, "path": deviceid, "total": total, "type": "physical"})
        except:
            pass
    else:
        seen = set()
        for part in psutil.disk_partitions():
            if part.device not in seen:
                seen.add(part.device)
                display = part.device.replace("/dev/", "")
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    drives.append({"name": display, "path": part.mountpoint, "total": usage.total, "used": usage.used, "free": usage.free, "percent": usage.percent, "type": "logical"})
                except:
                    drives.append({"name": display, "path": part.mountpoint, "type": "logical"})
        # Physical disks on Linux
        try:
            for entry in os.scandir("/sys/block"):
                if entry.is_dir():
                    dev = entry.name
                    if dev.startswith("sd") or dev.startswith("nvme") or dev.startswith("vd"):
                        try:
                            size_path = os.path.join("/sys/block", dev, "size")
                            if os.path.exists(size_path):
                                with open(size_path) as f:
                                    sectors = int(f.read().strip())
                                total = sectors * 512
                                drives.append({"name": "/dev/" + dev, "path": "/dev/" + dev, "total": total, "type": "physical"})
                        except:
                            pass
        except:
            pass
    return jsonify({"ok": True, "drives": drives})


@app.route("/api/files/download")
def api_file_download():
    path = request.args.get("path", "")
    if not path or not os.path.exists(path):
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    if os.path.isdir(path):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(path):
                for fn in files:
                    fpath = os.path.join(root, fn)
                    arcname = os.path.relpath(fpath, os.path.dirname(path))
                    try:
                        zf.write(fpath, arcname)
                    except PermissionError:
                        continue
                for dn in dirs:
                    dpath = os.path.join(root, dn)
                    arcname = os.path.relpath(dpath, os.path.dirname(path)) + '/'
                    try:
                        zf.write(dpath, arcname)
                    except PermissionError:
                        continue
        data.seek(0)
        return send_file(data, download_name=os.path.basename(path) + '.zip', as_attachment=True)
    try:
        dirname = os.path.dirname(path)
        filename = os.path.basename(path)
        return send_from_directory(dirname, filename, as_attachment=True)
    except PermissionError:
        return jsonify({"ok": False, "error": "权限不足"}), 403


@app.route("/vnc")
def vnc():
    ip, port, wsport, errors = validate_vnc_config()
    if errors:
        return render_template("vnc.html", errors=errors, ip=ip, port=port, wsport=wsport, connected=False)
    if not start_websockify(ip, port, wsport):
        return render_template("vnc.html", errors=["无法启动 websockify 代理，请检查配置"], ip=ip, port=port, wsport=wsport, connected=False)
    host = request.host.split(":")[0]
    return redirect(f"http://{host}:{wsport}/vnc.html?host={host}&port={wsport}&autoconnect=true&view_only=false&scale=true")


@app.route("/novnc/<path:filename>")
def serve_novnc(filename):
    return send_from_directory(NOVNC_DIR, filename)


@app.route("/files")
def file_explorer():
    return render_template("files.html")


def format_size(bytes_val):
    if bytes_val is None:
        return "-"
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}" if unit != "B" else f"{bytes_val} B"
        bytes_val /= 1024
    return f"{bytes_val:.1f} PB"


def file_type_label(name, is_dir):
    if is_dir:
        return "文件夹" if platform.system() == "Windows" else "directory"
    ext = os.path.splitext(name)[1].lower() if "." in name else ""
    if not ext:
        return "文件" if platform.system() == "Windows" else "file"
    return ext[1:].upper() + " 文件"


def list_dir(path):
    try:
        entries = []
        for entry in os.scandir(path):
            try:
                st = entry.stat()
                is_dir = entry.is_dir(follow_symlinks=False)
                info = {
                    "name": entry.name,
                    "is_dir": is_dir,
                    "size": st.st_size if not is_dir else None,
                    "modified": datetime.datetime.fromtimestamp(st.st_mtime).isoformat(),
                    "type": file_type_label(entry.name, is_dir),
                }
                if platform.system() != "Windows":
                    mode = st.st_mode
                    info["permission"] = stat.filemode(mode)
                entries.append(info)
            except (OSError, PermissionError):
                continue
        entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return entries, None
    except PermissionError:
        return None, "权限不足"
    except FileNotFoundError:
        return None, "路径不存在"
    except OSError as e:
        return None, str(e)


@app.route("/api/files")
def api_files():
    path = request.args.get("path", "")
    if not path:
        path = "/" if platform.system() != "Windows" else os.environ.get("SYSTEMDRIVE", "C:") + "\\"
    entries, err = list_dir(path)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "entries": entries, "path": os.path.abspath(path)})


@app.route("/api/files/delete", methods=["POST"])
def api_file_delete():
    path = request.get_json(force=True).get("path", "")
    if not path:
        return jsonify({"ok": False, "error": "路径为空"}), 400
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return jsonify({"ok": True})
    except PermissionError:
        return jsonify({"ok": False, "error": "权限不足"}), 403
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "文件不存在"}), 404
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/files/rename", methods=["POST"])
def api_file_rename():
    body = request.get_json(force=True)
    old_path = body.get("path", "")
    new_name = body.get("name", "")
    if not old_path or not new_name:
        return jsonify({"ok": False, "error": "参数不完整"}), 400
    try:
        parent = os.path.dirname(old_path)
        new_path = os.path.join(parent, new_name)
        if os.path.exists(new_path):
            return jsonify({"ok": False, "error": "目标已存在"}), 409
        os.rename(old_path, new_path)
        return jsonify({"ok": True})
    except PermissionError:
        return jsonify({"ok": False, "error": "权限不足"}), 403
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/files/mkdir", methods=["POST"])
def api_file_mkdir():
    parent = request.get_json(force=True).get("path", "")
    name = request.get_json(force=True).get("name", "")
    if not parent or not name:
        return jsonify({"ok": False, "error": "参数不完整"}), 400
    try:
        new_path = os.path.join(parent, name)
        os.makedirs(new_path, exist_ok=False)
        return jsonify({"ok": True})
    except FileExistsError:
        return jsonify({"ok": False, "error": "目录已存在"}), 409
    except PermissionError:
        return jsonify({"ok": False, "error": "权限不足"}), 403
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/files/create", methods=["POST"])
def api_file_create():
    parent = request.get_json(force=True).get("path", "")
    name = request.get_json(force=True).get("name", "")
    if not parent or not name:
        return jsonify({"ok": False, "error": "参数不完整"}), 400
    try:
        new_path = os.path.join(parent, name)
        if os.path.exists(new_path):
            return jsonify({"ok": False, "error": "文件已存在"}), 409
        open(new_path, 'w').close()
        return jsonify({"ok": True})
    except PermissionError:
        return jsonify({"ok": False, "error": "权限不足"}), 403
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/files/upload", methods=["POST"])
def api_file_upload():
    parent = request.form.get("path", "")
    is_dir = request.form.get("isDir", "0") == "1"
    if not parent:
        return jsonify({"ok": False, "error": "参数不完整"}), 400
    files = request.files.getlist("files")
    if not files:
        return jsonify({"ok": False, "error": "没有文件"}), 400
    try:
        for file in files:
            if is_dir and file.filename:
                # Preserve relative directory structure
                rel_path = file.filename
                dest = os.path.join(parent, rel_path)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                file.save(dest)
            else:
                dest = os.path.join(parent, file.filename)
                file.save(dest)
        return jsonify({"ok": True})
    except PermissionError:
        return jsonify({"ok": False, "error": "权限不足"}), 403
    except OSError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    ips, panel_port = load_panel_config()
    app.run(host="0.0.0.0", port=panel_port, debug=True)
