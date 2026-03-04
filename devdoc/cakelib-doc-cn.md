# CakeLib 开发文档
## 1. 概述
CakeLib 是一个基于 TCP 协议的客户端通信库，用于与 Cake 服务器建立连接、进行点对点消息通信、广播消息以及实现群组通信功能。该库封装了底层的 socket 通信、心跳保活、数据包编解码等逻辑，对外提供简洁易用的 API 接口。

### 核心特性
- 自动与 Cake 服务器建立 TCP 连接并获取唯一客户端 ID
- 心跳保活机制，自动检测连接状态
- 支持点对点消息发送、广播消息发送
- 支持群组的创建、注销、群组消息发送
- 支持获取在线客户端列表、已注册群组列表
- 异步消息接收回调机制

## 2. 环境依赖
- Python 版本：3.6 及以上
- 依赖库：无（仅使用 Python 标准库）
- 网络要求：客户端需能访问 Cake 服务器的 IP 和端口

## 3. 数据结构与常量说明
### 3.1 数据包结构
所有与服务器交互的数据包遵循统一格式：
| 字段         | 类型       | 长度（字节） | 说明                     |
|--------------|------------|--------------|--------------------------|
| 包类型       | uint8      | 1            | 标识数据包用途（如心跳、消息、群组注册等） |
| 包体长度     | uint32     | 4            | 大端序（!），表示包体的字节长度 |
| 包体         | bytes      | 可变         | 具体的业务数据，长度与包体长度字段一致 |

### 3.2 核心常量
| 常量名              | 值/说明                                  |
|---------------------|------------------------------------------|
| BUFFER_SIZE         | 4096，接收数据的缓冲区大小               |
| ID_LENGTH           | 8，客户端/群组 ID 的字节长度             |
| BROADCAST_ID        | b'\xff' * 8，广播消息的目标 ID           |
| SERVER_RESERVED_ID  | b'\x00' * 8，服务器保留 ID               |
| HEARTBEAT_INTERVAL  | 5，心跳包发送间隔（秒）                  |
| HEARTBEAT_TIMEOUT   | 20，心跳超时时间（秒）                   |
| PACKET_HEARTBEAT    | 0x04，心跳包类型标识                     |
| PACKET_ID_REQUEST   | 0x01，ID 请求包类型标识                  |
| PACKET_ID_RESPONSE  | 0x02，ID 响应包类型标识                  |
| PACKET_MESSAGE      | 0x03，业务消息包类型标识                 |
| PACKET_GROUP_REGISTER | 0x05，群组注册包类型标识               |
| PACKET_GROUP_RESPONSE | 0x07，群组 ID 响应包类型标识           |
| PACKET_GROUP_MESSAGE | 0x06，群组消息包类型标识               |
| PACKET_GROUP_UNREGISTER | 0x08，群组注销包类型标识           |

### 3.3 ID 格式说明
客户端/群组 ID 采用 **8 组两位十六进制数** 的字符串格式，例如：`a1:b2:c3:d4:e5:f6:78:90`，对应底层 8 字节的二进制数据。

## 4. 基础 API 接口
### 4.1 connect(server_addr: str) -> Tuple[bool, str]
**功能**：连接到 Cake 服务器，并完成客户端 ID 的获取。
**参数**：
- `server_addr`：服务器地址，支持两种格式：
  - 完整格式：`ip:port`（如 `127.0.0.1:9966`、`xxx.abc.xyz:9966`）
  - 简化格式：仅 IP/域名（如 `127.0.0.1`），默认使用端口 9966
**返回值**：
- 元组 `(是否成功, 消息/错误信息)`：
  - 成功：`(True, 客户端ID字符串)`
  - 失败：`(False, 错误描述)`
**示例**：
```python
import cakelib

# 连接服务器
success, msg = cakelib.connect("127.0.0.1:9966")
if success:
    print(f"连接成功，客户端ID：{msg}")
else:
    print(f"连接失败：{msg}")
```

