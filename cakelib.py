import socket
import threading
import struct
import time
import json
from typing import Optional, Union, Tuple, Any, List, Dict

# 全局常量
BUFFER_SIZE = 4096
ID_LENGTH = 8
BROADCAST_ID = b'\xff' * ID_LENGTH
SERVER_RESERVED_ID = b'\x00' * ID_LENGTH  # Cake服务器保留ID

# 心跳配置
HEARTBEAT_INTERVAL = 5    # 每5秒发一次心跳
HEARTBEAT_TIMEOUT = 20    # 20秒没收到心跳回应则断连（大于HEARTBEAT_INTERVAL*3）
PACKET_HEARTBEAT = 0x04   # 心跳包类型
PACKET_ID_REQUEST = 0x01  # ID请求包类型
PACKET_ID_RESPONSE = 0x02 # ID响应包类型
PACKET_MESSAGE = 0x03     # 业务消息包类型
# 新增群组相关包类型
PACKET_GROUP_REGISTER = 0x05    # 注册群组包类型
PACKET_GROUP_RESPONSE = 0x07    # 群组ID响应包类型
PACKET_GROUP_MESSAGE = 0x06     # 群组消息包类型
PACKET_GROUP_UNREGISTER = 0x08  # 注销群组包类型

# 全局客户端实例
_global_client: Optional['_CakeClient'] = None


