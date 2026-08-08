#!/usr/bin/env python3
import argparse
import base64
import datetime
import hashlib
import hmac
import os
import re
import sqlite3
import sys

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account.db")
PBKDF2_ITERATIONS = 200000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,32}$")


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users ("
        " username TEXT PRIMARY KEY,"
        " password_hash TEXT NOT NULL,"
        " created_at TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def hash_password(password, salt=None, iterations=PBKDF2_ITERATIONS):
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "$pbkdf2${0}${1}${2}".format(
        iterations,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password, stored):
    try:
        parts = stored.split("$")
        if len(parts) != 5 or parts[1] != "pbkdf2":
            return False
        iterations = int(parts[2])
        salt = base64.b64decode(parts[3])
        expected = base64.b64decode(parts[4])
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def add_user(username, password):
    if not USERNAME_RE.match(username or ""):
        raise ValueError("用户名无效（仅允许字母、数字、下划线、点、短横线，长度 1-32）")
    if not password:
        raise ValueError("密码不能为空")
    conn = _connect()
    try:
        if conn.execute("SELECT 1 FROM users WHERE username=?", (username,)).fetchone():
            raise ValueError("用户 {0} 已存在".format(username))
        conn.execute(
            "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
            (username, hash_password(password), datetime.datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()
    finally:
        conn.close()


def remove_user(username):
    conn = _connect()
    try:
        cur = conn.execute("DELETE FROM users WHERE username=?", (username,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def verify_user(username, password):
    if not username or not password:
        return False
    if not os.path.exists(DB_PATH):
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            row = conn.execute(
                "SELECT password_hash FROM users WHERE username=?", (username,)
            ).fetchone()
        finally:
            conn.close()
    except Exception:
        return False
    if not row:
        return False
    return verify_password(password, row[0])


def list_users():
    conn = _connect()
    try:
        return conn.execute(
            "SELECT username, created_at FROM users ORDER BY username"
        ).fetchall()
    finally:
        conn.close()


def count_users():
    if not os.path.exists(DB_PATH):
        return 0
    conn = _connect()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="pam.py", description="Panel Account Manager - Cake 面板账户管理工具"
    )
    sub = parser.add_subparsers(dest="command")

    p_add = sub.add_parser("add", help="添加用户")
    p_add.add_argument("username", help="用户名")
    p_add.add_argument("password", help="密码")

    p_rm = sub.add_parser("remove", help="删除用户及其密码")
    p_rm.add_argument("username", help="用户名")

    p_ls = sub.add_parser("list", help="列出所有用户")
    p_ls.add_argument("-v", "--verbose", action="store_true", help="同时显示创建时间")

    p_vf = sub.add_parser("verify", help="校验用户名和密码")
    p_vf.add_argument("username", help="用户名")
    p_vf.add_argument("password", nargs="?", default=None, help="密码，省略时从 stdin 读取")

    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 1

    if args.command == "add":
        try:
            add_user(args.username, args.password)
            print("用户 {0} 已添加".format(args.username))
            return 0
        except ValueError as e:
            print("错误：{0}".format(e))
            return 1

    if args.command == "remove":
        if remove_user(args.username):
            print("用户 {0} 已删除".format(args.username))
            return 0
        print("错误：用户 {0} 不存在".format(args.username))
        return 1

    if args.command == "list":
        users = list_users()
        if not users:
            print("暂无用户")
            return 0
        if args.verbose:
            for username, created in users:
                print("{0}\t{1}".format(username, created))
        else:
            for username, _ in users:
                print(username)
        return 0

    if args.command == "verify":
        password = args.password
        if password is None:
            password = sys.stdin.readline().rstrip("\n")
        if verify_user(args.username, password):
            print("校验通过")
            return 0
        print("校验失败")
        return 1

    return 1


if __name__ == "__main__":
    sys.exit(main())
