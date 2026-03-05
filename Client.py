import socket
import threading
import struct
import time
import sys
import json
from typing import Optional, List

# 全局常量
BUFFER_SIZE = 4096
ID_LENGTH = 8
SERVER_RESERVED_ID = b'\x00' * ID_LENGTH  # 服务器保留ID（全0）
BROADCAST_ID = b'\xff' * ID_LENGTH        # 广播ID（全ff）

# 心跳配置
HEARTBEAT_INTERVAL = 5    # 每5秒发一次心跳
HEARTBEAT_TIMEOUT = 20    # 20秒没收到心跳回应则断连（大于HEARTBEAT_INTERVAL*3）
PACKET_HEARTBEAT = 0x04   # 心跳包类型

# 数据包类型常量（与服务端完全对齐）
PACKET_ID_REQUEST = 0x01        # ID请求包类型
PACKET_ID_RESPONSE = 0x02       # ID响应包类型
PACKET_BUSINESS = 0x03          # 业务消息包类型
PACKET_GROUP_REGISTER = 0x05    # 注册群组包类型
PACKET_GROUP_BUSINESS = 0x06    # 群组业务消息包类型
PACKET_GROUP_RESPONSE = 0x07    # 群组ID响应包类型
PACKET_GROUP_UNREGISTER = 0x08  # 注销群组包类型

