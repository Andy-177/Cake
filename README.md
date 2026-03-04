# Cake
## 一、程序概述
Cake 是一套基于 TCP 协议实现的即时通信系统，支持**点对点消息**、**广播消息**、**群组消息**三大核心功能，内置心跳保活机制保证连接稳定性，同时提供完善的客户端/服务器交互逻辑，适用于小型局域网内的实时通信场景。

### 核心特性
1. **基础通信**：客户端与服务器建立连接后自动分配唯一8字节ID，支持点对点消息、全局广播消息；
2. **心跳保活**：客户端每5秒发送心跳包，服务器20秒未收到心跳则断开连接，避免无效连接占用资源；
3. **群组功能**：支持创建/注销群组、发送群组消息、查询已创建群组列表；
4. **状态查询**：支持查询当前在线客户端ID列表、已注册群组及成员信息；
5. **资源回收**：客户端下线后自动回收其创建的所有群组，避免群组资源泄漏。

## 二、文件说明
| 文件角色       | 核心功能                                                                 |
|----------------|--------------------------------------------------------------------------|
| 服务器端代码   | 监听客户端连接、分配客户端ID、转发消息（点对点/广播/群组）、管理群组生命周期 |
| 客户端API代码  | 封装通信接口（连接、发送消息、群组操作等），供其他程序调用               |
| 客户端交互代码 | 提供命令行交互界面，支持手动输入指令完成消息发送、群组管理等操作         |

## 三、环境要求
- Python 3.6+
- 无额外第三方依赖（仅使用Python标准库：`socket`/`threading`/`struct`/`json`等）
- 服务器与客户端网络互通，且服务器端口（默认9966）未被防火墙拦截

## 四、使用方法
### 1. 启动服务器
将服务器端代码保存为`cake.py`，执行以下命令启动：
```bash
python cake.py
```
启动成功后会输出：
```
[Cake服务器] 启动成功，监听地址: 0.0.0.0:9966
[Cake服务器] 保留ID: 00:00:00:00:00:00:00:00
[Cake服务器] 广播ID: ff:ff:ff:ff:ff:ff:ff:ff
```
- `0.0.0.0` 表示监听所有网卡，支持外网/局域网连接；
- 保留ID（全0）用于客户端向服务器发送指令（如查询在线列表）；
- 广播ID（全FF）用于发送全局广播消息。

### 2. 启动交互式客户端
将客户端交互代码保存为`Client.py`，执行以下命令连接服务器：
```bash
# 格式：python Client.py <服务器IP> <服务器端口>
python Client.py 127.0.0.1 9966
```
连接成功后会输出客户端ID，并进入交互菜单：
```
已连接到服务器 127.0.0.1:9966
获取到客户端ID: xx:xx:xx:xx:xx:xx:xx:xx

===== Cake客户端（带稳定心跳+群组功能） =====
基础功能:
  send <目标ID> <消息>        - 发送点对点消息
  broadcast <消息>            - 发送广播消息
群组功能:
  group_register <成员ID列表>  - 注册群组（成员ID用逗号分隔）
  group_send <群组ID> <消息>   - 发送群组消息
  group_unregister <群组ID>    - 注销群组
  group_list                  - 查看已注册的群组
其他:
  exit                        - 退出客户端
======================================================
```

### 3. 核心操作示例
#### （1）基础消息发送
- 点对点消息：
  ```bash
  > send aa:bb:cc:dd:ee:ff:11:22 你好，这是点对点消息
  ✅ 消息发送成功 - 目标: aa:bb:cc:dd:ee:ff:11:22, 内容: 你好，这是点对点消息
  ```
- 广播消息（所有在线客户端均可接收）：
  ```bash
  > broadcast 大家好，这是广播消息
  ✅ 消息发送成功 - 目标: broadcast, 内容: 大家好，这是广播消息
  ```

#### （2）群组操作
- 创建群组（成员ID用逗号分隔）：
  ```bash
  > group_register aa:bb:cc:dd:ee:ff:11:22,33:44:55:66:77:88:99:00
  ✅ 群组注册请求已发送，成员数: 2
  ✅ 群组注册完成，群组ID: 88:77:66:55:44:33:22:11
  ```