### 4.2 send(target_id: str, message: Union[str, bytes]) -> Tuple[bool, str]
**功能**：向指定 ID 的客户端发送消息。
**参数**：
- `target_id`：目标客户端 ID 字符串（格式如 `a1:b2:c3:d4:e5:f6:78:90`）
- `message`：要发送的消息，支持字符串（自动编码为 UTF-8 字节）或字节流
**返回值**：
- 元组 `(是否成功, 消息/错误信息)`
**示例**：
```python
# 发送文本消息
success, msg = cakelib.send("a1:b2:c3:d4:e5:f6:78:90", "你好，这是一条测试消息")
# 发送字节流
success, msg = cakelib.send("a1:b2:c3:d4:e5:f6:78:90", b"\x01\x02\x03\x04")
```

### 4.3 broadcast(message: Union[str, bytes]) -> Tuple[bool, str]
**功能**：广播消息给所有在线客户端。
**参数**：
- `message`：要广播的消息，支持字符串或字节流
**返回值**：
- 元组 `(是否成功, 消息/错误信息)`
**示例**：
```python
success, msg = cakelib.broadcast("全体客户端请注意，这是一条广播消息")
```

### 4.4 getid() -> Tuple[Optional[str], str]
**别名**：`get_id()`
**功能**：获取当前客户端的 ID 字符串。
**返回值**：
- 元组 `(客户端ID字符串/None, 错误信息/空字符串)`：
  - 成功：`(ID字符串, "")`
  - 失败：`(None, 错误描述)`
**示例**：
```python
client_id, err = cakelib.getid()
if client_id:
    print(f"当前客户端ID：{client_id}")
else:
    print(f"获取ID失败：{err}")
```

### 4.5 set_callback(callback) -> None
**功能**：设置消息接收的回调函数，当收到其他客户端/服务器的消息时自动触发。
**参数**：
- `callback`：回调函数，格式为 `callback(src_id: str, dest_id: str, message: bytes)`：
  - `src_id`：发送方 ID 字符串
  - `dest_id`：接收方 ID 字符串（当前客户端 ID）
  - `message`：收到的消息字节流
**示例**：
```python
# 定义回调函数
def on_message(src_id, dest_id, message):
    print(f"收到来自 {src_id} 的消息：{message.decode('utf-8')}")

# 设置回调
cakelib.set_callback(on_message)
```

### 4.6 close() -> None
**功能**：关闭与服务器的连接，停止心跳线程和接收线程。
**示例**：
```python
cakelib.close()
```

## 5. 群组相关 API 接口
### 5.1 registergroup(member_ids: List[str]) -> Tuple[Optional[str], str]
**功能**：注册一个新群组，指定群组成员列表。
**参数**：
- `member_ids`：群组成员 ID 列表（字符串格式），例如 `["11:11:11:11:11:11:11:11", "22:22:22:22:22:22:22:22"]`
**返回值**：
- 元组 `(群组ID字符串/None, 错误信息/成功信息)`：
  - 成功：`(群组ID字符串, "群组注册成功，ID: xxx")`
  - 失败：`(None, 错误描述)`
**示例**：
```python
# 定义群组成员
members = ["a1:b2:c3:d4:e5:f6:78:90", "00:11:22:33:44:55:66:77"]
# 注册群组
group_id, msg = cakelib.registergroup(members)
if group_id:
    print(f"群组注册成功，ID：{group_id}")
else:
    print(f"群组注册失败：{msg}")
```

### 5.2 groupsend(group_id: str, data: bytes) -> Tuple[bool, str]
**别名**：`group_send()`
**功能**：向指定群组发送二进制数据。
**参数**：
- `group_id`：群组 ID 字符串
- `data`：要发送的二进制数据
**返回值**：
- 元组 `(是否成功, 消息/错误信息)`
**示例**：
```python
# 发送二进制数据到群组
success, msg = cakelib.groupsend("88:88:88:88:88:88:88:88", b"\x00\x01\x02\x03")
```

