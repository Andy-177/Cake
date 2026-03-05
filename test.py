import cakelib

# 消息回调函数
def on_message(msg):
    """处理接收到的消息"""
    print(f"\n收到消息: {msg}")
    if msg['type'] == 'private':
        print(f"私信 - 来自: {msg['source_id']}, 内容: {msg['text']}")
    elif msg['type'] == 'broadcast':
        print(f"广播 - 来自: {msg['source_id']}, 内容: {msg['text']}")
    elif msg['type'] == 'group':
        print(f"群组 - 群组: {msg['group_id']}, 来自: {msg['source_id']}, 内容: {msg['text']}")

# 1. 连接服务器
if cakelib.connect("127.0.0.1:9966"):
    print("连接成功！")
    
    # 2. 设置消息回调
    cakelib.set_callback(on_message)
    
    # 3. 获取客户端ID
    client_id = cakelib.getid()
    print(f"客户端ID: {client_id}")
    
    # 4. 发送点对点消息
    target_id = "00:00:00:00:00:00:00:01"  # 替换为实际目标ID
    cakelib.send(target_id, "你好！")
    
    # 5. 广播消息
    cakelib.broadcast("这是一条广播消息！")
    
    # 6. 获取在线列表
    online_ids = cakelib.list()
    print(f"在线客户端: {online_ids}")
    
    # 7. 注册群组
    group_id = cakelib.registergroup([client_id])  # 初始成员包含自己
    if group_id:
        print(f"注册群组成功: {group_id}")
        
        # 8. 发送群组消息
        cakelib.groupsendtext(group_id, "大家好！这是群消息")
        
        # 9. 获取群组列表
        group_list = cakelib.grouplist()
        print(f"我的群组: {group_list}")
        
        # 10. 注销群组
        # cakelib.unregistergroup(group_id)
    
    # 保持运行接收消息
    try:
        while True:
            input("按回车退出...")
            break
    except KeyboardInterrupt:
        pass
    
    # 11. 关闭连接
    cakelib.close()
else:
    print("连接失败！")