- 发送群组消息：
  ```bash
  > group_send 88:77:66:55:44:33:22:11 各位群成员，大家好！
  ✅ 群组消息发送成功 - 群组: 88:77:66:55:44:33:22:11, 内容: 各位群成员，大家好！
  ```
- 查看已创建的群组：
  ```bash
  > group_list
  📋 已注册的群组列表:
     1. 88:77:66:55:44:33:22:11
  ```
- 注销群组：
  ```bash
  > group_unregister 88:77:66:55:44:33:22:11
  ✅ 群组 88:77:66:55:44:33:22:11 注销请求已发送
  ```

#### （3）状态查询（通过API客户端实现）
若使用客户端API代码（非交互式），可调用以下接口：
```python
# 连接服务器
success, msg = connect("127.0.0.1:9966")
# 查询在线客户端列表
online_ids = list()
print("在线客户端ID:", online_ids)
# 查询已创建的群组
groups = grouplist()
print("已创建群组:", groups)
```

### 4. 客户端API调用示例
将客户端API代码保存为`cakelib.py`，可在其他Python程序中调用：
```python
import cakelib as cake

# 1. 连接服务器
success, msg = cake.connect("127.0.0.1:9966")
if not success:
    print("连接失败:", msg)
else:
    print("连接成功，客户端ID:", msg)

# 2. 定义消息回调函数（接收消息时触发）
def on_message(src_id, dest_id, message):
    print(f"收到消息 - 来源: {src_id}, 目标: {dest_id}, 内容: {message.decode('utf-8')}")

cake.set_callback(on_message)

# 3. 发送点对点消息
cake.send("aa:bb:cc:dd:ee:ff:11:22", "Hello from API")

# 4. 发送广播消息
cake.broadcast("Broadcast from API")

# 5. 创建群组
group_id, msg = cake.registergroup(["aa:bb:cc:dd:ee:ff:11:22"])
if group_id:
    print("创建群组成功，ID:", group_id)
    # 发送群组文本消息
    cake.groupsendtext(group_id, "Hello Group")

# 6. 查询在线列表
online_ids = cake.list()
print("在线客户端:", online_ids)

# 7. 关闭连接
# cake.close()
```

## 五、注意事项
1. **ID格式**：客户端/群组ID均为8组两位十六进制数（如`aa:bb:cc:dd:ee:ff:11:22`），请勿修改格式；
2. **连接稳定性**：客户端断网/超时后会自动断开，重新连接会分配新ID；
3. **群组回收**：创建群组的客户端下线后，其创建的所有群组会被服务器自动回收；
4. **编码兼容**：消息内容默认使用UTF-8编码，若发送非UTF-8字符可能导致乱码；
5. **端口冲突**：若9966端口被占用，可修改代码中`cake_PORT`（服务器）/ 客户端连接参数。

## 六、常见问题
1. **客户端连接失败**：
   - 检查服务器是否启动、服务器IP/端口是否正确；
   - 检查服务器防火墙是否放行9966端口；
   - 确保客户端与服务器网络互通（可通过ping测试）。
2. **消息发送成功但对方未接收**：
   - 确认目标客户端在线且ID正确；
   - 群组消息需确认目标群组未被注销、接收者是群成员。
3. **心跳超时断开**：
   - 检查网络是否稳定，避免长时间无数据传输导致路由断开；
   - 可调整代码中`HEARTBEAT_INTERVAL`（心跳间隔）/`HEARTBEAT_TIMEOUT`（超时时间）参数。

---

# English

# Cake
## I. Program Overview
Cake is an instant messaging system implemented based on the TCP protocol, supporting three core functions: **point-to-point messaging**, **broadcast messaging**, and **group messaging**. It features a built-in heartbeat keep-alive mechanism to ensure connection stability, and provides complete client/server interaction logic, suitable for real-time communication scenarios in small local area networks.

