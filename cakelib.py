"""
Cake 客户端通信库
提供简单的 API 用于连接 Cake 服务器、发送消息、管理群组等功能
"""

import socket
import threading
import struct
import sys
from typing import Optional, Union, Callable, List, Dict, Any
from dataclasses import dataclass
import time

# 常量定义
CAKE_CLIENT_HOST = "127.0.0.1"
CAKE_CLIENT_PORT = 9966
CAKE_BUFFER_SIZE = 4096
CAKE_ID_LENGTH = 8
CAKE_SERVER_RESERVED_ID = b'\x00' * CAKE_ID_LENGTH
CAKE_BROADCAST_ID = b'\xff' * CAKE_ID_LENGTH
CAKE_PACKET_HEARTBEAT = 0x04
CAKE_PACKET_ID_REQUEST = 0x01
CAKE_PACKET_ID_RESPONSE = 0x02
CAKE_PACKET_BUSINESS = 0x03
CAKE_PACKET_GROUP_REGISTER = 0x05
CAKE_PACKET_GROUP_BUSINESS = 0x06
CAKE_PACKET_GROUP_RESPONSE = 0x07
CAKE_PACKET_GROUP_UNREGISTER = 0x08

# 全局状态
@dataclass
class _CakeState:
    socket: Optional[Any] = None  # Use Any to avoid type expression error
    client_id: Optional[bytes] = None
    stop_event: threading.Event = threading.Event()
    callback: Optional[Callable[[Dict[str, Any]], None]] = None
    recv_thread: Optional[threading.Thread] = None
    heartbeat_thread: Optional[threading.Thread] = None
    group_id_map: Dict[str, bytes] = None
    response_queue: Dict[str, Any] = None
    response_lock: threading.Lock = threading.Lock()

# 初始化全局状态
_state = _CakeState(
    group_id_map={},
    response_queue={}
)

def _cake_format_id(id_bytes: bytes) -> str:
    """将8字节ID转换为格式化字符串"""
    return ':'.join(f'{b:02x}' for b in id_bytes)

def _cake_parse_id_string(id_str: str) -> Optional[bytes]:
    """将格式化的ID字符串转换为8字节bytes"""
    try:
        parts = id_str.strip().split(':')
        if len(parts) != 8:
            return None
        id_bytes = bytes(int(part, 16) for part in parts)
        return id_bytes
    except:
        return None

def _cake_create_packet(packet_type: int, body: bytes) -> bytes:
    """创建数据包"""
    header = struct.pack('!BI', packet_type, len(body))
    return header + body

def _cake_parse_packet(data: bytes) -> Optional[tuple]:
    """解析数据包"""
    if len(data) < 5:
        return None
    packet_type = data[0]
    body_length = struct.unpack('!I', data[1:5])[0]
    if len(data) < 5 + body_length:
        return None
    body = data[5:5+body_length]
    return (packet_type, body)

def _receive_handler():
    """接收服务器消息的线程"""
    recv_buffer = b''
    while not _state.stop_event.is_set():
        try:
            if not _state.socket:
                break
            
            recv_data = _state.socket.recv(CAKE_BUFFER_SIZE)
            if not recv_data:
                _state.stop_event.set()
                break
            
            recv_buffer += recv_data
            
            # 解析数据包
            while len(recv_buffer) >= 5:
                packet_info = _cake_parse_packet(recv_buffer)
                if not packet_info:
                    break
                
                packet_type, body = packet_info
                packet_total_length = 5 + len(body)
                
                # 处理ID响应
                if packet_type == CAKE_PACKET_ID_RESPONSE:
                    _state.client_id = body[:CAKE_ID_LENGTH]
                    with _state.response_lock:
                        _state.response_queue['id_response'] = _cake_format_id(_state.client_id)
                
                # 处理心跳响应
                elif packet_type == CAKE_PACKET_HEARTBEAT:
                    pass
                
                # 处理群组响应
                elif packet_type == CAKE_PACKET_GROUP_RESPONSE:
                    group_id = body[:CAKE_ID_LENGTH]
                    group_id_str = _cake_format_id(group_id)
                    _state.group_id_map[group_id_str] = group_id
                    with _state.response_lock:
                        _state.response_queue['group_register'] = group_id_str
                
                # 处理业务消息
                elif packet_type == CAKE_PACKET_BUSINESS:
                    if len(body) < 16:
                        recv_buffer = recv_buffer[packet_total_length:]
                        continue
                    
                    src_id = body[:8]
                    dest_id = body[8:16]
                    message = body[16:]
                    
                    # 处理列表响应
                    if src_id == CAKE_SERVER_RESERVED_ID and message.startswith(b'list:'):
                        online_ids = message.decode().split(':', 1)[1].split(',')
                        with _state.response_lock:
                            _state.response_queue['online_list'] = online_ids
                    elif src_id == CAKE_SERVER_RESERVED_ID and message.startswith(b'grouplist:'):
                        group_info = message.decode().split(':', 1)[1]
                        with _state.response_lock:
                            _state.response_queue['group_list'] = group_info
                    else:
                        # 调用回调函数
                        if _state.callback:
                            try:
                                msg_data = {
                                    'type': 'private' if dest_id != CAKE_BROADCAST_ID else 'broadcast',
                                    'source_id': _cake_format_id(src_id),
                                    'target_id': _cake_format_id(dest_id),
                                    'data': message,
                                    'text': message.decode('utf-8', errors='ignore')
                                }
                                _state.callback(msg_data)
                            except Exception:
                                pass
                
                # 处理群组消息
                elif packet_type == CAKE_PACKET_GROUP_BUSINESS:
                    if len(body) < 16:
                        recv_buffer = recv_buffer[packet_total_length:]
                        continue
                    
                    src_id = body[:8]
                    group_id = body[8:16]
                    message = body[16:]
                    
                    if _state.callback:
                        try:
                            msg_data = {
                                'type': 'group',
                                'source_id': _cake_format_id(src_id),
                                'group_id': _cake_format_id(group_id),
                                'data': message,
                                'text': message.decode('utf-8', errors='ignore')
                            }
                            _state.callback(msg_data)
                        except Exception:
                            pass
                
                # 移除已处理的数据包
                recv_buffer = recv_buffer[packet_total_length:]
        
        except Exception:
            if not _state.stop_event.is_set():
                break