class CakeClient:
    def __init__(self, server_host: str, server_port: int):
        self.server_host = server_host
        self.server_port = server_port
        self.client_socket: Optional[socket.socket] = None
        self.client_id: Optional[bytes] = None
        self.running = False
        self.recv_thread: Optional[threading.Thread] = None
        self.heartbeat_thread: Optional[threading.Thread] = None
        self.last_heartbeat_ack_time = time.time()  # 最后一次收到心跳回应的时间
        
        # 群组相关存储
        self.registered_groups: List[str] = []  # 已注册的群组ID（字符串格式）
        self.last_registered_group_id: Optional[bytes] = None  # 临时存储注册返回的群组ID
        self.group_response_lock = threading.Lock()
        self.group_response_event = threading.Event()
        
        # 指令响应存储（用于同步获取add/del/list等指令的响应）
        self.cmd_response: Optional[str] = None
        self.cmd_response_lock = threading.Lock()
        self.cmd_response_event = threading.Event()

    def connect(self) -> bool:
        """连接服务器并获取ID"""
        try:
            # 创建socket（全程不设置recv超时，靠心跳检测存活）
            self.client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            # 仅连接阶段设置超时
            self.client_socket.settimeout(10)
            self.client_socket.connect((self.server_host, self.server_port))
            print(f"✅ 已连接到服务器 {self.server_host}:{self.server_port}")
            
            # 发送ID请求包（01 00 00 00 00）
            id_request_packet = struct.pack('!BI', PACKET_ID_REQUEST, 0)
            self.client_socket.sendall(id_request_packet)
            
            # 接收ID响应包
            response_data = self.client_socket.recv(5 + ID_LENGTH)
            if len(response_data) < 5 + ID_LENGTH:
                print("❌ ID响应包不完整")
                return False
            
            # 解析ID
            packet_type, body_length = struct.unpack('!BI', response_data[:5])
            if packet_type != PACKET_ID_RESPONSE or body_length != ID_LENGTH:
                print("❌ 无效的ID响应包")
                return False
            self.client_id = response_data[5:5+ID_LENGTH]
            print(f"✅ 获取到客户端ID: {self.format_id(self.client_id)}")
            
            # 取消recv超时（关键！避免recv timed out）
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
            
            return True
        except Exception as e:
            print(f"❌ 连接失败: {e}")
            self.close()
            return False

    def format_id(self, id_bytes: bytes) -> str:
        """将8字节ID转换为xx:xx:xx:xx:xx:xx:xx:xx格式的字符串"""
        return ':'.join(f'{b:02x}' for b in id_bytes)

    def parse_id(self, id_str: str) -> Optional[bytes]:
        """将xx:xx:xx:xx:xx:xx:xx:xx格式的字符串转换为8字节ID"""
        try:
            parts = id_str.strip().split(':')
            if len(parts) != 8:
                return None
            return bytes(int(part, 16) for part in parts)
        except (ValueError, TypeError):
            return None

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
                print(f"\n⚠️  心跳超时（{HEARTBEAT_TIMEOUT}秒未收到回应），断开连接")
                self.close()
                break

    def _recv_messages(self):
        """接收消息（无超时，阻塞式）"""
        buffer = b''
        while self.running:
            try:
                # 阻塞式recv（无超时），有数据才处理，没数据就等
                recv_data = self.client_socket.recv(BUFFER_SIZE)
                if not recv_data:  # 服务器主动断开
                    print("\n❌ 服务器主动断开连接")
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
                    
                    # 业务消息（点对点/广播/指令响应）
                    elif packet_type == PACKET_BUSINESS:
                        body = packet[5:]
                        if len(body) >= 16:
                            src_id = body[:8]
                            dest_id = body[8:16]
                            message = body[16:]
                            src_id_str = self.format_id(src_id)
                            dest_id_str = self.format_id(dest_id)
                            
                            # 区分普通消息和指令响应（目标是自己，来源是服务器保留ID）
                            if dest_id == self.client_id and src_id == SERVER_RESERVED_ID:
                                # 指令响应（list/grouplist/add/del）
                                with self.cmd_response_lock:
                                    self.cmd_response = message.decode('utf-8', errors='ignore')
                                self.cmd_response_event.set()
                            else:
                                # 普通点对点/广播消息
                                print(f"\n📩 收到消息 - 来源: {src_id_str}, 目标: {dest_id_str}, 内容: {message.decode('utf-8', errors='ignore')}")
                    
                    # 处理群组ID响应包（0x07）
                    elif packet_type == PACKET_GROUP_RESPONSE:
                        body = packet[5:]
                        if len(body) == ID_LENGTH:
                            group_id = body
                            group_id_str = self.format_id(group_id)
                            # 存储群组ID供后续使用
                            with self.group_response_lock:
                                self.last_registered_group_id = group_id
                                self.registered_groups.append(group_id_str)
                            # 触发事件通知注册函数
                            self.group_response_event.set()
                    
                    # 处理群组业务消息包（0x06）
                    elif packet_type == PACKET_GROUP_BUSINESS:
                        body = packet[5:]
                        if len(body) >= 16:
                            src_id = body[:8]
                            group_id = body[8:16]
                            message = body[16:]
                            src_id_str = self.format_id(src_id)
                            group_id_str = self.format_id(group_id)
                            print(f"\n📩 收到群组消息 - 来源: {src_id_str}, 群组: {group_id_str}, 内容: {message.decode('utf-8', errors='ignore')}")
            except Exception as e:
                if self.running:
                    print(f"\n❌ 接收消息异常: {e}")
                break
        
        # 接收线程退出 = 连接断开
        if self.running:
            self.close()
        print("\n🔌 与服务器的连接已断开")

    def send_business_cmd(self, cmd: str) -> Optional[str]:
        """
        向服务器保留ID发送业务指令（list/grouplist/add/del）
        :param cmd: 指令字符串（如"list"、"grouplist"、"xxx:xx:... add xx:xx:...")
        :return: 服务器响应内容，超时/失败返回None
        """
        if not self.running or not self.client_socket or not self.client_id:
            print("❌ 未连接到服务器或未获取ID")
            return None
        
        # 重置指令响应事件
        self.cmd_response_event.clear()
        with self.cmd_response_lock:
            self.cmd_response = None
        
        # 构造业务包（目标是服务器保留ID）
        cmd_bytes = cmd.encode('utf-8')
        body = self.client_id + SERVER_RESERVED_ID + cmd_bytes
        body_length = len(body)
        packet = struct.pack(f'!BI{body_length}s', PACKET_BUSINESS, body_length, body)
        
        # 发送指令
        try:
            self.client_socket.sendall(packet)
            # 等待服务器响应（超时10秒）
            if self.cmd_response_event.wait(timeout=10):
                with self.cmd_response_lock:
                    return self.cmd_response
            print("❌ 指令执行超时，未收到服务器响应")
            return None
        except Exception as e:
            print(f"❌ 指令发送失败: {e}")
            self.close()
            return None

    def send_message(self, target_id_str: str, message: str):
        """发送消息（点对点/广播）"""
        if not self.running or not self.client_socket or not self.client_id:
            print("❌ 未连接到服务器或未获取ID")
            return
        
        # 解析目标ID
        if target_id_str.lower() == "broadcast":
            target_id = BROADCAST_ID
        else:
            target_id = self.parse_id(target_id_str)
            if not target_id:
                print("❌ 目标ID格式错误（需8组两位十六进制数，如: a1:b2:c3:d4:e5:f6:78:90）")
                return
        
        # 构造业务消息包
        message_bytes = message.encode('utf-8')
        body = self.client_id + target_id + message_bytes
        body_length = len(body)
        packet = struct.pack(f'!BI{body_length}s', PACKET_BUSINESS, body_length, body)
        
        # 发送
        try:
            self.client_socket.sendall(packet)
            print(f"✅ 消息发送成功 - 目标: {target_id_str}, 内容: {message}")
        except Exception as e:
            print(f"❌ 消息发送失败: {e}")
            self.close()

    def register_group(self) -> Optional[str]:
        """
        极简注册群组（无包体，对应服务端05 00 00 00 00）
        :return: 生成的群组ID（字符串格式），失败返回None
        """
        if not self.running or not self.client_socket or not self.client_id:
            print("❌ 未连接到服务器或未获取ID")
            return None
        
        # 重置群组响应事件
        self.group_response_event.clear()
        with self.group_response_lock:
            self.last_registered_group_id = None
        
        # 构造无包体的群组注册包（05 00 00 00 00）
        packet = struct.pack('!BI', PACKET_GROUP_REGISTER, 0)
        
        # 发送注册包
        try:
            self.client_socket.sendall(packet)
            print("✅ 群组注册请求已发送（无初始成员）")
            # 等待服务器响应（超时10秒）
            if self.group_response_event.wait(timeout=10):
                with self.group_response_lock:
                    if self.last_registered_group_id:
                        return self.format_id(self.last_registered_group_id)
            print("❌ 群组注册超时，未收到服务器响应")
            return None
        except Exception as e:
            print(f"❌ 群组注册失败: {e}")
            self.close()
            return None

    def add_group_members(self, group_id_str: str, member_ids_str: List[str]) -> Optional[str]:
        """
        向群组添加成员
        :param group_id_str: 群组ID（字符串格式）
        :param member_ids_str: 要添加的成员ID列表（字符串格式）
        :return: 服务器响应（ok/null），失败返回None
        """
        # 构造add指令
        members = ','.join(member_ids_str)
        cmd = f"{group_id_str} add {members}"
        # 发送指令并获取响应
        return self.send_business_cmd(cmd)

    def del_group_members(self, group_id_str: str, member_ids_str: List[str]) -> Optional[str]:
        """
        从群组删除成员
        :param group_id_str: 群组ID（字符串格式）
        :param member_ids_str: 要删除的成员ID列表（字符串格式）
        :return: 服务器响应（ok/null），失败返回None
        """
        # 构造del指令
        members = ','.join(member_ids_str)
        cmd = f"{group_id_str} del {members}"
        # 发送指令并获取响应
        return self.send_business_cmd(cmd)

    def list_online_clients(self) -> Optional[List[str]]:
        """
        查询所有在线客户端ID
        :return: 在线ID列表，失败返回None
        """
        response = self.send_business_cmd("list")
        if not response:
            return None
        return response.split(',') if response else []

    def list_my_groups(self) -> Optional[dict]:
        """
        查询自己创建的群组及成员
        :return: 群组字典 {群组ID: [成员ID列表]}，失败返回None
        """
        response = self.send_business_cmd("grouplist")
        if not response:
            return None
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            print("❌ 群组列表响应格式错误")
            return None

    def send_group_message(self, group_id_str: str, message: str):
        """
        发送群组消息
        :param group_id_str: 群组ID（字符串格式）
        :param message: 消息内容
        """
        if not self.running or not self.client_socket or not self.client_id:
            print("❌ 未连接到服务器或未获取ID")
            return
        
        # 解析群组ID
        group_id = self.parse_id(group_id_str)
        if not group_id:
            print("❌ 群组ID格式错误（需8组两位十六进制数）")
            return
        
        # 构造群组消息包
        message_bytes = message.encode('utf-8')
        body = self.client_id + group_id + message_bytes
        body_length = len(body)
        packet = struct.pack(f'!BI{body_length}s', PACKET_GROUP_BUSINESS, body_length, body)
        
        # 发送
        try:
            self.client_socket.sendall(packet)
            print(f"✅ 群组消息发送成功 - 群组: {group_id_str}, 内容: {message}")
        except Exception as e:
            print(f"❌ 群组消息发送失败: {e}")
            self.close()

    def unregister_group(self, group_id_str: str) -> bool:
        """
        注销群组
        :param group_id_str: 群组ID（字符串格式）
        :return: 成功返回True，失败返回False
        """
        if not self.running or not self.client_socket or not self.client_id:
            print("❌ 未连接到服务器或未获取ID")
            return False
        
        # 解析群组ID
        group_id = self.parse_id(group_id_str)
        if not group_id:
            print("❌ 群组ID格式错误（需8组两位十六进制数）")
            return False
        
        # 构造注销包
        body = group_id
        body_length = len(body)
        packet = struct.pack(f'!BI{body_length}s', PACKET_GROUP_UNREGISTER, body_length, body)
        
        # 发送
        try:
            self.client_socket.sendall(packet)
            # 从本地已注册列表移除
            if group_id_str in self.registered_groups:
                self.registered_groups.remove(group_id_str)
            print(f"✅ 群组注销请求已发送 - 群组: {group_id_str}")
            return True
        except Exception as e:
            print(f"❌ 群组注销失败: {e}")
            self.close()
            return False

    def close(self):
        """关闭客户端"""
        if not self.running:
            return
        self.running = False
        print("\n🛑 正在关闭客户端...")
        # 关闭socket
        if self.client_socket:
            try:
                self.client_socket.shutdown(socket.SHUT_RDWR)
                self.client_socket.close()
            except:
                pass
        self.client_id = None
        self.registered_groups.clear()