### Core Features
1. **Basic Communication**: After a client establishes a connection with the server, a unique 8-byte ID is automatically assigned. Supports point-to-point messages and global broadcast messages.
2. **Heartbeat Keep-Alive**: The client sends a heartbeat packet every 5 seconds. The server disconnects if no heartbeat is received for 20 seconds, preventing invalid connections from occupying resources.
3. **Group Functions**: Supports creating/destroying groups, sending group messages, and querying the list of created groups.
4. **Status Query**: Supports querying the current online client ID list, registered groups, and member information.
5. **Resource Reclamation**: All groups created by a client are automatically reclaimed when the client goes offline, avoiding group resource leaks.

## II. File Description
| Role          | Core Functions                                                                 |
|---------------|--------------------------------------------------------------------------------|
| Server Code   | Listens for client connections, assigns client IDs, forwards messages (P2P/broadcast/group), manages group lifecycles |
| Client API Code | Encapsulates communication interfaces (connection, message sending, group operations, etc.) for use by other programs |
| Client Interactive Code | Provides a command-line interactive interface, supporting manual input of commands to send messages, manage groups, etc. |

## III. Environment Requirements
- Python 3.6 or higher
- No additional third-party dependencies (only Python standard libraries: `socket`, `threading`, `struct`, `json`, etc.)
- Network connectivity between server and clients; server port (default 9966) not blocked by firewall

## IV. Usage Instructions
### 1. Start the Server
Save the server code as `cake.py` and run the following command to start:
```bash
python cake.py
```
On successful startup, it will print:
```
[Cake Server] Started successfully, listening on: 0.0.0.0:9966
[Cake Server] Reserved ID: 00:00:00:00:00:00:00:00
[Cake Server] Broadcast ID: ff:ff:ff:ff:ff:ff:ff:ff
```
- `0.0.0.0` means listening on all network interfaces, supporting LAN/WAN connections.
- Reserved ID (all zeros) is used for clients to send commands to the server (e.g., query online list).
- Broadcast ID (all FFs) is used to send global broadcast messages.

### 2. Start the Interactive Client
Save the client interactive code as `Client.py` and run the following command to connect to the server:
```bash
# Format: python Client.py <server-ip> <server-port>
python Client.py 127.0.0.1 9966
```
After a successful connection, the client ID will be displayed, and you will enter the interactive menu:
```
Connected to server 127.0.0.1:9966
Assigned client ID: xx:xx:xx:xx:xx:xx:xx:xx

===== Cake Client (Stable Heartbeat + Group Functions) =====
Basic Functions:
  send <target-id> <message>        - Send point-to-point message
  broadcast <message>               - Send broadcast message
Group Functions:
  group_register <member-id-list>    - Register group (member IDs separated by commas)
  group_send <group-id> <message>    - Send group message
  group_unregister <group-id>        - Unregister group
  group_list                        - View registered groups
Others:
  exit                              - Exit client
======================================================
```

### 3. Core Operation Examples
#### (1) Basic Message Sending
- Point-to-point message:
  ```bash
  > send aa:bb:cc:dd:ee:ff:11:22 Hello, this is a point-to-point message
  ✅ Message sent successfully - Target: aa:bb:cc:dd:ee:ff:11:22, Content: Hello, this is a point-to-point message
  ```
- Broadcast message (received by all online clients):
  ```bash
  > broadcast Hello everyone, this is a broadcast message
  ✅ Message sent successfully - Target: broadcast, Content: Hello everyone, this is a broadcast message
  ```

#### (2) Group Operations
- Create a group (member IDs separated by commas):
  ```bash
  > group_register aa:bb:cc:dd:ee:ff:11:22,33:44:55:66:77:88:99:00
  ✅ Group registration request sent, member count: 2
  ✅ Group registration completed, Group ID: 88:77:66:55:44:33:22:11
  ```
- Send group message:
  ```bash
  > group_send 88:77:66:55:44:33:22:11 Hello everyone!
  ✅ Group message sent successfully - Group: 88:77:66:55:44:33:22:11, Content: Hello everyone!
  ```
- View created groups:
  ```bash
  > group_list
  📋 Registered group list:
     1. 88:77:66:55:44:33:22:11
  ```
- Unregister a group:
  ```bash
  > group_unregister 88:77:66:55:44:33:22:11
  ✅ Unregister request sent for group 88:77:66:55:44:33:22:11
  ```

