import socket
import threading
import struct
import json
import sys
from typing import Optional

# 客户端常量定义
CAKE_CLIENT_HOST = "127.0.0.1"  # 服务器地址
CAKE_CLIENT_PORT = 9966
CAKE_BUFFER_SIZE = 4096
CAKE_ID_LENGTH = 8
CAKE_SERVER_RESERVED_ID = b'\x00' * CAKE_ID_LENGTH
CAKE_BROADCAST_ID = b'\xff' * CAKE_ID_LENGTH
CAKE_PACKET_HEARTBEAT = 0x04    # 心跳包类型
CAKE_PACKET_ID_REQUEST = 0x01   # ID请求包类型
CAKE_PACKET_ID_RESPONSE = 0x02  # ID响应包类型
CAKE_PACKET_BUSINESS = 0x03     # 业务消息包类型
# 群组相关常量
CAKE_PACKET_GROUP_REGISTER = 0x05   # 注册群组包类型
CAKE_PACKET_GROUP_BUSINESS = 0x06   # 群组业务消息包类型
CAKE_PACKET_GROUP_RESPONSE = 0x07   # 群组ID响应包类型
CAKE_PACKET_GROUP_UNREGISTER = 0x08 # 注销群组包类型

# 全局变量
client_socket: Optional[socket.socket] = None
client_id: Optional[bytes] = None
stop_event = threading.Event()

def cake_format_id(id_bytes: bytes) -> str:
    """将8字节ID转换为格式化字符串（xx:xx:xx:xx:xx:xx:xx:xx）"""
    return ':'.join(f'{b:02x}' for b in id_bytes)

def cake_parse_id_string(id_str: str) -> Optional[bytes]:
    """将格式化的ID字符串转换为8字节bytes"""
    try:
        parts = id_str.strip().split(':')
        if len(parts) != 8:
            return None
        id_bytes = bytes(int(part, 16) for part in parts)
        return id_bytes
    except:
        return None

def cake_create_packet(packet_type: int, body: bytes) -> bytes:
    """创建数据包：包头(类型1字节 + 长度4字节) + 包体"""
    header = struct.pack('!BI', packet_type, len(body))
    return header + body

def cake_parse_packet(data: bytes) -> Optional[tuple]:
    """解析数据包，返回(包类型, 数据体)，不完整返回None"""
    if len(data) < 5:
        return None
    packet_type = data[0]
    body_length = struct.unpack('!I', data[1:5])[0]
    if len(data) < 5 + body_length:
        return None
    body = data[5:5+body_length]
    return (packet_type, body)