class _CakeClient:
    """内部客户端实现类，对外不暴露"""
    def __init__(self):
        self.server_host: str = ""
        self.server_port: int = 0
        self.client_socket: Optional[socket.socket] = None
        self.client_id: Optional[bytes] = None
        self.running = False
        self.recv_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.last_heartbeat_ack_time = time.time()
        self.message_callback = None  # 消息回调函数
        self.error_info: str = ""     # 错误信息存储
        
        # 新增：同步请求相关（用于grouplist/list等需要等待响应的操作）
        self.sync_response_lock = threading.Lock()
        self.sync_response_data = None
        self.sync_response_event = threading.Event()

    def connect(self, server_addr: str) -> Tuple[bool, str]:
        """
        连接服务器
        :param server_addr: 服务器地址，格式为 "ip:port" 或域名（如 "xxx.abc.xyz:9966"）
        :return: (是否成功, 消息/错误信息)
        """
        # 解析服务器地址
        try:
            if ':' in server_addr:
                host_port = server_addr.split(':', 1)
                self.server_host = host_port[0]
                self.server_port = int(host_port[1])
            else:
                # 默认端口9966
                self.server_host = server_addr
                self.server_port = 9966
        except ValueError:
            self.error_info = f"服务器地址格式错误: {server_addr}"
            return False, self.error_info

        try:
            # 创建socket
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.client_socket.settimeout(10)  # 连接阶段超时
            self.client_socket.connect((self.server_host, self.server_port))
            
            # 发送ID请求包
            id_request_packet = struct.pack('!BI', PACKET_ID_REQUEST, 0)
            self.client_socket.sendall(id_request_packet)
            
            # 接收ID响应包
            response_data = self.client_socket.recv(5 + ID_LENGTH)
            if len(response_data) < 5 + ID_LENGTH:
                self.error_info = "ID响应包不完整"
                return False, self.error_info
            
            # 解析ID
            packet_type, body_length = struct.unpack('!BI', response_data[:5])
            if packet_type != PACKET_ID_RESPONSE or body_length != ID_LENGTH:
                self.error_info = "无效的ID响应包"
                return False, self.error_info
            self.client_id = response_data[5:5+ID_LENGTH]
            
            # 取消recv超时
            self.client_socket.settimeout(None)
            
            # 启动线程
            self.running = True
            self.last_heartbeat_ack_time = time.time()
            self.recv_thread = threading.Thread(target=self._recv_messages)
            self.heartbeat_thread = threading.Thread(target=self._heartbeat_loop)
            self.recv_thread.daemon = True
            self.heartbeat_thread.daemon = True
            self.recv_thread.start()
            self.heartbeat_thread.start()
            
            return True, self.format_id(self.client_id)
        except Exception as e:
            self.error_info = f"连接失败: {str(e)}"
            self.close()
            return False, self.error_info

    def _send_heartbeat(self):
        """发送心跳包"""
        if not self.running or not self.client_socket:
            return
        try:
            heartbeat_packet = struct.pack('!BI', PACKET_HEARTBEAT, 0)
            self.client_socket.sendall(heartbeat_packet)
        except:
            pass

    def _heartbeat_loop(self):
        """心跳循环：定时发送+超时检测"""
        while self.running:
            time.sleep(HEARTBEAT_INTERVAL)
            # 发送心跳
            self._send_heartbeat()
            # 检测超时
            elapsed = time.time() - self.last_heartbeat_ack_time
            if elapsed > HEARTBEAT_TIMEOUT:
                self.error_info = f"心跳超时（{HEARTBEAT_TIMEOUT}秒未收到回应）"
                self.close()
                break

    def _recv_messages(self):
        """接收消息（无超时，阻塞式）"""
        buffer = b''
        while self.running:
            try:
                recv_data = self.client_socket.recv(BUFFER_SIZE)
                if not recv_data:  # 服务器主动断开
                    self.error_info = "服务器主动断开连接"
                    break
                buffer += recv_data
                
                # 解析数据包
                while len(buffer) >= 5:
                    packet_type = buffer[0]
                    body_length = struct.unpack('!I', buffer[1:5])[0]
                    packet_total_length = 5 + body_length
                    
                    if len(buffer) < packet_total_length:
                        break  # 数据包不完整，等后续数据
                    
                    # 处理完整包
                    packet = buffer[:packet_total_length]
                    buffer = buffer[packet_total_length:]
                    
                    # 心跳回应
                    if packet_type == PACKET_HEARTBEAT:
                        self.last_heartbeat_ack_time = time.time()
                        continue
                    
                    # 业务消息
                    if packet_type == PACKET_MESSAGE:
                        body = packet[5:]
                        if len(body) >= 16:
                            src_id = body[:8]
                            dest_id = body[8:16]
                            message = body[16:]
                            src_id_str = self.format_id(src_id)
                            dest_id_str = self.format_id(dest_id)
                            
                            # 处理同步请求的响应（grouplist/list/groupadd/groupdel）
                            if src_id == SERVER_RESERVED_ID and dest_id == self.client_id:
                                with self.sync_response_lock:
                                    self.sync_response_data = message
                                    self.sync_response_event.set()
                                continue
                            
                            # 调用回调函数
                            if self.message_callback:
                                try:
                                    self.message_callback(src_id_str, dest_id_str, message)
                                except Exception as e:
                                    self.error_info = f"消息回调函数执行错误: {str(e)}"
                    
                    # 群组注册响应
                    elif packet_type == PACKET_GROUP_RESPONSE:
                        body = packet[5:]
                        if len(body) == ID_LENGTH:
                            with self.sync_response_lock:
                                self.sync_response_data = body  # 返回群组ID字节
                                self.sync_response_event.set()
            except Exception as e:
                if self.running:
                    self.error_info = f"接收消息异常: {str(e)}"
                break
        
        # 接收线程退出 = 连接断开
        if self.running:
            self.close()

    def send_message(self, target_id_str: str, message: Union[str, bytes]) -> Tuple[bool, str]:
        """
        发送消息
        :param target_id_str: 目标ID字符串（格式如 a1:b2:c3:d4:e5:f6:78:90）或 "broadcast"
        :param message: 要发送的消息（字符串或字节流）
        :return: (是否成功, 消息/错误信息)
        """
        if not self.running or not self.client_socket or not self.client_id:
            self.error_info = "未连接到服务器或未获取ID"
            return False, self.error_info
        
        # 解析目标ID
        if target_id_str.lower() == "broadcast":
            target_id = BROADCAST_ID
        else:
            try:
                target_id_parts = target_id_str.split(':')
                if len(target_id_parts) != 8:
                    self.error_info = "目标ID格式错误（需8组两位十六进制数）"
                    return False, self.error_info
                target_id = bytes(int(part, 16) for part in target_id_parts)
            except ValueError:
                self.error_info = "目标ID格式错误（非十六进制数）"
                return False, self.error_info
        
        # 处理消息数据
        if isinstance(message, str):
            message_bytes = message.encode('utf-8')
        else:
            message_bytes = message
        
        # 构造业务消息包
        body = self.client_id + target_id + message_bytes
        body_length = len(body)
        packet = struct.pack(f'!BI{body_length}s', PACKET_MESSAGE, body_length, body)
        
        # 发送
        try:
            self.client_socket.sendall(packet)
            return True, f"消息发送成功，内容长度: {len(message_bytes)} 字节"
        except Exception as e:
            self.error_info = f"消息发送失败: {str(e)}"
            self.close()
            return False, self.error_info

    # ------------------------------
    # 新增群组相关核心方法
    # ------------------------------
    def register_group(self, member_ids: List[str] = None) -> Tuple[Optional[str], str]:
        """
        注册群组（优化：支持空参数注册空群组）
        :param member_ids: 群组成员ID列表（字符串格式），不传/传空则注册空群组
        :return: (群组ID字符串/None, 错误信息/成功信息)
        """
        if not self.running or not self.client_socket or not self.client_id:
            return None, "未连接到服务器或未获取ID"
        
        # 处理空参数，注册空群组
        if member_ids is None:
            member_ids = []
        
        # 验证并转换成员ID为字节
        member_bytes_list = []
        for member_id_str in member_ids:
            try:
                parts = member_id_str.split(':')
                if len(parts) != 8:
                    return None, f"成员ID格式错误: {member_id_str}（需8组两位十六进制数）"
                member_bytes = bytes(int(part, 16) for part in parts)
                member_bytes_list.append(member_bytes)
            except ValueError:
                return None, f"成员ID格式错误: {member_id_str}（非十六进制数）"
        
        # 构造群组注册包体（成员ID拼接，空列表则包体长度为0）
        body = b''.join(member_bytes_list)
        body_length = len(body)
        packet = struct.pack(f'!BI{body_length}s', PACKET_GROUP_REGISTER, body_length, body)
        
        try:
            # 重置同步响应
            with self.sync_response_lock:
                self.sync_response_data = None
                self.sync_response_event.clear()
            
            # 发送注册包
            self.client_socket.sendall(packet)
            
            # 等待响应（超时10秒）
            if self.sync_response_event.wait(timeout=10):
                with self.sync_response_lock:
                    if self.sync_response_data and len(self.sync_response_data) == ID_LENGTH:
                        group_id_str = self.format_id(self.sync_response_data)
                        return group_id_str, f"群组注册成功，ID: {group_id_str}"
                    else:
                        return None, "未收到有效的群组ID响应"
            else:
                return None, "群组注册请求超时"
        except Exception as e:
            return None, f"群组注册失败: {str(e)}"

    def unregister_group(self, group_id_str: str) -> Tuple[bool, str]:
        """
        注销群组
        :param group_id_str: 群组ID字符串
        :return: (是否成功, 错误信息/成功信息)
        """
        if not self.running or not self.client_socket or not self.client_id:
            return False, "未连接到服务器或未获取ID"
        
        # 转换群组ID为字节
        try:
            parts = group_id_str.split(':')
            if len(parts) != 8:
                return False, "群组ID格式错误（需8组两位十六进制数）"
            group_id = bytes(int(part, 16) for part in parts)
        except ValueError:
            return False, f"群组ID格式错误: {group_id_str}（非十六进制数）"
        
        # 构造注销包
        body = group_id
        body_length = len(body)
        packet = struct.pack(f'!BI{body_length}s', PACKET_GROUP_UNREGISTER, body_length, body)
        
        try:
            self.client_socket.sendall(packet)
            return True, f"群组注销请求已发送: {group_id_str}"
        except Exception as e:
            return False, f"群组注销失败: {str(e)}"

    def group_send(self, group_id_str: str, data: bytes) -> Tuple[bool, str]:
        """
        发送二进制数据到群组
        :param group_id_str: 群组ID字符串
        :param data: 二进制数据
        :return: (是否成功, 错误信息/成功信息)
        """
        if not self.running or not self.client_socket or not self.client_id:
            return False, "未连接到服务器或未获取ID"
        
        # 转换群组ID为字节
        try:
            parts = group_id_str.split(':')
            if len(parts) != 8:
                return False, "群组ID格式错误（需8组两位十六进制数）"
            group_id = bytes(int(part, 16) for part in parts)
        except ValueError:
            return False, f"群组ID格式错误: {group_id_str}（非十六进制数）"
        
        # 构造群组消息包体（源ID + 群组ID + 数据）
        body = self.client_id + group_id + data
        body_length = len(body)
        packet = struct.pack(f'!BI{body_length}s', PACKET_GROUP_MESSAGE, body_length, body)
        
        try:
            self.client_socket.sendall(packet)
            return True, f"群组消息发送成功，数据长度: {len(data)} 字节"
        except Exception as e:
            return False, f"群组消息发送失败: {str(e)}"

    def group_send_text(self, group_id_str: str, text: str) -> Tuple[bool, str]:
        """
        发送文本消息到群组
        :param group_id_str: 群组ID字符串
        :param text: 文本字符串
        :return: (是否成功, 错误信息/成功信息)
        """
        try:
            data = text.encode('utf-8')
            return self.group_send(group_id_str, data)
        except Exception as e:
            return False, f"文本消息编码失败: {str(e)}"

    # ------------------------------
    # 新增：群组添加/删除成员核心方法
    # ------------------------------
    def group_add_members(self, group_id_str: str, member_ids: List[str]) -> Tuple[bool, str]:
        """
        向群组添加成员
        :param group_id_str: 群组ID字符串
        :param member_ids: 要添加的成员ID列表（字符串格式）
        :return: (是否成功, 错误信息/成功信息)
        """
        if not self.running or not self.client_socket or not self.client_id:
            return False, "未连接到服务器或未获取ID"
        
        # 验证群组ID格式
        try:
            parts = group_id_str.split(':')
            if len(parts) != 8:
                return False, "群组ID格式错误（需8组两位十六进制数）"
        except:
            return False, f"群组ID格式错误: {group_id_str}"
        
        # 验证成员ID格式并拼接成指令字符串
        member_str = ','.join([m.strip() for m in member_ids if m.strip()])
        if not member_str:
            return False, "成员列表不能为空"
        
        # 构造add指令
        cmd = f"{group_id_str} add {member_str}"
        
        try:
            # 重置同步响应
            with self.sync_response_lock:
                self.sync_response_data = None
                self.sync_response_event.clear()
            
            # 发送指令到服务器保留ID
            success, msg = self.send_message(self.format_id(SERVER_RESERVED_ID), cmd)
            if not success:
                return False, msg
            
            # 等待响应（超时10秒）
            if self.sync_response_event.wait(timeout=10):
                with self.sync_response_lock:
                    response = self.sync_response_data.decode('utf-8') if self.sync_response_data else ""
                    if response == "ok":
                        return True, f"成员添加成功，已向群组 {group_id_str} 添加 {len(member_ids)} 个成员"
                    elif response == "null":
                        return False, f"群组不存在: {group_id_str}"
                    else:
                        return False, f"添加成员失败，服务器响应: {response}"
            else:
                return False, "添加成员请求超时"
        except Exception as e:
            return False, f"添加成员失败: {str(e)}"

    def group_del_members(self, group_id_str: str, member_ids: List[str]) -> Tuple[bool, str]:
        """
        从群组删除成员
        :param group_id_str: 群组ID字符串
        :param member_ids: 要删除的成员ID列表（字符串格式）
        :return: (是否成功, 错误信息/成功信息)
        """
        if not self.running or not self.client_socket or not self.client_id:
            return False, "未连接到服务器或未获取ID"
        
        # 验证群组ID格式
        try:
            parts = group_id_str.split(':')
            if len(parts) != 8:
                return False, "群组ID格式错误（需8组两位十六进制数）"
        except:
            return False, f"群组ID格式错误: {group_id_str}"
        
        # 验证成员ID格式并拼接成指令字符串
        member_str = ','.join([m.strip() for m in member_ids if m.strip()])
        if not member_str:
            return False, "成员列表不能为空"
        
        # 构造del指令
        cmd = f"{group_id_str} del {member_str}"
        
        try:
            # 重置同步响应
            with self.sync_response_lock:
                self.sync_response_data = None
                self.sync_response_event.clear()
            
            # 发送指令到服务器保留ID
            success, msg = self.send_message(self.format_id(SERVER_RESERVED_ID), cmd)
            if not success:
                return False, msg
            
            # 等待响应（超时10秒）
            if self.sync_response_event.wait(timeout=10):
                with self.sync_response_lock:
                    response = self.sync_response_data.decode('utf-8') if self.sync_response_data else ""
                    if response == "ok":
                        return True, f"成员删除成功，已从群组 {group_id_str} 删除 {len(member_ids)} 个成员"
                    elif response == "null":
                        return False, f"群组不存在: {group_id_str}"
                    else:
                        return False, f"删除成员失败，服务器响应: {response}"
            else:
                return False, "删除成员请求超时"
        except Exception as e:
            return False, f"删除成员失败: {str(e)}"

    def get_group_list(self) -> Optional[Dict]:
        """
        获取当前客户端注册的群组列表
        :return: 群组字典（{群组ID: [成员ID列表]}）/None（无群组）
        """
        if not self.running or not self.client_socket or not self.client_id:
            return None
        
        # 发送grouplist请求
        success, msg = self.send_message(self.format_id(SERVER_RESERVED_ID), "grouplist")
        if not success:
            return None
        
        # 等待响应（超时10秒）
        with self.sync_response_lock:
            self.sync_response_data = None
            self.sync_response_event.clear()
        
        if not self.sync_response_event.wait(timeout=10):
            return None
        
        # 解析响应
        with self.sync_response_lock:
            response_data = self.sync_response_data
        
        if not response_data:
            return None
        
        try:
            # 解码JSON
            json_str = response_data.decode('utf-8')
            group_data = json.loads(json_str)
            return group_data if group_data is not None else None
        except json.JSONDecodeError:
            return None

    def get_online_id_list(self) -> List[str]:
        """
        获取所有在线客户端ID列表
        :return: ID字符串列表（空列表表示无在线客户端或请求失败）
        """
        if not self.running or not self.client_socket or not self.client_id:
            return []
        
        # 发送list请求
        success, msg = self.send_message(self.format_id(SERVER_RESERVED_ID), "list")
        if not success:
            return []
        
        # 等待响应（超时10秒）
        with self.sync_response_lock:
            self.sync_response_data = None
            self.sync_response_event.clear()
        
        if not self.sync_response_event.wait(timeout=10):
            return []
        
        # 解析响应
        with self.sync_response_lock:
            response_data = self.sync_response_data
        
        if not response_data:
            return []
        
        try:
            id_str = response_data.decode('utf-8').strip()
            if not id_str:
                return []
            # 按逗号分割ID列表
            id_list = [id_part.strip() for id_part in id_str.split(',') if id_part.strip()]
            return id_list
        except:
            return []

    def get_client_id(self) -> Tuple[Optional[str], str]:
        """
        获取客户端ID（字符串格式）
        :return: (客户端ID/None, 错误信息/空字符串)
        """
        if not self.client_id:
            self.error_info = "未获取到客户端ID"
            return None, self.error_info
        return self.format_id(self.client_id), ""

    def close(self) -> None:
        """关闭客户端"""
        if not self.running:
            return
        self.running = False
        # 关闭socket
        if self.client_socket:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
                self.client_socket.close()
            except:
                pass
        self.client_id = None

    @staticmethod
    def format_id(id_bytes: bytes) -> str:
        """将字节ID格式化为字符串"""
        return ':'.join(f'{b:02x}' for b in id_bytes)

    def set_message_callback(self, callback) -> None:
        """设置消息接收回调函数"""
        self.message_callback = callback


