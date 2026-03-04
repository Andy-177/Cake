import socket
import threading
import random
import struct
import json  # 用于JSON序列化
from typing import Dict, Optional, Set

# 全局常量定义（cake 服务器）
CAKE_SERVER_HOST = "0.0.0.0"
CAKE_SERVER_PORT = 9966
CAKE_BUFFER_SIZE = 4096
CAKE_ID_LENGTH = 8
CAKE_SERVER_RESERVED_ID = b'\x00' * CAKE_ID_LENGTH
CAKE_BROADCAST_ID = b'\xff' * CAKE_ID_LENGTH
CAKE_CONNECTION_TIMEOUT = 60.0  # 服务器超时时间（适配客户端5秒心跳）
CAKE_PACKET_HEARTBEAT = 0x04    # 心跳包类型
CAKE_PACKET_ID_REQUEST = 0x01   # ID请求包类型
CAKE_PACKET_ID_RESPONSE = 0x02  # ID响应包类型
CAKE_PACKET_BUSINESS = 0x03     # 业务消息包类型
# 群组相关常量
CAKE_PACKET_GROUP_REGISTER = 0x05   # 注册群组包类型
CAKE_PACKET_GROUP_BUSINESS = 0x06   # 群组业务消息包类型
CAKE_PACKET_GROUP_RESPONSE = 0x07   # 群组ID响应包类型
CAKE_PACKET_GROUP_UNREGISTER = 0x08 # 注销群组包类型

# 全局状态管理
cake_client_connections: Dict[bytes, socket.socket] = {}  # 客户端ID -> socket
cake_id_pool_lock = threading.Lock()

# 群组相关全局状态
cake_groups: Dict[bytes, Set[bytes]] = {}  # 群组ID -> 成员ID集合
cake_client_created_groups: Dict[bytes, Set[bytes]] = {}  # 客户端ID -> 该客户端创建的群组ID集合
cake_group_id_lock = threading.Lock()

def cake_generate_unique_id() -> bytes:
    """生成8字节唯一客户端ID（排除保留ID/广播ID/已存在ID）"""
    while True:
        new_id = bytes([random.randint(0x00, 0xff) for _ in range(CAKE_ID_LENGTH)])
        if new_id not in (CAKE_SERVER_RESERVED_ID, CAKE_BROADCAST_ID) and new_id not in cake_client_connections:
            return new_id

def cake_generate_unique_group_id() -> bytes:
    """生成8字节唯一群组ID（排除保留ID/广播ID/已存在群组ID）"""
    while True:
        new_group_id = bytes([random.randint(0x00, 0xff) for _ in range(CAKE_ID_LENGTH)])
        if new_group_id not in (CAKE_SERVER_RESERVED_ID, CAKE_BROADCAST_ID) and new_group_id not in cake_groups:
            return new_group_id

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

def cake_recycle_client_groups(client_id: bytes):
    """回收指定客户端创建的所有群组"""
    if not client_id:
        return
    
    with cake_group_id_lock:
        # 获取该客户端创建的所有群组ID
        client_created_group_ids = cake_client_created_groups.get(client_id, set())
        if not client_created_group_ids:
            return
        
        # 遍历并删除所有该客户端创建的群组
        recycled_count = 0
        for group_id in list(client_created_group_ids):  # 转列表避免迭代时修改集合
            if group_id in cake_groups:
                del cake_groups[group_id]
                recycled_count += 1
            # 从客户端创建的群组列表中移除
            if group_id in client_created_group_ids:
                client_created_group_ids.remove(group_id)
        
        # 若该客户端无剩余创建的群组，删除其在字典中的记录
        if not client_created_group_ids:
            del cake_client_created_groups[client_id]
        
        # 打印回收日志
        formatted_client_id = ':'.join(f'{b:02x}' for b in client_id)
        print(f"[Cake服务器] 客户端 {formatted_client_id} 下线，回收其创建的 {recycled_count} 个群组ID")