def cake_receive_handler():
    """接收服务器消息的独立线程"""
    recv_buffer = b''
    while not stop_event.is_set():
        try:
            if not client_socket:
                break
            
            recv_data = client_socket.recv(CAKE_BUFFER_SIZE)
            if not recv_data:
                print("\n❌ 与服务器断开连接")
                stop_event.set()
                break
            
            recv_buffer += recv_data
            
            # 循环解析完整数据包
            while len(recv_buffer) >= 5:
                packet_info = cake_parse_packet(recv_buffer)
                if not packet_info:
                    break
                
                packet_type, body = packet_info
                packet_total_length = 5 + len(body)
                
                # 处理ID响应
                if packet_type == CAKE_PACKET_ID_RESPONSE:
                    global client_id
                    client_id = body[:CAKE_ID_LENGTH]
                    print(f"\n✅ 已连接服务器，分配的客户端ID: {cake_format_id(client_id)}")
                
                # 处理心跳响应
                elif packet_type == CAKE_PACKET_HEARTBEAT:
                    pass  # 心跳包无需显示
                
                # 处理群组响应
                elif packet_type == CAKE_PACKET_GROUP_RESPONSE:
                    group_id = body[:CAKE_ID_LENGTH]
                    print(f"\n✅ 群组注册成功，群组ID: {cake_format_id(group_id)}")
                
                # 处理业务消息（服务器响应/点对点/广播）
                elif packet_type == CAKE_PACKET_BUSINESS:
                    if len(body) < 16:
                        print("\n❌ 收到格式错误的业务消息")
                        recv_buffer = recv_buffer[packet_total_length:]
                        continue
                    
                    src_id = body[:8]
                    dest_id = body[8:16]
                    message = body[16:].decode('utf-8', errors='ignore')
                    
                    src_id_str = cake_format_id(src_id)
                    dest_id_str = cake_format_id(dest_id)
                    
                    # 服务器响应（源ID为保留ID）
                    if src_id == CAKE_SERVER_RESERVED_ID:
                        print(f"\n📩 服务器响应: {message}")
                    # 广播消息
                    elif dest_id == CAKE_BROADCAST_ID:
                        print(f"\n📢 广播消息 (来自 {src_id_str}): {message}")
                    # 点对点消息
                    else:
                        print(f"\n📨 私信消息 (来自 {src_id_str}): {message}")
                
                # 处理群组消息
                elif packet_type == CAKE_PACKET_GROUP_BUSINESS:
                    if len(body) < 16:
                        print("\n❌ 收到格式错误的群组消息")
                        recv_buffer = recv_buffer[packet_total_length:]
                        continue
                    
                    src_id = body[:8]
                    group_id = body[8:16]
                    message = body[16:].decode('utf-8', errors='ignore')
                    
                    src_id_str = cake_format_id(src_id)
                    group_id_str = cake_format_id(group_id)
                    print(f"\n👥 群组消息 (群组 {group_id_str}, 来自 {src_id_str}): {message}")
                
                # 移除已处理的数据包
                recv_buffer = recv_buffer[packet_total_length:]
        
        except Exception as e:
            if not stop_event.is_set():
                print(f"\n❌ 接收消息异常: {e}")
            break

def cake_send_heartbeat():
    """发送心跳包的线程"""
    while not stop_event.is_set():
        try:
            if client_socket and client_id:
                # 发送心跳包（包体为空）
                heartbeat_packet = cake_create_packet(CAKE_PACKET_HEARTBEAT, b'')
                client_socket.sendall(heartbeat_packet)
            # 每5秒发送一次心跳
            threading.Event().wait(5.0)
        except:
            break

