# CakeLib Development Documentation
## 1. Overview
CakeLib is a TCP-based client communication library for establishing connections with the Cake server, performing peer-to-peer messaging, broadcasting messages, and implementing group communication.
It encapsulates low-level socket communication, heartbeat keep-alive, packet encoding/decoding, and provides a clean and easy-to-use API.

### Core Features
- Automatically establishes a TCP connection with the Cake server and obtains a unique client ID
- Heartbeat keep-alive mechanism with automatic connection status detection
- Supports peer-to-peer messaging and broadcast messaging
- Supports group creation, unregistration, and group messaging
- Supports retrieving online client list and registered group list
- Asynchronous message reception callback mechanism

## 2. Dependencies
- Python version: 3.6 or higher
- Libraries: None (uses only Python standard libraries)
- Network requirement: Client must access the Cake server’s IP and port

## 3. Data Structures and Constants
### 3.1 Packet Structure
All packets exchanged with the server follow a unified format:

| Field          | Type       | Length (bytes) | Description |
|----------------|------------|----------------|-------------|
| Packet Type    | uint8      | 1              | Identifies packet purpose (heartbeat, message, group registration, etc.) |
| Body Length    | uint32     | 4              | Big-endian (!), byte length of the payload |
| Body           | bytes      | Variable       | Actual business data, matching Body Length |

### 3.2 Core Constants

| Constant Name         | Value / Description |
|-----------------------|---------------------|
| BUFFER_SIZE           | 4096, receive buffer size |
| ID_LENGTH             | 8, byte length of client/group ID |
| BROADCAST_ID          | b'\xff' * 8, target ID for broadcast messages |
| SERVER_RESERVED_ID    | b'\x00' * 8, server reserved ID |
| HEARTBEAT_INTERVAL    | 5, heartbeat interval (seconds) |
| HEARTBEAT_TIMEOUT     | 20, heartbeat timeout (seconds) |
| PACKET_HEARTBEAT      | 0x04, heartbeat packet type |
| PACKET_ID_REQUEST     | 0x01, ID request packet type |
| PACKET_ID_RESPONSE    | 0x02, ID response packet type |
| PACKET_MESSAGE        | 0x03, business message packet type |
| PACKET_GROUP_REGISTER | 0x05, group registration packet type |
| PACKET_GROUP_RESPONSE | 0x07, group ID response packet type |
| PACKET_GROUP_MESSAGE  | 0x06, group message packet type |
| PACKET_GROUP_UNREGISTER | 0x08, group unregistration packet type |

### 3.3 ID Format
Client and group IDs use a string format of **8 pairs of two-digit hexadecimal numbers**, e.g.:
`a1:b2:c3:d4:e5:f6:78:90`, corresponding to an underlying 8-byte binary value.

## 4. Basic API
### 4.1 connect(server_addr: str) -> Tuple[bool, str]
**Function**: Connects to the Cake server and obtains a client ID.

**Parameters**:
- `server_addr`: Server address, two formats supported:
  - Full: `ip:port` (e.g., `127.0.0.1:9966`, `xxx.abc.xyz:9966`)
  - Short: IP/domain only (e.g., `127.0.0.1`), default port 9966

**Return**:
- Tuple `(success, message/error)`:
  - Success: `(True, client_id_string)`
  - Failure: `(False, error_description)`

**Example**:
```python
import cakelib

success, msg = cakelib.connect("127.0.0.1:9966")
if success:
    print(f"Connected. Client ID: {msg}")
else:
    print(f"Connection failed: {msg}")
```

### 4.2 send(target_id: str, message: Union[str, bytes]) -> Tuple[bool, str]
**Function**: Sends a message to the specified client ID.

**Parameters**:
- `target_id`: Target client ID string (format `a1:b2:c3:d4:e5:f6:78:90`)
- `message`: String (auto-encoded to UTF-8 bytes) or bytes

**Return**: `(success, message/error)`

**Example**:
```python
success, msg = cakelib.send("a1:b2:c3:d4:e5:f6:78:90", "Hello, this is a test message")
success, msg = cakelib.send("a1:b2:c3:d4:e5:f6:78:90", b"\x01\x02\x03\x04")
```

### 4.3 broadcast(message: Union[str, bytes]) -> Tuple[bool, str]
**Function**: Broadcasts a message to all online clients.

**Parameters**:
- `message`: String or bytes

**Return**: `(success, message/error)`

**Example**:
```python
success, msg = cakelib.broadcast("Notice to all clients: this is a broadcast")
```

### 4.4 getid() -> Tuple[Optional[str], str]
**Alias**: `get_id()`

**Function**: Gets the current client ID string.

**Return**:
- `(client_id/None, error/empty string)`
  - Success: `(id_str, "")`
  - Failure: `(None, error)`

**Example**:
```python
client_id, err = cakelib.getid()
if client_id:
    print(f"Current ID: {client_id}")
else:
    print(f"Failed to get ID: {err}")
```

### 4.5 set_callback(callback) -> None
**Function**: Sets the message reception callback, triggered when a message is received.

**Parameters**:
- `callback`: Function with signature `callback(src_id: str, dest_id: str, message: bytes)`
  - `src_id`: sender ID string
  - `dest_id`: receiver ID string (current client)
  - `message`: received bytes

**Example**:
```python
def on_message(src_id, dest_id, message):
    print(f"From {src_id}: {message.decode('utf-8')}")

cakelib.set_callback(on_message)
```

### 4.6 close() -> None
**Function**: Closes the connection, stops heartbeat and receive threads.

**Example**:
```python
cakelib.close()
```