def _send_heartbeat():
    """发送心跳包"""
    while not _state.stop_event.is_set():
        try:
            if _state.socket and _state.client_id:
                heartbeat_packet = _cake_create_packet(CAKE_PACKET_HEARTBEAT, b'')
                _state.socket.sendall(heartbeat_packet)
            time.sleep(5.0)
        except:
            break

def _wait_for_response(key: str, timeout: float = 5.0) -> Any:
    """等待响应"""
    start_time = time.time()
    while time.time() - start_time < timeout:
        with _state.response_lock:
            if key in _state.response_queue:
                return _state.response_queue.pop(key)
        time.sleep(0.1)
    return None

# 公开API
def connect(server_addr: str = "127.0.0.1:9966") -> bool:
    """
    连接到Cake服务器
    
    Args:
        server_addr: 服务器地址，格式为 "host:port"
    
    Returns:
        bool: 连接成功返回True，失败返回False
    """
    # 清理之前的状态
    close()
    
    try:
        host, port = server_addr.split(':')
        port = int(port)
    except:
        host = CAKE_CLIENT_HOST
        port = CAKE_CLIENT_PORT
    
    try:
        # 创建socket
        _state.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        _state.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        _state.socket.connect((host, port))
        _state.stop_event.clear()
        
        # 发送ID请求
        id_request_packet = _cake_create_packet(CAKE_PACKET_ID_REQUEST, b'')
        _state.socket.sendall(id_request_packet)
        
        # 启动接收线程
        _state.recv_thread = threading.Thread(target=_receive_handler, daemon=True)
        _state.recv_thread.start()
        
        # 启动心跳线程
        _state.heartbeat_thread = threading.Thread(target=_send_heartbeat, daemon=True)
        _state.heartbeat_thread.start()
        
        # 等待ID响应
        client_id = _wait_for_response('id_response', 10.0)
        return client_id is not None
        
    except Exception:
        close()
        return False

def send(target_id: str, message: Union[str, bytes]) -> bool:
    """
    发送消息给指定ID的客户端
    
    Args:
        target_id: 目标客户端ID（格式化字符串）
        message: 要发送的消息（字符串或字节）
    
    Returns:
        bool: 发送成功返回True，失败返回False
    """
    if not _state.socket or not _state.client_id:
        return False
    
    try:
        # 解析目标ID
        target_id_bytes = _cake_parse_id_string(target_id)
        if not target_id_bytes:
            return False
        
        # 处理消息数据
        if isinstance(message, str):
            message_bytes = message.encode('utf-8')
        else:
            message_bytes = message
        
        # 构造数据包
        body = _state.client_id + target_id_bytes + message_bytes
        packet = _cake_create_packet(CAKE_PACKET_BUSINESS, body)
        
        _state.socket.sendall(packet)
        return True
        
    except Exception:
        return False

def broadcast(message: Union[str, bytes]) -> bool:
    """
    广播消息给所有客户端
    
    Args:
        message: 要广播的消息（字符串或字节）
    
    Returns:
        bool: 发送成功返回True，失败返回False
    """
    return send(_cake_format_id(CAKE_BROADCAST_ID), message)

def getid() -> Optional[str]:
    """
    获取当前客户端的ID
    
    Returns:
        str: 格式化的客户端ID，未连接返回None
    """
    if _state.client_id:
        return _cake_format_id(_state.client_id)
    return None

# 别名
get_id = getid

def set_callback(callback: Callable[[Dict[str, Any]], None]) -> None:
    """
    设置消息接收回调函数
    
    Args:
        callback: 回调函数，接收一个字典参数，包含消息类型、来源、内容等信息
    """
    _state.callback = callback