def cake_handle_command(command: str):
    """处理客户端指令"""
    if not client_socket or not client_id:
        print("❌ 未连接到服务器")
        return
    
    command_parts = command.strip().split(maxsplit=2)
    if not command_parts:
        return
    
    cmd = command_parts[0].lower()
    
    # 发送点对点/广播消息
    if cmd == "send":
        if len(command_parts) < 3:
            print("❌ 用法: send <目标ID> <消息> (broadcast表示广播)")
            return
        
        target_id_str = command_parts[1]
        message = command_parts[2]
        
        # 广播消息
        if target_id_str.lower() == "broadcast":
            target_id = CAKE_BROADCAST_ID
        # 服务器指令（保留ID）
        elif target_id_str == cake_format_id(CAKE_SERVER_RESERVED_ID):
            target_id = CAKE_SERVER_RESERVED_ID
        # 点对点消息
        else:
            target_id = cake_parse_id_string(target_id_str)
            if not target_id:
                print("❌ 目标ID格式错误（应为xx:xx:xx:xx:xx:xx:xx:xx）")
                return
        
        # 构造业务包体：源ID + 目标ID + 消息
        body = client_id + target_id + message.encode('utf-8')
        packet = cake_create_packet(CAKE_PACKET_BUSINESS, body)
        
        try:
            client_socket.sendall(packet)
            print(f"✅ 消息发送成功 - 目标: {cake_format_id(target_id)}, 内容: {message}")
        except Exception as e:
            print(f"❌ 消息发送失败: {e}")
    
    # 查看在线客户端列表
    elif cmd == "list":
        # 发送list指令到服务器保留ID
        body = client_id + CAKE_SERVER_RESERVED_ID + b"list"
        packet = cake_create_packet(CAKE_PACKET_BUSINESS, body)
        try:
            client_socket.sendall(packet)
            print("✅ 已发送在线列表查询请求，等待服务器响应...")
        except Exception as e:
            print(f"❌ 请求发送失败: {e}")
    
    # 注册群组
    elif cmd == "group_register":
        # 发送群组注册包（包体为空）
        packet = cake_create_packet(CAKE_PACKET_GROUP_REGISTER, b'')
        try:
            client_socket.sendall(packet)
            print("✅ 已发送群组注册请求，等待服务器响应...")
        except Exception as e:
            print(f"❌ 群组注册请求失败: {e}")
    
    # 向群组添加成员
    elif cmd == "group_add":
        if len(command_parts) < 3:
            print("❌ 用法: group_add <群组ID> <成员ID列表> (成员ID用逗号分隔)")
            return
        
        group_id_str = command_parts[1]
        member_ids_str = command_parts[2]
        
        group_id = cake_parse_id_string(group_id_str)
        if not group_id:
            print("❌ 群组ID格式错误")
            return
        
        # 构造添加指令消息
        message = f"{group_id_str} add {member_ids_str}"
        body = client_id + CAKE_SERVER_RESERVED_ID + message.encode('utf-8')
        packet = cake_create_packet(CAKE_PACKET_BUSINESS, body)
        
        try:
            client_socket.sendall(packet)
            print(f"✅ 已发送添加群成员请求 - 群组: {group_id_str}, 成员: {member_ids_str}")
        except Exception as e:
            print(f"❌ 添加群成员请求失败: {e}")
    
    # 从群组删除成员
    elif cmd == "group_del":
        if len(command_parts) < 3:
            print("❌ 用法: group_del <群组ID> <成员ID列表> (成员ID用逗号分隔)")
            return
        
        group_id_str = command_parts[1]
        member_ids_str = command_parts[2]
        
        group_id = cake_parse_id_string(group_id_str)
        if not group_id:
            print("❌ 群组ID格式错误")
            return
        
        # 构造删除指令消息
        message = f"{group_id_str} del {member_ids_str}"
        body = client_id + CAKE_SERVER_RESERVED_ID + message.encode('utf-8')
        packet = cake_create_packet(CAKE_PACKET_BUSINESS, body)
        
        try:
            client_socket.sendall(packet)
            print(f"✅ 已发送删除群成员请求 - 群组: {group_id_str}, 成员: {member_ids_str}")
        except Exception as e:
            print(f"❌ 删除群成员请求失败: {e}")
    
    # 发送群组消息
    elif cmd == "group_send":
        if len(command_parts) < 3:
            print("❌ 用法: group_send <群组ID> <消息>")
            return
        
        group_id_str = command_parts[1]
        message = command_parts[2]
        
        group_id = cake_parse_id_string(group_id_str)
        if not group_id:
            print("❌ 群组ID格式错误")
            return
        
        # 构造群组业务包体：源ID + 群组ID + 消息
        body = client_id + group_id + message.encode('utf-8')
        packet = cake_create_packet(CAKE_PACKET_GROUP_BUSINESS, body)
        
        try:
            client_socket.sendall(packet)
            print(f"✅ 群组消息发送成功 - 群组: {group_id_str}, 内容: {message}")
        except Exception as e:
            print(f"❌ 群组消息发送失败: {e}")
    
    # 查看自己创建的群组列表
    elif cmd == "group_list":
        # 发送grouplist指令到服务器保留ID
        body = client_id + CAKE_SERVER_RESERVED_ID + b"grouplist"
        packet = cake_create_packet(CAKE_PACKET_BUSINESS, body)
        try:
            client_socket.sendall(packet)
            print("✅ 已发送群组列表查询请求，等待服务器响应...")
        except Exception as e:
            print(f"❌ 请求发送失败: {e}")
    
    # 注销群组
    elif cmd == "group_unregister":
        if len(command_parts) < 2:
            print("❌ 用法: group_unregister <群组ID>")
            return
        
        group_id_str = command_parts[1]
        group_id = cake_parse_id_string(group_id_str)
        if not group_id:
            print("❌ 群组ID格式错误")
            return
        
        # 构造群组注销包体：群组ID
        packet = cake_create_packet(CAKE_PACKET_GROUP_UNREGISTER, group_id)
        try:
            client_socket.sendall(packet)
            print(f"✅ 已发送群组注销请求 - 群组: {group_id_str}")
        except Exception as e:
            print(f"❌ 群组注销请求失败: {e}")
    
    # 退出客户端
    elif cmd == "exit":
        print("👋 正在退出客户端...")
        stop_event.set()
        return
    
    else:
        print("❌ 未知指令，请输入以下指令：")
        print("  send <目标ID> <消息>        - 发送点对点消息（broadcast表示广播）")
        print("  list                        - 查看所有在线客户端ID")
        print("  group_register              - 注册新群组（无初始成员）")
        print("  group_add <群组ID> <成员ID> - 向群组添加成员（逗号分隔）")
        print("  group_del <群组ID> <成员ID> - 从群组删除成员（逗号分隔）")
        print("  group_send <群组ID> <消息>  - 发送群组消息")
        print("  group_list                  - 查看自己创建的群组及成员")
        print("  group_unregister <群组ID>   - 注销群组")
        print("  exit                        - 退出客户端")