# ------------------------------
# 对外暴露的API接口
# ------------------------------
def connect(server_addr: str) -> Tuple[bool, str]:
    """
    连接到Cake服务器
    :param server_addr: 服务器地址，格式为 "ip:port" 或域名（如 "127.0.0.1:9966" 或 "xxx.abc.xyz"）
    :return: (是否成功, 消息/错误信息)
    """
    global _global_client
    if _global_client and _global_client.running:
        _global_client.close()
    
    _global_client = _CakeClient()
    return _global_client.connect(server_addr)


def send(target_id: str, message: Union[str, bytes]) -> Tuple[bool, str]:
    """
    发送消息给指定ID的客户端
    :param target_id: 目标客户端ID（格式如 a1:b2:c3:d4:e5:f6:78:90）
    :param message: 要发送的消息（字符串或字节流）
    :return: (是否成功, 消息/错误信息)
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return False, "未连接到服务器，请先调用connect()"
    return _global_client.send_message(target_id, message)


def broadcast(message: Union[str, bytes]) -> Tuple[bool, str]:
    """
    广播消息给所有客户端
    :param message: 要广播的消息（字符串或字节流）
    :return: (是否成功, 消息/错误信息)
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return False, "未连接到服务器，请先调用connect()"
    return _global_client.send_message("broadcast", message)