#### (3) Status Query (via API Client)
When using the client API code (non-interactive), you can call these interfaces:
```python
# Connect to server
success, msg = connect("127.0.0.1:9966")
# Query online client list
online_ids = list()
print("Online client IDs:", online_ids)
# Query created groups
groups = grouplist()
print("Created groups:", groups)
```

### 4. Client API Usage Example
Save the client API code as `cakelib.py` and import it in other Python programs:
```python
import cakelib as cake

# 1. Connect to server
success, msg = cake.connect("127.0.0.1:9966")
if not success:
    print("Connection failed:", msg)
else:
    print("Connected successfully, client ID:", msg)

# 2. Define message callback (triggered when a message is received)
def on_message(src_id, dest_id, message):
    print(f"Message received - From: {src_id}, To: {dest_id}, Content: {message.decode('utf-8')}")

cake.set_callback(on_message)

# 3. Send point-to-point message
cake.send("aa:bb:cc:dd:ee:ff:11:22", "Hello from API")

# 4. Send broadcast message
cake.broadcast("Broadcast from API")

# 5. Create group
group_id, msg = cake.registergroup(["aa:bb:cc:dd:ee:ff:11:22"])
if group_id:
    print("Group created successfully, ID:", group_id)
    # Send group text message
    cake.groupsendtext(group_id, "Hello Group")

# 6. Query online list
online_ids = cake.list()
print("Online clients:", online_ids)

# 7. Close connection
# cake.close()
```

## V. Notes
1. **ID Format**: Client and group IDs are 8 groups of two-digit hexadecimal numbers (e.g., `aa:bb:cc:dd:ee:ff:11:22`). Do not modify the format.
2. **Connection Stability**: The client disconnects automatically on network loss/timeout; a new ID will be assigned upon reconnection.
3. **Group Reclamation**: All groups created by a client are automatically reclaimed by the server when the creator goes offline.
4. **Encoding Compatibility**: Messages use UTF-8 encoding by default. Non-UTF-8 characters may cause garbled text.
5. **Port Conflict**: If port 9966 is occupied, modify `cake_PORT` in the server code and the client connection parameters.

## VI. Common Issues
1. **Client fails to connect**:
   - Check if the server is running and the server IP/port are correct.
   - Check if the firewall allows port 9966.
   - Ensure network connectivity between client and server (test with ping).
2. **Message sent successfully but not received**:
   - Verify the target client is online and the ID is correct.
   - For group messages, confirm the target group is not unregistered and the receiver is a group member.
3. **Heartbeat timeout disconnection**:
   - Check network stability; avoid long periods of no data transmission that may cause routing disconnection.
   - Adjust `HEARTBEAT_INTERVAL` (heartbeat interval) and `HEARTBEAT_TIMEOUT` (timeout duration) in the code.

---

# 日本語

# Cake
## 一、プログラム概要
Cake は TCP プロトコルを基盤として実装されたインスタントメッセージングシステムです。**ピアツーピアメッセージ**、**ブロードキャストメッセージ**、**グループメッセージ**の3つのコア機能をサポートし、ハートビート維持機構を内蔵して接続の安定性を確保するとともに、クライアント/サーバー間のインタラクションロジックを整備しています。小規模なローカルネットワーク内でのリアルタイムコミュニケーションに適しています。

### コア機能
1. **基本通信**
    クライアントがサーバーと接続を確立すると、自動的に一意の8バイトIDが割り当てられ、ピアツーピアメッセージおよびグローバルブロードキャストメッセージに対応。
2. **ハートビート維持**
    クライアントは5秒ごとにハートビートパケットを送信し、サーバーは20秒間ハートビートを受信しない場合に接続を切断し、無効な接続によるリソース占有を回避。
3. **グループ機能**
    グループの作成/削除、グループメッセージ送信、作成済みグループ一覧の照会に対応。
4. **状態照会**
    現在オンライン中のクライアントIDリスト、登録済みグループおよびメンバー情報の照会に対応。
5. **リソース解放**
    クライアントがオフラインになると、作成したすべてのグループが自動的に解放され、グループリソースのリークを防止。

