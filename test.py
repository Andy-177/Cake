import cakelib

# 1. 连接服务器
success, msg = cakelib.connect("127.0.0.1:9966")
if not success:
    print(f"连接失败: {msg}")
else:
    print(f"连接成功，客户端ID: {msg}")

# 2. 注册群组
member_ids = ["11:11:11:11:11:11:11:11", "22:22:22:22:22:22:22:22"]
group_id, msg = cakelib.registergroup(member_ids)
if group_id:
    print(f"群组注册成功，ID: {group_id}")
else:
    print(f"群组注册失败: {msg}")

# 3. 发送群组文本消息
success, msg = cakelib.groupsendtext(group_id, "大家好！")
if success:
    print(f"文本消息发送成功: {msg}")
else:
    print(f"文本消息发送失败: {msg}")

# 4. 发送二进制数据到群组
binary_data = b"\x01\x02\x03\x04"
success, msg = cakelib.groupsend(group_id, binary_data)
if success:
    print(f"二进制数据发送成功: {msg}")
else:
    print(f"二进制数据发送失败: {msg}")

# 5. 获取群组列表
group_list = cakelib.grouplist()
if group_list is None:
    print("暂无注册群组")
else:
    print(f"已注册群组: {group_list}")

# 6. 获取在线ID列表
online_ids = cakelib.list()
print(f"在线客户端ID列表: {online_ids}")

# 7. 注销群组
success, msg = cakelib.unregistergroup(group_id)
if success:
    print(f"群组注销成功: {msg}")
else:
    print(f"群组注销失败: {msg}")

# 8. 关闭连接
cakelib.close()