def cake_handle_client_connection(client_socket: socket.socket, client_address):
    """处理单个客户端连接"""
    client_id: Optional[bytes] = None
    print(f"[Cake服务器] 新客户端连接: {client_address}")
    
    try:
        client_socket.settimeout(CAKE_CONNECTION_TIMEOUT)
        recv_buffer = b''
        
        while True:
            try:
                recv_data = client_socket.recv(CAKE_BUFFER_SIZE)
                if not recv_data:  # 客户端主动关闭
                    print(f"[Cake服务器] 客户端 {client_address} 主动断开连接")
                    break
                
                recv_buffer += recv_data
                
                # 循环解析完整数据包
                while len(recv_buffer) >= 5:
                    packet_info = cake_parse_packet(recv_buffer)
                    if not packet_info:
                        break
                    
                    packet_type, body = packet_info
                    packet_total_length = 5 + len(body)
                    
                    # 处理ID请求
                    if packet_type == CAKE_PACKET_ID_REQUEST and client_id is None:
                        with cake_id_pool_lock:
                            client_id = cake_generate_unique_id()
                            cake_client_connections[client_id] = client_socket
                        # 发送ID响应
                        response_header = struct.pack('!BI', CAKE_PACKET_ID_RESPONSE, CAKE_ID_LENGTH)
                        response_packet = response_header + client_id
                        client_socket.sendall(response_packet)
                        formatted_id = ':'.join(f'{b:02x}' for b in client_id)
                        print(f"[Cake服务器] 为客户端 {client_address} 分配ID: {formatted_id}")
                    
                    # 处理业务消息（含grouplist、list指令）
                    elif packet_type == CAKE_PACKET_BUSINESS:
                        if client_id is None or len(body) < 16:
                            print(f"[Cake服务器] 客户端 {client_address} 业务消息格式错误/未分配ID")
                            break
                        
                        src_id = body[:8]
                        dest_id = body[8:16]
                        message = body[16:]
                        
                        if src_id != client_id:
                            print(f"[Cake服务器] 客户端 {client_address} 伪造源ID，拒绝处理")
                            break
                        
                        formatted_src_id = ':'.join(f'{b:02x}' for b in src_id)
                        formatted_dest_id = ':'.join(f'{b:02x}' for b in dest_id)
                        
                        # 处理grouplist指令
                        if dest_id == CAKE_SERVER_RESERVED_ID and message.decode('utf-8', errors='ignore').strip().lower() == "grouplist":
                            print(f"[Cake服务器] 客户端 {formatted_src_id} 请求查询已注册群组列表")
                            group_list_result = None
                            with cake_group_id_lock:
                                client_groups = cake_client_created_groups.get(client_id, set())
                                valid_groups = [gid for gid in client_groups if gid in cake_groups]
                                
                                if valid_groups:
                                    group_list_result = {}
                                    for group_id in valid_groups:
                                        group_id_str = ':'.join(f'{b:02x}' for b in group_id)
                                        members = cake_groups[group_id]
                                        member_str_list = [':'.join(f'{b:02x}' for b in mid) for mid in members]
                                        group_list_result[group_id_str] = member_str_list
                            
                            # 序列化JSON并发送响应
                            response_json = json.dumps(group_list_result, ensure_ascii=False)
                            response_msg_bytes = response_json.encode('utf-8')
                            response_body = CAKE_SERVER_RESERVED_ID + client_id + response_msg_bytes
                            response_body_length = len(response_body)
                            response_packet = struct.pack(f'!BI{response_body_length}s', CAKE_PACKET_BUSINESS, response_body_length, response_body)
                            client_socket.sendall(response_packet)
                            print(f"[Cake服务器] 已向客户端 {formatted_src_id} 返回群组列表: {response_json}")
                            recv_buffer = recv_buffer[packet_total_length:]
                            continue
                        
                        # 新增：处理list指令（返回所有在线客户端ID列表）
                        elif dest_id == CAKE_SERVER_RESERVED_ID and message.decode('utf-8', errors='ignore').strip().lower() == "list":
                            print(f"[Cake服务器] 客户端 {formatted_src_id} 请求查询所有在线客户端ID列表")
                            # 获取所有在线客户端ID并格式化
                            with cake_id_pool_lock:
                                # 过滤掉保留ID和广播ID（实际client_connections中不会包含这两个）
                                online_ids = []
                                for cid in cake_client_connections.keys():
                                    if cid not in (CAKE_SERVER_RESERVED_ID, CAKE_BROADCAST_ID):
                                        cid_str = ':'.join(f'{b:02x}' for b in cid)
                                        online_ids.append(cid_str)
                            # 拼接为逗号分隔的字符串
                            id_list_str = ','.join(online_ids) if online_ids else ""
                            response_msg_bytes = id_list_str.encode('utf-8')
                            # 构造响应包
                            response_body = CAKE_SERVER_RESERVED_ID + client_id + response_msg_bytes
                            response_body_length = len(response_body)
                            response_packet = struct.pack(f'!BI{response_body_length}s', CAKE_PACKET_BUSINESS, response_body_length, response_body)
                            # 发送响应
                            client_socket.sendall(response_packet)
                            print(f"[Cake服务器] 已向客户端 {formatted_src_id} 返回在线ID列表: {id_list_str}")
                            recv_buffer = recv_buffer[packet_total_length:]
                            continue
                        
                        # 广播消息处理
                        if dest_id == CAKE_BROADCAST_ID:
                            print(f"[Cake服务器] 客户端 {formatted_src_id} 广播消息: {message.decode('utf-8', errors='ignore')}")
                            with cake_id_pool_lock:
                                for target_id, target_socket in cake_client_connections.items():
                                    if target_id != client_id:
                                        try:
                                            target_socket.sendall(recv_buffer[:packet_total_length])
                                        except Exception as e:
                                            print(f"[Cake服务器] 广播给 {':'.join(f'{b:02x}' for b in target_id)} 失败: {e}")
                        # 点对点消息处理
                        else:
                            print(f"[Cake服务器] 客户端 {formatted_src_id} 发送给 {formatted_dest_id}: {message.decode('utf-8', errors='ignore')}")
                            with cake_id_pool_lock:
                                target_socket = cake_client_connections.get(dest_id)
                                if target_socket:
                                    try:
                                        target_socket.sendall(recv_buffer[:packet_total_length])
                                    except Exception as e:
                                        print(f"[Cake服务器] 发送给 {formatted_dest_id} 失败: {e}")
                                else:
                                    print(f"[Cake服务器] 目标客户端 {formatted_dest_id} 不存在")
                    
                    # 处理心跳包
                    elif packet_type == CAKE_PACKET_HEARTBEAT:
                        try:
                            client_socket.sendall(recv_buffer[:packet_total_length])
                        except Exception as e:
                            print(f"[Cake服务器] 客户端 {client_address} 心跳响应失败: {e}")
                            break
                    
                    # 处理群组注册
                    elif packet_type == CAKE_PACKET_GROUP_REGISTER:
                        if client_id is None or len(body) % CAKE_ID_LENGTH != 0:
                            print(f"[Cake服务器] 客户端 {client_address} 群组注册格式错误/未分配ID")
                            break
                        
                        # 解析并过滤有效成员ID
                        members = [body[i:i+CAKE_ID_LENGTH] for i in range(0, len(body), CAKE_ID_LENGTH)]
                        valid_members = set()
                        with cake_id_pool_lock:
                            for member_id in members:
                                if member_id not in (CAKE_SERVER_RESERVED_ID, CAKE_BROADCAST_ID) and member_id in cake_client_connections:
                                    valid_members.add(member_id)
                        
                        # 生成群组ID并存储
                        with cake_group_id_lock:
                            group_id = cake_generate_unique_group_id()
                            cake_groups[group_id] = valid_members
                            if client_id not in cake_client_created_groups:
                                cake_client_created_groups[client_id] = set()
                            cake_client_created_groups[client_id].add(group_id)
                        
                        # 发送群组ID响应
                        response_header = struct.pack('!BI', CAKE_PACKET_GROUP_RESPONSE, CAKE_ID_LENGTH)
                        response_packet = response_header + group_id
                        client_socket.sendall(response_packet)
                        formatted_group_id = ':'.join(f'{b:02x}' for b in group_id)
                        formatted_members = [':'.join(f'{b:02x}' for b in mid) for mid in valid_members]
                        print(f"[Cake服务器] 客户端 {client_address} 注册群组 {formatted_group_id}，成员: {formatted_members}")
                    
                    # 处理群组消息
                    elif packet_type == CAKE_PACKET_GROUP_BUSINESS:
                        if client_id is None or len(body) < 16:
                            print(f"[Cake服务器] 客户端 {client_address} 群组消息格式错误/未分配ID")
                            break
                        
                        src_id = body[:8]
                        group_id = body[8:16]
                        message = body[16:]
                        
                        if src_id != client_id or group_id not in cake_groups:
                            print(f"[Cake服务器] 客户端 {client_address} 伪造源ID/群组不存在，拒绝处理")
                            break
                        
                        # 发送给群组成员（排除发送者）
                        formatted_src_id = ':'.join(f'{b:02x}' for b in src_id)
                        formatted_group_id = ':'.join(f'{b:02x}' for b in group_id)
                        print(f"[Cake服务器] 客户端 {formatted_src_id} 发送群组({formatted_group_id})消息: {message.decode('utf-8', errors='ignore')}")
                        with cake_id_pool_lock:
                            for member_id in cake_groups[group_id]:
                                if member_id != client_id:
                                    target_socket = cake_client_connections.get(member_id)
                                    if target_socket:
                                        try:
                                            target_socket.sendall(recv_buffer[:packet_total_length])
                                        except Exception as e:
                                            print(f"[Cake服务器] 发送群组消息给 {':'.join(f'{b:02x}' for b in member_id)} 失败: {e}")
                    
                    # 处理群组注销
                    elif packet_type == CAKE_PACKET_GROUP_UNREGISTER:
                        if client_id is None or len(body) != CAKE_ID_LENGTH:
                            print(f"[Cake服务器] 客户端 {client_address} 群组注销格式错误/未分配ID")
                            break
                        
                        unreg_group_id = body[:CAKE_ID_LENGTH]
                        if unreg_group_id in (CAKE_SERVER_RESERVED_ID, CAKE_BROADCAST_ID):
                            print(f"[Cake服务器] 客户端 {client_address} 尝试注销保留群组ID，拒绝处理")
                            break
                        
                        # 注销群组
                        with cake_group_id_lock:
                            if unreg_group_id in cake_groups:
                                del cake_groups[unreg_group_id]
                                if client_id in cake_client_created_groups and unreg_group_id in cake_client_created_groups[client_id]:
                                    cake_client_created_groups[client_id].remove(unreg_group_id)
                                formatted_group_id = ':'.join(f'{b:02x}' for b in unreg_group_id)
                                print(f"[Cake服务器] 客户端 {client_address} 成功注销群组 {formatted_group_id}")
                            else:
                                print(f"[Cake服务器] 客户端 {client_address} 尝试注销不存在的群组 {':'.join(f'{b:02x}' for b in unreg_group_id)}")
                    
                    # 移除已处理的数据包
                    recv_buffer = recv_buffer[packet_total_length:]
            
            except socket.timeout:
                print(f"[Cake服务器] 客户端 {client_address} 空闲超时，断开连接")
                break
    
    except Exception as e:
        print(f"[Cake服务器] 客户端 {client_address} 处理异常: {e}")
    
    finally:
        # 清理客户端连接
        with cake_id_pool_lock:
            if client_id and client_id in cake_client_connections:
                del cake_client_connections[client_id]
                formatted_id = ':'.join(f'{b:02x}' for b in client_id) if client_id else '未知'
                print(f"[Cake服务器] 客户端 {client_address} (ID: {formatted_id}) 断开，释放ID")
        
        # 回收该客户端创建的所有群组
        cake_recycle_client_groups(client_id)
        
        # 关闭socket
        try:
            client_socket.close()
        except:
            pass