def getid() -> Tuple[Optional[str], str]:
    """
    获取当前客户端的ID
    :return: (客户端ID字符串/None, 错误信息/空字符串)
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return None, "未连接到服务器"
    return _global_client.get_client_id()


def set_callback(callback) -> None:
    """
    设置消息接收回调函数
    回调函数格式: callback(src_id: str, dest_id: str, message: bytes)
    """
    global _global_client
    if _global_client:
        _global_client.set_message_callback(callback)


def close() -> None:
    """关闭连接"""
    global _global_client
    if _global_client:
        _global_client.close()

# ------------------------------
# 新增群组相关API
# ------------------------------
def registergroup(member_ids: List[str] = None) -> Tuple[Optional[str], str]:
    """
    注册群组（支持空参数注册空群组）
    :param member_ids: 群组成员ID列表（字符串格式，如 ["11:11:11:11:11:11:11:11", ...]），不传则注册空群组
    :return: (群组ID字符串/None, 错误信息/成功信息)
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return None, "未连接到服务器，请先调用connect()"
    return _global_client.register_group(member_ids)


def groupsend(group_id: str, data: bytes) -> Tuple[bool, str]:
    """
    发送二进制数据到群组
    :param group_id: 群组ID字符串
    :param data: 二进制数据包
    :return: (是否成功, 错误信息/成功信息)
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return False, "未连接到服务器，请先调用connect()"
    return _global_client.group_send(group_id, data)


def groupsendtext(group_id: str, text: str) -> Tuple[bool, str]:
    """
    发送文本消息到群组
    :param group_id: 群组ID字符串
    :param text: 文本字符串
    :return: (是否成功, 错误信息/成功信息)
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return False, "未连接到服务器，请先调用connect()"
    return _global_client.group_send_text(group_id, text)


