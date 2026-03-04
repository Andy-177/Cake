# Cake-Protocol Specification
# 1. Protocol Overview
Cake-Protocol is an application-layer binary communication protocol based on TCP transmission, designed for client-server architecture. It supports peer-to-peer messaging, broadcast messaging, and group messaging, with a built-in heartbeat keep-alive mechanism to ensure connection stability.

## 1.1 Protocol Design Goals
- Lightweight: Binary format, efficient parsing, low overhead
- Reliable: Message ordering and losslessness guaranteed by TCP
- Extensible: Fixed header + variable body structure for easy addition of new message types
- High availability: Built-in heartbeat mechanism for connection status detection

## 1.2 Core Features
- Client ID Assignment: The server assigns a unique 8-byte ID to each connected client
- Peer-to-Peer Communication: Directed message transmission between clients based on ID
- Broadcast Communication: Send messages to all online clients
- Group Communication: Support group creation/deletion and in-group message broadcasting
- Heartbeat Keep-Alive: Timed heartbeat detection, automatic disconnection of abnormal connections

# 2. Basic Data Format
## 2.1 Byte Order
All multi-byte data uses **network byte order (Big-Endian)**.

## 2.2 Basic Type Definitions
| Type | Description | Byte Length | Format Note |
|------|-------------|-------------|-------------|
| uint8 | Unsigned 8-bit integer | 1 | Packet type identifier |
| uint32 | Unsigned 32-bit integer | 4 | Body length |
| bytes[8] | 8-byte binary data | 8 | Client ID / Group ID / Broadcast identifier |
| bytes[n] | Variable-length binary data | n | Message content / member list (n ≥ 0) |

## 2.3 Fixed Identifier Definitions
| Identifier Name | Binary Value | Description |
|-----------------|--------------|-------------|
| Broadcast ID | 0xff 0xff … 0xff | 8-byte all 0xff, used for broadcast messages |
| Client ID Length | 8 bytes | All client IDs are fixed at 8 bytes |
| Group ID Length | 8 bytes | All group IDs are fixed at 8 bytes |

# 3. General Packet Structure
All Cake-Protocol packets follow the **fixed header + variable body** structure:

| Field | Type | Byte Length | Note |
|-------|------|-------------|------|
| PacketType | uint8 | 1 | Packet type (see 3.1) |
| BodyLength | uint32 | 4 | Byte length of the body part |
| Body | bytes[] | Variable | Packet body (varies by type) |

**Total header length is fixed at 5 bytes (1+4)**. Body length is specified by the BodyLength field, valid range: 0 ≤ BodyLength ≤ 65535 (recommended max 4096).

## 3.1 Packet Type Definitions (PacketType)
| Type Value | Name | Identifier | Usage |
|------------|------|-------------|-------|
| 0x01 | ID Request | ID_REQUEST | Client requests ID assignment from server |
| 0x02 | ID Response | ID_RESPONSE | Server returns unique client ID |
| 0x03 | Peer/Broadcast Business | BUSINESS | Send peer-to-peer or broadcast messages |
| 0x04 | Heartbeat | HEARTBEAT | Heartbeat detection (request/response) |
| 0x05 | Group Register | GROUP_REGISTER | Client requests group creation |
| 0x06 | Group Business | GROUP_BUSINESS | Send group messages |
| 0x07 | Group ID Response | GROUP_RESPONSE | Server returns created group ID |
| 0x08 | Group Unregister | GROUP_UNREGISTER | Client requests group deletion |

# 4. Detailed Packet Formats
## 4.1 ID Request Packet (0x01)
- **Purpose**: Client requests a unique ID from the server after successful connection
- **PacketType**: 0x01
- **BodyLength**: 0 (no body)
- **Body**: Empty
- **Example**:
```plain text
01 00 00 00 00
```

## 4.2 ID Response Packet (0x02)
- **Purpose**: Server assigns and returns a unique 8-byte client ID
- **PacketType**: 0x02
- **BodyLength**: 8
- **Body Structure**:

| Field | Type | Byte Length | Note |
|-------|------|-------------|------|
| ClientID | bytes[8] | 8 | Unique client ID |

- **Example**:
```plain text
02 00 00 00 08 a1 b2 c3 d4 e5 f6 78 90
```
(where `a1 b2 c3 d4 e5 f6 78 90` is the assigned client ID)

## 4.3 Peer-to-Peer / Broadcast Business Packet (0x03)
- **Purpose**: Client sends peer-to-peer or broadcast messages
- **PacketType**: 0x03
- **BodyLength**: 16 + message length (8+8+message bytes)
- **Body Structure**:

| Field | Type | Byte Length | Note |
|-------|------|-------------|------|
| SrcID | bytes[8] | 8 | Sender client ID |
| DestID | bytes[8] | 8 | Receiver ID (all 0xff for broadcast) |
| Message | bytes[] | Variable | Message content (UTF-8 encoded) |

- **Example**:
Sender ID: `a1 b2 c3 d4 e5 f6 78 90`, Receiver ID: `ff ff ff ff ff ff ff ff` (broadcast), Message: `hello`
```plain text
03 00 00 00 15 a1 b2 c3 d4 e5 f6 78 90 ff ff ff ff ff ff ff ff 68 65 6c 6c 6f
```
(BodyLength = 21, 16+5=21)

## 4.4 Heartbeat Packet (0x04)
- **Purpose**: Client sends periodic heartbeat; server echoes the same packet as response
- **PacketType**: 0x04
- **BodyLength**: 0 (no body)
- **Body**: Empty
- **Example**:
```plain text
04 00 00 00 00
```