def cake_start_server():
    """启动Cake服务器"""
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    
    try:
        server_socket.bind((CAKE_SERVER_HOST, CAKE_SERVER_PORT))
        server_socket.listen(5)
        print(f"[Cake服务器] 启动成功，监听地址: {CAKE_SERVER_HOST}:{CAKE_SERVER_PORT}")
        print(f"[Cake服务器] 保留ID: {':'.join(f'{b:02x}' for b in CAKE_SERVER_RESERVED_ID)}")
        print(f"[Cake服务器] 广播ID: {':'.join(f'{b:02x}' for b in CAKE_BROADCAST_ID)}")
        
        while True:
            client_socket, client_address = server_socket.accept()
            client_thread = threading.Thread(
                target=cake_handle_client_connection,
                args=(client_socket, client_address)
            )
            client_thread.daemon = True
            client_thread.start()
    
    except KeyboardInterrupt:
        print("\n[Cake服务器] 接收到退出信号，正在关闭...")
    except Exception as e:
        print(f"[Cake服务器] 启动失败: {e}")
    finally:
        # 清理所有资源
        with cake_id_pool_lock:
            for sock in cake_client_connections.values():
                try:
                    sock.close()
                except:
                    pass
        with cake_group_id_lock:
            cake_groups.clear()
            cake_client_created_groups.clear()
        server_socket.close()
        print("[Cake服务器] 已完全关闭")

if __name__ == "__main__":
    cake_start_server()