def unregistergroup(group_id: str) -> Tuple[bool, str]:
    """
    注销群组
    :param group_id: 群组ID字符串
    :return: (是否成功, 错误信息/成功信息)
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return False, "未连接到服务器，请先调用connect()"
    return _global_client.unregister_group(group_id)

# ------------------------------
# 新增：groupadd/groupdel 对外API
# ------------------------------
def groupadd(group_id: str, member_ids: List[str]) -> Tuple[bool, str]:
    """
    向群组添加成员
    :param group_id: 群组ID字符串
    :param member_ids: 要添加的成员ID列表（字符串格式）
    :return: (是否成功, 错误信息/成功信息)
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return False, "未连接到服务器，请先调用connect()"
    return _global_client.group_add_members(group_id, member_ids)


def groupdel(group_id: str, member_ids: List[str]) -> Tuple[bool, str]:
    """
    从群组删除成员
    :param group_id: 群组ID字符串
    :param member_ids: 要删除的成员ID列表（字符串格式）
    :return: (是否成功, 错误信息/成功信息)
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return False, "未连接到服务器，请先调用connect()"
    return _global_client.group_del_members(group_id, member_ids)

def grouplist() -> Optional[Dict]:
    """
    获取当前客户端注册的群组列表
    :return: 群组字典（{群组ID: [成员ID列表]}）/None（无群组或请求失败）
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return None
    return _global_client.get_group_list()


def list() -> List[str]:
    """
    获取所有在线客户端ID列表
    :return: ID字符串列表（空列表表示无在线客户端或请求失败）
    """
    global _global_client
    if not _global_client or not _global_client.running:
        return []
    return _global_client.get_online_id_list()

# 兼容别名
get_id = getid
group_send = groupsend
group_send_text = groupsendtext
unregister_group = unregistergroup
group_list = grouplist
online_list = list
group_add = groupadd  # 兼容驼峰命名
group_del = groupdel  # 兼容驼峰命名

# 模块导出
__all__ = [
    'connect', 'send', 'broadcast', 'getid', 'get_id', 'set_callback', 'close',
    'registergroup', 'groupsend', 'groupsendtext', 'unregistergroup', 'grouplist', 'list',
    'groupadd', 'groupdel',  # 新增导出
    'group_send', 'group_send_text', 'unregister_group', 'group_list', 'online_list',
    'group_add', 'group_del'  # 兼容别名导出
]