def main():
    """客户端交互入口"""
    if len(sys.argv) != 3:
        print("使用方法: python cake_client.py <服务器IP> <服务器端口>")
        print("示例: python cake_client.py 127.0.0.1 9966")
        return
    
    server_host = sys.argv[1]
    server_port = int(sys.argv[2])
    
    # 创建客户端并连接
    client = CakeClient(server_host, server_port)
    if not client.connect():
        return
    
    # 交互菜单（适配服务端所有功能）
    print("\n===== Cake客户端（完全适配服务端） =====")
    print("基础功能:")
    print("  send <目标ID> <消息>        - 发送点对点消息（broadcast表示广播）")
    print("  list                        - 查看所有在线客户端ID")
    print("群组功能:")
    print("  group_register              - 注册新群组（无初始成员）")
    print("  group_add <群组ID> <成员ID列表> - 向群组添加成员（成员ID用逗号分隔）")
    print("  group_del <群组ID> <成员ID列表> - 从群组删除成员（成员ID用逗号分隔）")
    print("  group_send <群组ID> <消息>   - 发送群组消息")
    print("  group_list                  - 查看自己创建的群组及成员")
    print("  group_unregister <群组ID>    - 注销群组")
    print("其他:")
    print("  exit                        - 退出客户端")
    print("======================================================\n")
    
    while client.running:
        try:
            command = input("> ").strip()
            if not command:
                continue
            
            if command.lower() == "exit":
                client.close()
                break
            
            parts = command.split(' ', 1)
            base_cmd = parts[0].lower()
            
            # 基础消息发送
            if base_cmd == "send":
                if len(parts) < 2:
                    print("❌ 错误: send命令需要目标ID和消息内容（示例: send a1:b2:c3:d4:e5:f6:78:90 hello）")
                    continue
                sub_parts = parts[1].split(' ', 1)
                if len(sub_parts) != 2:
                    print("❌ 错误: send命令需要目标ID和消息内容（示例: send broadcast hello all）")
                    continue
                target_id = sub_parts[0]
                message = sub_parts[1]
                client.send_message(target_id, message)
            
            # 查看在线客户端
            elif base_cmd == "list":
                print("🔍 正在查询在线客户端...")
                online_ids = client.list_online_clients()
                if online_ids is not None:
                    if online_ids:
                        print("✅ 在线客户端ID列表:")
                        for i, cid in enumerate(online_ids, 1):
                            print(f"   {i}. {cid}")
                    else:
                        print("📭 当前无在线客户端")
                else:
                    print("❌ 查询在线客户端失败")
            
            # 注册群组（无包体）
            elif base_cmd == "group_register":
                print("🔍 正在注册群组...")
                group_id = client.register_group()
                if group_id:
                    print(f"✅ 群组注册成功，群组ID: {group_id}")
                else:
                    print("❌ 群组注册失败")
            
            # 向群组添加成员
            elif base_cmd == "group_add":
                if len(parts) < 2:
                    print("❌ 错误: group_add命令需要群组ID和成员ID列表（示例: group_add a1:b2:...:90 c3:d4:...:80,e5:f6:...:70）")
                    continue
                sub_parts = parts[1].split(' ', 1)
                if len(sub_parts) != 2:
                    print("❌ 错误: group_add命令需要群组ID和成员ID列表（示例: group_add a1:b2:...:90 c3:d4:...:80,e5:f6:...:70）")
                    continue
                group_id = sub_parts[0]
                member_ids = sub_parts[1].split(',')
                print(f"🔍 正在向群组 {group_id} 添加成员...")
                response = client.add_group_members(group_id, member_ids)
                if response == "ok":
                    print(f"✅ 成员添加成功（响应: {response}）")
                elif response == "null":
                    print(f"❌ 群组不存在（响应: {response}）")
                else:
                    print(f"❌ 添加成员失败（响应: {response}）")
            
            # 从群组删除成员
            elif base_cmd == "group_del":
                if len(parts) < 2:
                    print("❌ 错误: group_del命令需要群组ID和成员ID列表（示例: group_del a1:b2:...:90 c3:d4:...:80,e5:f6:...:70）")
                    continue
                sub_parts = parts[1].split(' ', 1)
                if len(sub_parts) != 2:
                    print("❌ 错误: group_del命令需要群组ID和成员ID列表（示例: group_del a1:b2:...:90 c3:d4:...:80,e5:f6:...:70）")
                    continue
                group_id = sub_parts[0]
                member_ids = sub_parts[1].split(',')
                print(f"🔍 正在从群组 {group_id} 删除成员...")
                response = client.del_group_members(group_id, member_ids)
                if response == "ok":
                    print(f"✅ 成员删除成功（响应: {response}）")
                elif response == "null":
                    print(f"❌ 群组不存在（响应: {response}）")
                else:
                    print(f"❌ 删除成员失败（响应: {response}）")
            
            # 发送群组消息
            elif base_cmd == "group_send":
                if len(parts) < 2:
                    print("❌ 错误: group_send命令需要群组ID和消息内容（示例: group_send a1:b2:...:90 hello group）")
                    continue
                sub_parts = parts[1].split(' ', 1)
                if len(sub_parts) != 2:
                    print("❌ 错误: group_send命令需要群组ID和消息内容（示例: group_send a1:b2:...:90 hello group）")
                    continue
                group_id = sub_parts[0]
                message = sub_parts[1]
                client.send_group_message(group_id, message)
            
            # 查看自己创建的群组及成员
            elif base_cmd == "group_list":
                print("🔍 正在查询群组列表...")
                groups = client.list_my_groups()
                if groups is not None:
                    if groups:
                        print("✅ 已创建的群组及成员:")
                        for group_id, members in groups.items():
                            print(f"   群组 {group_id}:")
                            if members:
                                for i, member in enumerate(members, 1):
                                    print(f"      {i}. {member}")
                            else:
                                print("      无成员")
                    else:
                        print("📭 暂无已创建的群组")
                else:
                    print("❌ 查询群组列表失败")
            
            # 注销群组
            elif base_cmd == "group_unregister":
                if len(parts) != 2:
                    print("❌ 错误: group_unregister命令需要群组ID（示例: group_unregister a1:b2:...:90）")
                    continue
                group_id = parts[1]
                success = client.unregister_group(group_id)
                if success:
                    print(f"✅ 群组 {group_id} 注销请求已发送")
                else:
                    print(f"❌ 群组 {group_id} 注销失败")
            
            else:
                print("❌ 未知命令，请重新输入")
        except KeyboardInterrupt:
            client.close()
            break
        except Exception as e:
            print(f"❌ 命令执行错误: {e}")

if __name__ == "__main__":
    main()