def close() -> None:
    """关闭连接"""
    _state.stop_event.set()
    
    # 关闭socket
    if _state.socket:
        try:
            _state.socket.close()
        except:
            pass
        _state.socket = None
    
    # 重置状态
    _state.client_id = None
    _state.group_id_map.clear()
    with _state.response_lock:
        _state.response_queue.clear()

def registergroup(member_ids: List[str] = None) -> Optional[str]:
    """
    注册群组
    
    Args:
        member_ids: 初始成员ID列表（可选）
    
    Returns:
        str: 新注册的群组ID，失败返回None
    """
    if not _state.socket or not _state.client_id:
        return None
    
    try:
        # 发送群组注册请求
        packet = _cake_create_packet(CAKE_PACKET_GROUP_REGISTER, b'')
        _state.socket.sendall(packet)
        
        # 等待群组ID响应
        group_id = _wait_for_response('group_register', 10.0)
        if not group_id:
            return None
        
        # 添加初始成员
        if member_ids and len(member_ids) > 0:
            member_ids_str = ','.join(member_ids)
            message = f"{group_id} add {member_ids_str}"
            body = _state.client_id + CAKE_SERVER_RESERVED_ID + message.encode('utf-8')
            packet = _cake_create_packet(CAKE_PACKET_BUSINESS, body)
            _state.socket.sendall(packet)
        
        return group_id
        
    except Exception:
        return None

def groupsend(group_id: str, data: bytes) -> bool:
    """
    发送二进制数据到群组
    
    Args:
        group_id: 群组ID（格式化字符串）
        data: 要发送的二进制数据
    
    Returns:
        bool: 发送成功返回True，失败返回False
    """
    if not _state.socket or not _state.client_id:
        return False
    
    try:
        # 解析群组ID
        group_id_bytes = _cake_parse_id_string(group_id)
        if not group_id_bytes:
            return False
        
        # 构造数据包
        body = _state.client_id + group_id_bytes + data
        packet = _cake_create_packet(CAKE_PACKET_GROUP_BUSINESS, body)
        
        _state.socket.sendall(packet)
        return True
        
    except Exception:
        return False

# 别名
group_send = groupsend

def groupsendtext(group_id: str, text: str) -> bool:
    """
    发送文本消息到群组
    
    Args:
        group_id: 群组ID（格式化字符串）
        text: 要发送的文本消息
    
    Returns:
        bool: 发送成功返回True，失败返回False
    """
    return groupsend(group_id, text.encode('utf-8'))

# 别名
group_send_text = groupsendtext

def unregistergroup(group_id: str) -> bool:
    """
    注销群组
    
    Args:
        group_id: 要注销的群组ID
    
    Returns:
        bool: 注销成功返回True，失败返回False
    """
    if not _state.socket or not _state.client_id:
        return False
    
    try:
        # 解析群组ID
        group_id_bytes = _cake_parse_id_string(group_id)
        if not group_id_bytes:
            return False
        
        # 构造数据包
        packet = _cake_create_packet(CAKE_PACKET_GROUP_UNREGISTER, group_id_bytes)
        _state.socket.sendall(packet)
        
        # 从本地缓存移除
        if group_id in _state.group_id_map:
            del _state.group_id_map[group_id]
        
        return True
        
    except Exception:
        return False

# 别名
unregister_group = unregistergroup

def grouplist() -> Optional[str]:
    """
    获取当前客户端注册的群组列表
    
    Returns:
        str: 群组列表信息，未连接返回None
    """
    if not _state.socket or not _state.client_id:
        return None
    
    try:
        # 发送群组列表请求
        body = _state.client_id + CAKE_SERVER_RESERVED_ID + b"grouplist"
        packet = _cake_create_packet(CAKE_PACKET_BUSINESS, body)
        _state.socket.sendall(packet)
        
        # 等待响应
        return _wait_for_response('group_list', 10.0)
        
    except Exception:
        return None

# 别名
group_list = grouplist

def list() -> Optional[List[str]]:
    """
    获取所有在线客户端ID列表
    
    Returns:
        List[str]: 在线客户端ID列表，未连接返回None
    """
    if not _state.socket or not _state.client_id:
        return None
    
    try:
        # 发送列表请求
        body = _state.client_id + CAKE_SERVER_RESERVED_ID + b"list"
        packet = _cake_create_packet(CAKE_PACKET_BUSINESS, body)
        _state.socket.sendall(packet)
        
        # 等待响应
        return _wait_for_response('online_list', 10.0)
        
    except Exception:
        return None

# 别名
online_list = list

# 清理函数
def __del__():
    """析构函数，确保关闭连接"""
    close()

# 导出的API列表
__all__ = [
    'connect', 'send', 'broadcast', 'getid', 'get_id',
    'set_callback', 'close', 'registergroup', 'groupsend',
    'group_send', 'groupsendtext', 'group_send_text',
    'unregistergroup', 'unregister_group', 'grouplist',
    'group_list', 'list', 'online_list'
]