def cake_start_client():
    """启动Cake客户端"""
    global client_socket
    
    # 创建客户端socket
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        # 连接服务器
        print(f"🔌 正在连接服务器 {CAKE_CLIENT_HOST}:{CAKE_CLIENT_PORT}...")
        client_socket.connect((CAKE_CLIENT_HOST, CAKE_CLIENT_PORT))
        print("✅ 连接服务器成功")
        
        # 发送ID请求
        id_request_packet = cake_create_packet(CAKE_PACKET_ID_REQUEST, b'')
        client_socket.sendall(id_request_packet)
        
        # 启动接收线程
        recv_thread = threading.Thread(target=cake_receive_handler, daemon=True)
        recv_thread.start()
        
        # 启动心跳线程
        heartbeat_thread = threading.Thread(target=cake_send_heartbeat, daemon=True)
        heartbeat_thread.start()
        
        # 显示帮助信息
        print("\n===== Cake客户端（完全适配服务端） =====")
        print("基础功能:")
        print("  send <目标ID> <消息>        - 发送点对点消息（broadcast表示广播）")
        print("  list                        - 查看所有在线客户端ID")
        print("群组功能:")
        print("  group_register              - 注册新群组（无初始成员）")
        print("  group_add <群组ID> <成员ID> - 向群组添加成员（逗号分隔）")
        print("  group_del <群组ID> <成员ID> - 从群组删除成员（逗号分隔）")
        print("  group_send <群组ID> <消息>  - 发送群组消息")
        print("  group_list                  - 查看自己创建的群组及成员")
        print("  group_unregister <群组ID>   - 注销群组")
        print("其他:")
        print("  exit                        - 退出客户端")
        print("="*50)
        
        # 指令输入循环
        while not stop_event.is_set():
            try:
                command = input("> ").strip()
                if command:
                    cake_handle_command(command)
                    if command.lower() == "exit":
                        break
            except KeyboardInterrupt:
                print("\n👋 接收到退出信号，正在退出...")
                stop_event.set()
                break
            except EOFError:
                break
    
    except ConnectionRefusedError:
        print("❌ 连接服务器失败，请确认服务器是否已启动")
    except Exception as e:
        print(f"❌ 客户端异常: {e}")
    finally:
        # 清理资源
        stop_event.set()
        if client_socket:
            try:
                client_socket.close()
            except:
                pass
        print("✅ 客户端已退出")

if __name__ == "__main__":
    cake_start_client()