## 二、ファイル説明
| ファイル役割 | コア機能 |
|--------------|----------|
| サーバー側コード | クライアント接続の待ち受け、クライアントIDの割り当て、メッセージ転送（ピアツーピア/ブロードキャスト/グループ）、グループライフサイクルの管理 |
| クライアントAPIコード | 通信インターフェース（接続、メッセージ送信、グループ操作など）をカプセル化し、他のプログラムから呼び出し可能 |
| クライアントインタラクティブコード | コマンドラインインターフェースを提供し、手動入力によるメッセージ送信、グループ管理などの操作を実現 |

## 三、動作環境
- Python 3.6以上
- 追加のサードパーティ製ライブラリに依存せず、Python標準ライブラリ（`socket`/`threading`/`struct`/`json`など）のみを使用
- サーバーとクライアントがネットワーク上で相互に到達可能であり、サーバーのポート（デフォルト9966）がファイアウォールでブロックされていないこと

## 四、使用方法
### 1. サーバーの起動
サーバー側コードを`cake.py`として保存し、以下のコマンドで起動します。
```bash
python cake.py
```
起動に成功すると以下が出力されます。
```
[Cakeサーバー] 起動に成功しました。待ち受けアドレス: 0.0.0.0:9966
[Cakeサーバー] 予約済みID: 00:00:00:00:00:00:00:00
[Cakeサーバー] ブロードキャストID: ff:ff:ff:ff:ff:ff:ff:ff
```
- `0.0.0.0` はすべてのネットワークカードを待ち受け対象とし、外部ネットワーク/ローカルネットワークからの接続に対応
- 予約済みID（すべて0）はクライアントがサーバーにコマンド（オンラインリスト照会など）を送信する際に使用
- ブロードキャストID（すべてFF）はグローバルブロードキャストメッセージの送信に使用

### 2. インタラクティブクライアントの起動
クライアントインタラクティブコードを`Client.py`として保存し、以下のコマンドでサーバーに接続します。
```bash
# 形式：python Client.py <サーバーIP> <サーバーポート>
python Client.py 127.0.0.1 9966
```
接続に成功するとクライアントIDが表示され、インタラクティブメニューに移行します。
```
サーバー 127.0.0.1:9966 に接続しました
クライアントIDを取得しました: xx:xx:xx:xx:xx:xx:xx:xx

===== Cakeクライアント（安定したハートビート+グループ機能付き）=====
基本機能:
  send <対象ID> <メッセージ>        - ピアツーピアメッセージ送信
  broadcast <メッセージ>            - ブロードキャストメッセージ送信
グループ機能:
  group_register <メンバーIDリスト>  - グループ登録（メンバーIDはカンマ区切り）
  group_send <グループID> <メッセージ>   - グループメッセージ送信
  group_unregister <グループID>    - グループ削除
  group_list                  - 登録済みグループを表示
その他:
  exit                        - クライアント終了
======================================================
```

### 3. コア操作例
#### （1）基本メッセージ送信
- ピアツーピアメッセージ：
  ```bash
  > send aa:bb:cc:dd:ee:ff:11:22 こんにちは、ピアツーピアメッセージです
  ✅ メッセージ送信に成功しました - 対象: aa:bb:cc:dd:ee:ff:11:22, 内容: こんにちは、ピアツーピアメッセージです
  ```
- ブロードキャストメッセージ（すべてのオンラインクライアントが受信）：
  ```bash
  > broadcast みなさんこんにちは、ブロードキャストメッセージです
  ✅ メッセージ送信に成功しました - 対象: broadcast, 内容: みなさんこんにちは、ブロードキャストメッセージです
  ```

#### （2）グループ操作
- グループ作成（メンバーIDはカンマ区切り）：
  ```bash
  > group_register aa:bb:cc:dd:ee:ff:11:22,33:44:55:66:77:88:99:00
  ✅ グループ登録リクエストを送信しました。メンバー数: 2
  ✅ グループ登録が完了しました。グループID: 88:77:66:55:44:33:22:11
  ```
