import atexit
import json
import os
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
import psutil
from flask import Flask, jsonify, render_template, request, redirect, send_from_directory, abort

app = Flask(__name__)

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


if __name__ == "__main__":
    ips, panel_port = load_panel_config()
    app.run(host="0.0.0.0", port=panel_port, debug=True)