## 4.5 Group Register Packet (0x05)
- **Purpose**: Client requests group creation with a member list
- **PacketType**: 0x05
- **BodyLength**: 8 × number of members
- **Body Structure**:

| Field | Type | Byte Length | Note |
|-------|------|-------------|------|
| MemberIDs | bytes[8]*N | 8×N | N client IDs of group members |

- **Example**:
Member 1 ID: `a1 b2 c3 d4 e5 f6 78 90`, Member 2 ID: `01 02 03 04 05 06 07 08`
```plain text
05 00 00 00 10 a1 b2 c3 d4 e5 f6 78 90 01 02 03 04 05 06 07 08
```
(BodyLength = 16, 8×2=16)

## 4.6 Group Business Packet (0x06)
- **Purpose**: Client sends message to a specified group
- **PacketType**: 0x06
- **BodyLength**: 16 + message length (8+8+message bytes)
- **Body Structure**:

| Field | Type | Byte Length | Note |
|-------|------|-------------|------|
| SrcID | bytes[8] | 8 | Sender client ID |
| GroupID | bytes[8] | 8 | Target group ID |
| Message | bytes[] | Variable | Message content (UTF-8 encoded) |

- **Example**:
Sender ID: `a1 b2 c3 d4 e5 f6 78 90`, Group ID: `99 88 77 66 55 44 33 22`, Message: `hi group`
```plain text
06 00 00 00 19 a1 b2 c3 d4 e5 f6 78 90 99 88 77 66 55 44 33 22 68 69 20 67 72 6f 75 70
```
(BodyLength = 25, 16+9=25)

## 4.7 Group ID Response Packet (0x07)
- **Purpose**: Server returns unique 8-byte group ID after creation
- **PacketType**: 0x07
- **BodyLength**: 8
- **Body Structure**:

| Field | Type | Byte Length | Note |
|-------|------|-------------|------|
| GroupID | bytes[8] | 8 | Unique group ID |

- **Example**:
```plain text
07 00 00 00 08 99 88 77 66 55 44 33 22
```

## 4.8 Group Unregister Packet (0x08)
- **Purpose**: Client requests deletion of a specified group
- **PacketType**: 0x08
- **BodyLength**: 8
- **Body Structure**:

| Field | Type | Byte Length | Note |
|-------|------|-------------|------|
| GroupID | bytes[8] | 8 | Group ID to be deleted |

- **Example**:
```plain text
08 00 00 00 08 99 88 77 66 55 44 33 22
```

# 5. Communication Flow Specifications
## 5.1 Client Connection Flow
1. Client creates TCP socket and connects to server at specified IP and port
2. Client sends ID Request packet (0x01)
3. Server receives packet, assigns unique 8-byte ClientID, returns ID Response packet (0x02)
4. Client parses and stores ClientID, disables socket timeout
5. Client starts heartbeat thread (periodic heartbeat sending) and receive thread (listening for server messages)

## 5.2 Heartbeat Keep-Alive Flow
1. Client sends heartbeat packet (0x04) every N seconds (recommended: 5s)
2. Server immediately echoes the same heartbeat packet as response
3. Client records timestamp of last heartbeat response
4. If no heartbeat response received within M seconds (recommended: 20s), client judges connection abnormal and closes TCP
5. If no heartbeat received from client within M seconds, server closes TCP

## 5.3 Peer-to-Peer Message Sending Flow
1. Sender constructs peer-to-peer business packet (0x03), fills DestID with receiver ClientID
2. Sender sends packet to server
3. Server parses packet and finds online client by DestID
4. Server forwards packet to receiver
5. Receiver parses packet and displays message

## 5.4 Broadcast Message Sending Flow
1. Sender constructs broadcast business packet (0x03), fills DestID with all 0xff
2. Sender sends packet to server
3. Server parses and identifies broadcast, forwards to all online clients
4. All online clients parse and display message

## 5.5 Group Creation & Messaging Flow
### 5.5.1 Group Creation
1. Client constructs Group Register packet (0x05) with member ClientID list
2. Client sends to server
3. Server creates group, assigns unique 8-byte GroupID, returns Group ID Response packet (0x07)
4. Client stores GroupID, registration complete

### 5.5.2 Group Message Sending
1. Client constructs Group Business packet (0x06) with sender ClientID and target GroupID
2. Client sends to server
3. Server parses packet and finds member list by GroupID
4. Server forwards packet to all group members
5. Members parse and display message

### 5.5.3 Group Deletion
1. Client constructs Group Unregister packet (0x08) with target GroupID
2. Client sends to server
3. Server removes group data, deletion complete

# 6. Exception Handling Specifications
## 6.1 Packet Parsing Exceptions
- If header length < 5 bytes: discard current data, wait for subsequent concatenation
- If BodyLength does not match actual body length: discard packet, log error
- If PacketType is unknown: discard packet, log error

## 6.2 Connection Exceptions
- No ID response within 10s: disconnect, prompt connection failure
- Heartbeat timeout: client/server actively closes TCP
- Connection error during message sending: shut down client, clean resources

## 6.3 Business Exceptions
- Message sent before ClientID assigned: reject, prompt not connected
- Invalid member ID format during group registration: return failure, prompt format error
- Group message sent to non-existent group: reject forwarding, prompt group deleted/non-existent

# 7. Protocol Extension Specifications
## 7.1 New Packet Types
- New PacketType values start from 0x09 to avoid conflict
- New packets must follow fixed header + variable body structure
- New types must document purpose, body structure, and interaction flow

## 7.2 Field Extension
- Extend existing body fields by appending at end, preserve original field order
- Update BodyLength calculation after extension to maintain compatibility

> Note: Some content may be AI-generated.