### 5.3 groupsendtext(group_id: str, text: str) -> Tuple[bool, str]
**别名**：`group_send_text()`
**功能**：向指定群组发送文本消息（自动编码为 UTF-8 字节）。
**参数**：
- `group_id`：群组 ID 字符串
- `text`：要发送的文本字符串
**返回值**：
- 元组 `(是否成功, 消息/错误信息)`
**示例**：
```python
# 发送文本消息到群组
success, msg = cakelib.groupsendtext("88:88:88:88:88:88:88:88", "各位群成员，这是一条群组消息")
```

### 5.4 unregistergroup(group_id: str) -> Tuple[bool, str]
**别名**：`unregister_group()`
**功能**：注销指定的群组。
**参数**：
- `group_id`：要注销的群组 ID 字符串
**返回值**：
- 元组 `(是否成功, 消息/错误信息)`
**示例**：
```python
success, msg = cakelib.unregistergroup("88:88:88:88:88:88:88:88")
if success:
    print(f"群组注销成功：{msg}")
else:
    print(f"群组注销失败：{msg}")
```

### 5.5 grouplist() -> Optional[Dict]
**别名**：`group_list()`
**功能**：获取当前客户端注册的所有群组列表。
**返回值**：
- 成功：字典 `{群组ID: [成员ID列表]}`，例如：
  ```python
  {
      "88:88:88:88:88:88:88:88": ["a1:b2:c3:d4:e5:f6:78:90", "00:11:22:33:44:55:66:77"],
      "99:99:99:99:99:99:99:99": ["a1:b2:c3:d4:e5:f6:78:90"]
  }
  ```
- 失败/无群组：`None`
**示例**：
```python
groups = cakelib.grouplist()
if groups:
    print("当前注册的群组：")
    for gid, members in groups.items():
        print(f"群组 {gid} 成员：{members}")
else:
    print("未注册任何群组或请求失败")
```

### 5.6 list() -> List[str]
**别名**：`online_list()`
**功能**：获取所有在线客户端的 ID 列表。
**返回值**：
- 成功：在线客户端 ID 字符串列表（空列表表示无在线客户端）
- 失败：空列表
**示例**：
```python
online_ids = cakelib.list()
print(f"当前在线客户端数量：{len(online_ids)}")
for client_id in online_ids:
    print(f"在线客户端：{client_id}")
```

## 6. 完整使用示例
```python
import cakelib
import time

# 定义消息回调函数
def message_callback(src_id, dest_id, message):
    """处理收到的消息"""
    try:
        # 尝试解码为文本
        text = message.decode('utf-8')
        print(f"\n收到消息 - 发送方：{src_id} | 内容：{text}")
    except:
        # 二进制消息
        print(f"\n收到二进制消息 - 发送方：{src_id} | 长度：{len(message)} 字节")

def main():
    # 1. 连接服务器
    server_addr = "127.0.0.1:9966"
    success, msg = cakelib.connect(server_addr)
    if not success:
        print(f"连接服务器失败：{msg}")
        return
    print(f"连接成功，客户端ID：{msg}")

    # 2. 设置消息回调
    cakelib.set_callback(message_callback)

    # 3. 获取当前客户端ID
    client_id, err = cakelib.getid()
    print(f"当前客户端ID确认：{client_id}")

    # 4. 获取在线客户端列表
    online_ids = cakelib.list()
    print(f"在线客户端列表：{online_ids}")

    # 5. 注册群组（如果有其他在线客户端）
    if len(online_ids) > 1:
        # 排除自己，选择第一个其他客户端作为群成员
        other_member = [id for id in online_ids if id != client_id][0]
        group_id, msg = cakelib.registergroup([client_id, other_member])
        if group_id:
            print(f"群组注册成功，ID：{group_id}")
            
            # 发送群组文本消息
            success, msg = cakelib.groupsendtext(group_id, "大家好，这是群组测试消息！")
            print(f"群组消息发送结果：{msg}")
            
            # 获取群组列表
            groups = cakelib.grouplist()
            print(f"当前注册的群组：{groups}")
            
            # 注销群组（可选）
            # success, msg = cakelib.unregistergroup(group_id)
            # print(f"群组注销结果：{msg}")

    # 6. 发送点对点消息（如果有其他在线客户端）
    if len(online_ids) > 1:
        target_id = online_ids[0]
        if target_id != client_id:
            success, msg = cakelib.send(target_id, "你好，这是点对点测试消息！")
            print(f"点对点消息发送结果：{msg}")

    # 7. 发送广播消息
    success, msg = cakelib.broadcast("这是一条广播消息，所有客户端都能收到！")
    print(f"广播消息发送结果：{msg}")

    # 8. 保持连接，等待接收消息
    try:
        print("\n客户端已就绪，等待消息（按 Ctrl+C 退出）...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n用户退出，关闭连接...")
    finally:
        # 9. 关闭连接
        cakelib.close()
        print("连接已关闭")

if __name__ == "__main__":
    main()
```