- グループメッセージ送信：
  ```bash
  > group_send 88:77:66:55:44:33:22:11 グループの皆さん、こんにちは！
  ✅ グループメッセージ送信に成功しました - グループ: 88:77:66:55:44:33:22:11, 内容: グループの皆さん、こんにちは！
  ```
- 作成済みグループを表示：
  ```bash
  > group_list
  📋 登録済みグループ一覧:
     1. 88:77:66:55:44:33:22:11
  ```
- グループ削除：
  ```bash
  > group_unregister 88:77:66:55:44:33:22:11
  ✅ グループ 88:77:66:55:44:33:22:11 の削除リクエストを送信しました
  ```

#### （3）状態照会（APIクライアントによる実装）
インタラクティブ形式ではなくクライアントAPIコードを使用する場合、以下のインターフェースを呼び出せます。
```python
# サーバーに接続
success, msg = connect("127.0.0.1:9966")
# オンラインクライアントリストを照会
online_ids = list()
print("オンラインクライアントID:", online_ids)
# 作成済みグループを照会
groups = grouplist()
print("作成済みグループ:", groups)
```

### 4. クライアントAPI呼び出し例
クライアントAPIコードを`cakelib.py`として保存すると、他のPythonプログラムから呼び出せます。
```python
import cakelib as cake

# 1. サーバーに接続
success, msg = cake.connect("127.0.0.1:9966")
if not success:
    print("接続に失敗しました:", msg)
else:
    print("接続に成功しました。クライアントID:", msg)

# 2. メッセージ受信時コールバック関数の定義
def on_message(src_id, dest_id, message):
    print(f"メッセージを受信しました - 送信元: {src_id}, 宛先: {dest_id}, 内容: {message.decode('utf-8')}")

cake.set_callback(on_message)

# 3. ピアツーピアメッセージ送信
cake.send("aa:bb:cc:dd:ee:ff:11:22", "Hello from API")

# 4. ブロードキャストメッセージ送信
cake.broadcast("Broadcast from API")

# 5. グループ作成
group_id, msg = cake.registergroup(["aa:bb:cc:dd:ee:ff:11:22"])
if group_id:
    print("グループ作成に成功しました。ID:", group_id)
    # グループテキストメッセージ送信
    cake.groupsendtext(group_id, "Hello Group")

# 6. オンラインリスト照会
online_ids = cake.list()
print("オンラインクライアント:", online_ids)

# 7. 接続終了
# cake.close()
```

## 五、注意事項
1. **ID形式**
    クライアント/グループIDはいずれも8桁の2桁16進数（例：`aa:bb:cc:dd:ee:ff:11:22`）であり、形式を変更しないでください。
2. **接続安定性**
    クライアントはネットワーク切断/タイムアウト時に自動的に切断され、再接続時には新しいIDが割り当てられます。
3. **グループ解放**
    グループを作成したクライアントがオフラインになると、サーバーが当該クライアントの作成したすべてのグループを自動的に解放します。
4. **エンコーディング互換性**
    メッセージ内容はデフォルトでUTF-8エンコーディングを使用します。UTF-8以外の文字を送信すると文字化けが発生する場合があります。
5. **ポート競合**
    9966ポートが使用中の場合は、コード内の`cake_PORT`（サーバー）/クライアント接続パラメータを変更してください。

## 六、よくある問題
1. **クライアントが接続に失敗する**
    - サーバーが起動しているか、サーバーIP/ポートが正しいか確認
    - サーバーのファイアウォールが9966ポートを許可しているか確認
    - クライアントとサーバーがネットワーク上で到達可能か（pingで確認可能）確認
2. **メッセージは送信成功したが相手が受信しない**
    - 対象クライアントがオンラインでIDが正しいか確認
    - グループメッセージの場合は、対象グループが削除されていないか、受信者がグループメンバーであるか確認
3. **ハートビートタイムアウトによる切断**
    - ネットワークが安定しているか確認し、長時間のデータなし通信によるルーター側の切断を回避
    - コード内の`HEARTBEAT_INTERVAL`（ハートビート間隔）/`HEARTBEAT_TIMEOUT`（タイムアウト時間）パラメータを調整可能