## 5. Group-Related API
### 5.1 registergroup(member_ids: List[str]) -> Tuple[Optional[str], str]
**Function**: Registers a new group with a member list.

**Parameters**:
- `member_ids`: List of client ID strings

**Return**:
- `(group_id/None, info/error)`
  - Success: `(group_id, "Group registered successfully, ID: xxx")`
  - Failure: `(None, error)`

**Example**:
```python
members = ["a1:b2:c3:d4:e5:f6:78:90", "00:11:22:33:44:55:66:77"]
group_id, msg = cakelib.registergroup(members)
if group_id:
    print(f"Group created: {group_id}")
```

### 5.2 groupsend(group_id: str, data: bytes) -> Tuple[bool, str]
**Alias**: `group_send()`

**Function**: Sends binary data to a group.

**Parameters**:
- `group_id`: group ID string
- `data`: bytes to send

**Return**: `(success, message/error)`

**Example**:
```python
success, msg = cakelib.groupsend("88:88:88:88:88:88:88:88", b"\x00\x01\x02\x03")
```

### 5.3 groupsendtext(group_id: str, text: str) -> Tuple[bool, str]
**Alias**: `group_send_text()`

**Function**: Sends UTF-8 text to a group.

**Parameters**:
- `group_id`: group ID string
- `text`: string message

**Return**: `(success, message/error)`

**Example**:
```python
success, msg = cakelib.groupsendtext("88:88:88:88:88:88:88:88", "Hello group!")
```

### 5.4 unregistergroup(group_id: str) -> Tuple[bool, str]
**Alias**: `unregister_group()`

**Function**: Unregisters a group.

**Parameters**:
- `group_id`: group ID string

**Return**: `(success, message/error)`

**Example**:
```python
success, msg = cakelib.unregistergroup("88:88:88:88:88:88:88:88")
```

### 5.5 grouplist() -> Optional[Dict]
**Alias**: `group_list()`

**Function**: Gets all groups registered by the current client.

**Return**:
- Success: `{ group_id: [member_ids] }`
- Failure / no groups: `None`

**Example**:
```python
groups = cakelib.grouplist()
if groups:
    for gid, members in groups.items():
        print(f"Group {gid}: {members}")
```

### 5.6 list() -> List[str]
**Alias**: `online_list()`

**Function**: Gets all online client IDs.

**Return**: list of client ID strings (empty if none or failed)

**Example**:
```python
online_ids = cakelib.list()
print(f"Online clients: {len(online_ids)}")
```

## 6. Complete Usage Example
```python
import cakelib
import time

def message_callback(src_id, dest_id, message):
    try:
        text = message.decode('utf-8')
        print(f"\nFrom {src_id}: {text}")
    except:
        print(f"\nBinary from {src_id}, length: {len(message)} bytes")

def main():
    server_addr = "127.0.0.1:9966"
    success, msg = cakelib.connect(server_addr)
    if not success:
        print(f"Connect failed: {msg}")
        return
    print(f"Connected, ID: {msg}")

    cakelib.set_callback(message_callback)

    client_id, err = cakelib.getid()
    print(f"Confirmed ID: {client_id}")

    online_ids = cakelib.list()
    print(f"Online: {online_ids}")

    if len(online_ids) > 1:
        others = [uid for uid in online_ids if uid != client_id]
        if others:
            group_id, msg = cakelib.registergroup([client_id, others[0]])
            if group_id:
                print(f"Group ID: {group_id}")
                cakelib.groupsendtext(group_id, "Hello group!")
                groups = cakelib.grouplist()
                print(f"Groups: {groups}")

    if len(online_ids) > 1:
        target = online_ids[0]
        if target != client_id:
            cakelib.send(target, "Hello P2P!")

    cakelib.broadcast("Broadcast from client")

    try:
        print("\nRunning... Ctrl+C to exit")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nExiting...")
    finally:
        cakelib.close()
        print("Closed")

if __name__ == "__main__":
    main()
```

## 7. Exception Handling & Notes
### 7.1 Common Error Scenarios
1. **Connection failure**:
   - Invalid server address format
   - Server unreachable
   - Connection timeout (10s)
   - Invalid ID response from server

2. **Message send failure**:
   - Not connected
   - Invalid ID format
   - Network disconnection (heartbeat timeout)

3. **Group operation failure**:
   - Invalid member ID format
   - Request timeout (10s)
   - Group does not exist

### 7.2 Important Notes
1. All APIs require a successful `connect()` first.
2. Callbacks should be lightweight to avoid blocking the receive thread.
3. Heartbeat timeout (20s) closes the connection automatically; reconnect with `connect()`.
4. Client ID becomes invalid after disconnection; a new ID is assigned on reconnection.
5. Strings are UTF-8 encoded by default.
6. Only the creator can unregister a group (server-dependent).
7. Broadcasts are sent to all online clients including yourself.
8. Call `close()` before exiting to avoid resource leaks.

## 8. Internal Implementation (Optional)
### 8.1 Core Class `_CakeClient`
- Not exposed externally; used via global instance `_global_client`
- Key methods:
  - `connect()`: connection, ID assignment, thread start
  - `_recv_messages()`: receive loop, packet parsing, callback
  - `_heartbeat_loop()`: heartbeat and timeout detection
  - Message/group helpers: packet encode/decode and send

### 8.2 Thread Model
- `recv_thread`: blocking receive, packet parsing
- `heartbeat_thread`: periodic heartbeat and status check
- All threads are daemon threads and exit with the main program

### 8.3 Synchronous Request Handling
For operations requiring server response (group register, group list, online list):
- `sync_response_lock`: thread-safe response access
- `sync_response_event`: wait for response signal
- 10-second timeout to prevent hanging