## 7. 异常处理与注意事项
### 7.1 异常场景
1. **连接失败**：
   - 服务器地址格式错误（如端口非数字）
   - 服务器不可达（网络问题、服务器未启动）
   - 连接超时（超过 10 秒未建立连接）
   - 服务器返回无效的 ID 响应包
2. **消息发送失败**：
   - 未连接服务器（未调用 `connect()` 或连接已断开）
   - 目标 ID 格式错误（非 8 组两位十六进制数）
   - 网络断开（心跳超时触发连接关闭）
3. **群组操作失败**：
   - 群组成员 ID 格式错误
   - 群组注册/注销请求超时（超过 10 秒未收到响应）
   - 群组 ID 不存在（注销/发送消息时）

### 7.2 注意事项
1. 所有 API 调用前必须确保已成功连接服务器（`connect()` 返回 `True`），否则会返回失败
2. 回调函数应尽量简洁，避免阻塞（回调运行在接收线程中，阻塞会影响消息接收）
3. 心跳超时（20 秒）会自动关闭连接，需重新调用 `connect()` 重连
4. 客户端 ID 在连接断开后失效，重新连接会获取新的 ID
5. 字符串消息默认使用 UTF-8 编码，如需其他编码需手动处理字节流
6. 群组注册后，只有注册者可以注销该群组（具体取决于服务器逻辑）
7. 广播消息会发送给所有在线客户端，包括自己
8. 程序退出前需调用 `close()` 关闭连接，避免资源泄漏

## 8. 内部实现说明（可选）
### 8.1 核心类 `_CakeClient`
- 对外不暴露，通过全局实例 `_global_client` 提供服务
- 核心方法：
  - `connect()`：处理连接建立、ID 获取、线程启动
  - `_recv_messages()`：接收线程核心逻辑，处理数据包解析、回调触发
  - `_heartbeat_loop()`：心跳线程，定时发送心跳包并检测超时
  - 各类消息/群组操作方法：封装数据包编解码和发送逻辑

### 8.2 线程模型
- 接收线程（`recv_thread`）：阻塞式接收服务器数据，解析数据包并触发回调
- 心跳线程（`heartbeat_thread`）：定时发送心跳包，检测连接状态
- 所有线程均为守护线程（`daemon=True`），主程序退出时自动结束

### 8.3 同步请求处理
- 对于需要等待服务器响应的操作（如群组注册、获取群组列表、获取在线列表），使用：
  - `sync_response_lock`：保护响应数据的线程安全
  - `sync_response_event`：等待响应的事件通知
  - 超时机制（10 秒）避免无限等待