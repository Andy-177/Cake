# CakeLib 開発ドキュメント（日本語訳）
## 1. 概要
CakeLib は TCP プロトコルを基盤としたクライアント通信用ライブラリで、Cake サーバーとの接続確立、ピアツーピアメッセージ通信、ブロードキャストメッセージ、グループ通信機能を実現するために使用されます。
本ライブラリは、ソケット通信、ハートビートによる接続維持、パケットのエンコード・デコードなどの低レイヤー処理をカプセル化し、簡単に使用できる API インターフェースを提供します。

### コア機能
- Cake サーバーへの TCP 接続の自動確立と、クライアント固有 ID の自動取得
- ハートビートによる接続維持機構、接続状態の自動検出
- ピアツーピアメッセージ送信、ブロードキャストメッセージ送信に対応
- グループの作成・削除、グループメッセージ送信に対応
- オンラインクライアント一覧、登録済みグループ一覧の取得に対応
- 非同期メッセージ受信コールバック機構

## 2. 環境依存
- Python バージョン：3.6 以上
- 依存ライブラリ：なし（Python 標準ライブラリのみ使用）
- ネットワーク要件：クライアントが Cake サーバーの IP およびポートにアクセス可能であること

## 3. データ構造と定数の説明
### 3.1 パケット構造
サーバーとの送受信パケットはすべて統一フォーマットに従います。

| フィールド     | 型         | バイト長 | 説明                                     |
|----------------|------------|----------|------------------------------------------|
| パケット種別   | uint8      | 1        | パケットの用途を識別（ハートビート、メッセージ、グループ登録など） |
| ボディ長       | uint32     | 4        | ビッグエンディアン（!）、ボディ部のバイト長 |
| ボディ         | bytes      | 可変     | 実際の業務データ。ボディ長フィールドと一致 |

### 3.2 コア定数
| 定数名              | 値・説明                                      |
|---------------------|-----------------------------------------------|
| BUFFER_SIZE         | 4096、受信データのバッファサイズ              |
| ID_LENGTH           | 8、クライアント/グループ ID のバイト長        |
| BROADCAST_ID        | b'\xff' * 8、ブロードキャスト用ターゲット ID  |
| SERVER_RESERVED_ID  | b'\x00' * 8、サーバー予約 ID                  |
| HEARTBEAT_INTERVAL  | 5、ハートビート送信間隔（秒）                 |
| HEARTBEAT_TIMEOUT   | 20、ハートビートタイムアウト時間（秒）         |
| PACKET_HEARTBEAT    | 0x04、ハートビートパケット識別子              |
| PACKET_ID_REQUEST   | 0x01、ID 要求パケット識別子                   |
| PACKET_ID_RESPONSE  | 0x02、ID 応答パケット識別子                   |
| PACKET_MESSAGE      | 0x03、業務メッセージパケット識別子            |
| PACKET_GROUP_REGISTER | 0x05、グループ登録パケット識別子           |
| PACKET_GROUP_RESPONSE | 0x07、グループ ID 応答パケット識別子       |
| PACKET_GROUP_MESSAGE | 0x06、グループメッセージパケット識別子       |
| PACKET_GROUP_UNREGISTER | 0x08、グループ削除パケット識別子       |

### 3.3 ID フォーマット
クライアント/グループ ID は**8 組の 2 桁 16 進数**からなる文字列形式を使用します。
例：`a1:b2:c3:d4:e5:f6:78:90`
これは内部的に 8 バイトのバイナリデータに対応します。

## 4. 基本 API インターフェース
### 4.1 connect(server_addr: str) -> Tuple[bool, str]
**機能**：Cake サーバーに接続し、クライアント ID の取得を完了します。
**引数**：
- `server_addr`：サーバーアドレス。2 形式をサポート
  - フル形式：`ip:port`（例：`127.0.0.1:9966`、`xxx.abc.xyz:9966`）
  - 簡略形式：IP/ドメインのみ（例：`127.0.0.1`）。デフォルトポート 9966 を使用
**戻り値**：
- タプル `(成功可否, メッセージ/エラー情報)`
  - 成功：`(True, クライアントID文字列)`
  - 失敗：`(False, エラー詳細)`
**使用例**：
```python
import cakelib

# サーバーに接続
success, msg = cakelib.connect("127.0.0.1:9966")
if success:
    print(f"接続成功、クライアントID：{msg}")
else:
    print(f"接続失敗：{msg}")
```

### 4.2 send(target_id: str, message: Union[str, bytes]) -> Tuple[bool, str]
**機能**：指定した ID のクライアントにメッセージを送信します。
**引数**：
- `target_id`：送信先クライアント ID 文字列（例：`a1:b2:c3:d4:e5:f6:78:90`）
- `message`：送信メッセージ。文字列（自動的に UTF-8 エンコード）またはバイト列を指定
**戻り値**：
- タプル `(成功可否, メッセージ/エラー情報)`
**使用例**：
```python
# テキストメッセージ送信
success, msg = cakelib.send("a1:b2:c3:d4:e5:f6:78:90", "こんにちは、テストメッセージです")
# バイト列送信
success, msg = cakelib.send("a1:b2:c3:d4:e5:f6:78:90", b"\x01\x02\x03\x04")
```

### 4.3 broadcast(message: Union[str, bytes]) -> Tuple[bool, str]
**機能**：すべてのオンラインクライアントにブロードキャストメッセージを送信します。
**引数**：
- `message`：送信メッセージ。文字列またはバイト列
**戻り値**：
- タプル `(成功可否, メッセージ/エラー情報)`
**使用例**：
```python
success, msg = cakelib.broadcast("全クライアントに通知、これはブロードキャストメッセージです")
```

### 4.4 getid() -> Tuple[Optional[str], str]
**別名**：`get_id()`
**機能**：現在のクライアント ID 文字列を取得します。
**戻り値**：
- タプル `(クライアントID文字列/None, エラー情報/空文字)`
  - 成功：`(ID文字列, "")`
  - 失敗：`(None, エラー詳細)`
**使用例**：
```python
client_id, err = cakelib.getid()
if client_id:
    print(f"現在のクライアントID：{client_id}")
else:
    print(f"ID取得失敗：{err}")
```

### 4.5 set_callback(callback) -> None
**機能**：メッセージ受信時のコールバック関数を設定します。他クライアントまたはサーバーからメッセージを受信すると自動的に実行されます。
**引数**：
- `callback`：コールバック関数。形式は `callback(src_id: str, dest_id: str, message: bytes)`
  - `src_id`：送信元 ID 文字列
  - `dest_id`：送信先 ID 文字列（自クライアント ID）
  - `message`：受信したメッセージのバイト列
**使用例**：
```python
# コールバック関数定義
def on_message(src_id, dest_id, message):
    print(f"{src_id} からのメッセージ：{message.decode('utf-8')}")

# コールバック設定
cakelib.set_callback(on_message)
```

### 4.6 close() -> None
**機能**：サーバーとの接続を閉じ、ハートビートスレッドと受信スレッドを停止します。
**使用例**：
```python
cakelib.close()
```

## 5. グループ関連 API インターフェース
### 5.1 registergroup(member_ids: List[str]) -> Tuple[Optional[str], str]
**機能**：新規グループを登録し、グループメンバーを指定します。
**引数**：
- `member_ids`：グループメンバー ID リスト（文字列形式）
  例：`["11:11:11:11:11:11:11:11", "22:22:22:22:22:22:22:22"]`
**戻り値**：
- タプル `(グループID文字列/None, エラー情報/成功メッセージ)`
  - 成功：`(グループID文字列, "グループ登録成功、ID: xxx")`
  - 失敗：`(None, エラー詳細)`
**使用例**：
```python
# グループメンバー定義
members = ["a1:b2:c3:d4:e5:f6:78:90", "00:11:22:33:44:55:66:77"]
# グループ登録
group_id, msg = cakelib.registergroup(members)
if group_id:
    print(f"グループ登録成功、ID：{group_id}")
else:
    print(f"グループ登録失敗：{msg}")
```

### 5.2 groupsend(group_id: str, data: bytes) -> Tuple[bool, str]
**別名**：`group_send()`
**機能**：指定したグループにバイナリデータを送信します。
**引数**：
- `group_id`：グループ ID 文字列
- `data`：送信するバイナリデータ
**戻り値**：
- タプル `(成功可否, メッセージ/エラー情報)`
**使用例**：
```python
# グループにバイナリデータ送信
success, msg = cakelib.groupsend("88:88:88:88:88:88:88:88", b"\x00\x01\x02\x03")
```

### 5.3 groupsendtext(group_id: str, text: str) -> Tuple[bool, str]
**別名**：`group_send_text()`
**機能**：指定したグループにテキストメッセージを送信します（自動的に UTF-8 エンコード）。
**引数**：
- `group_id`：グループ ID 文字列
- `text`：送信するテキスト文字列
**戻り値**：
- タプル `(成功可否, メッセージ/エラー情報)`
**使用例**：
```python
# グループにテキストメッセージ送信
success, msg = cakelib.groupsendtext("88:88:88:88:88:88:88:88", "グループメンバーの皆さん、こんにちは")
```

### 5.4 unregistergroup(group_id: str) -> Tuple[bool, str]
**別名**：`unregister_group()`
**機能**：指定したグループを削除します。
**引数**：
- `group_id`：削除するグループ ID 文字列
**戻り値**：
- タプル `(成功可否, メッセージ/エラー情報)`
**使用例**：
```python
success, msg = cakelib.unregistergroup("88:88:88:88:88:88:88:88")
if success:
    print(f"グループ削除成功：{msg}")
else:
    print(f"グループ削除失敗：{msg}")
```

### 5.5 grouplist() -> Optional[Dict]
**別名**：`group_list()`
**機能**：現在のクライアントが登録したすべてのグループ一覧を取得します。
**戻り値**：
- 成功：辞書 `{グループID: [メンバーIDリスト]}`
  ```python
  {
      "88:88:88:88:88:88:88:88": ["a1:b2:c3:d4:e5:f6:78:90", "00:11:22:33:44:55:66:77"],
      "99:99:99:99:99:99:99:99": ["a1:b2:c3:d4:e5:f6:78:90"]
  }
  ```
- 失敗/グループなし：`None`
**使用例**：
```python
groups = cakelib.grouplist()
if groups:
    print("登録済みグループ：")
    for gid, members in groups.items():
        print(f"グループ {gid} メンバー：{members}")
else:
    print("グループ未登録、または取得失敗")
```

### 5.6 list() -> List[str]
**別名**：`online_list()`
**機能**：すべてのオンラインクライアント ID リストを取得します。
**戻り値**：
- 成功：オンラインクライアント ID 文字列リスト（空リストはオンラインなしを意味）
- 失敗：空リスト
**使用例**：
```python
online_ids = cakelib.list()
print(f"オンラインクライアント数：{len(online_ids)}")
for client_id in online_ids:
    print(f"オンラインクライアント：{client_id}")
```

## 6. 完全使用例
```python
import cakelib
import time

# メッセージコールバック関数定義
def message_callback(src_id, dest_id, message):
    """受信メッセージの処理"""
    try:
        # テキストとしてデコード試行
        text = message.decode('utf-8')
        print(f"\nメッセージ受信 - 送信元：{src_id} | 内容：{text}")
    except:
        # バイナリメッセージ
        print(f"\nバイナリメッセージ受信 - 送信元：{src_id} | 長さ：{len(message)} バイト")

def main():
    # 1. サーバー接続
    server_addr = "127.0.0.1:9966"
    success, msg = cakelib.connect(server_addr)
    if not success:
        print(f"サーバー接続失敗：{msg}")
        return
    print(f"接続成功、クライアントID：{msg}")

    # 2. メッセージコールバック設定
    cakelib.set_callback(message_callback)

    # 3. 自クライアントID取得
    client_id, err = cakelib.getid()
    print(f"自クライアントID確認：{client_id}")

    # 4. オンラインクライアント一覧取得
    online_ids = cakelib.list()
    print(f"オンラインクライアント一覧：{online_ids}")

    # 5. グループ登録（他クライアントがオンラインの場合）
    if len(online_ids) > 1:
        # 自分を除外し、他クライアントをメンバーに指定
        other_member = [id for id in online_ids if id != client_id][0]
        group_id, msg = cakelib.registergroup([client_id, other_member])
        if group_id:
            print(f"グループ登録成功、ID：{group_id}")
            
            # グループテキストメッセージ送信
            success, msg = cakelib.groupsendtext(group_id, "グループテストメッセージです！")
            print(f"グループメッセージ送信結果：{msg}")
            
            # グループ一覧取得
            groups = cakelib.grouplist()
            print(f"登録済みグループ：{groups}")
            
            # グループ削除（任意）
            # success, msg = cakelib.unregistergroup(group_id)
            # print(f"グループ削除結果：{msg}")

    # 6. ピアツーピアメッセージ送信（他クライアントがオンラインの場合）
    if len(online_ids) > 1:
        target_id = online_ids[0]
        if target_id != client_id:
            success, msg = cakelib.send(target_id, "こんにちは、ピアツーピアテストメッセージです！")
            print(f"P2Pメッセージ送信結果：{msg}")

    # 7. ブロードキャスト送信
    success, msg = cakelib.broadcast("ブロードキャストメッセージ、全クライアント受信可能！")
    print(f"ブロードキャスト送信結果：{msg}")

    # 8. 接続維持、メッセージ待ち受け
    try:
        print("\nクライアント起動中、メッセージ待ち（Ctrl+C で終了）...")
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nユーザー終了、接続を閉じます...")
    finally:
        # 9. 接続クローズ
        cakelib.close()
        print("接続を閉じました")

if __name__ == "__main__":
    main()
```

## 7. 例外処理と注意事項
### 7.1 例外シナリオ
1. **接続失敗**
   - サーバーアドレス形式エラー（ポートが数値でないなど）
   - サーバーに到達不可（ネットワーク異常、サーバー未起動）
   - 接続タイムアウト（10 秒以内に確立できず）
   - サーバーから無効な ID 応答パケットを受信

2. **メッセージ送信失敗**
   - サーバー未接続（`connect()` 未呼び出し、または切断済み）
   - 送信先 ID フォーマット異常（8 組 2 桁 16 進数形式でない）
   - ネットワーク切断（ハートビートタイムアウトによる自動切断）

3. **グループ操作失敗**
   - グループメンバー ID フォーマット異常
   - グループ登録/削除要求タイムアウト（10 秒以内に応答なし）
   - グループ ID が存在しない（削除・メッセージ送信時）

### 7.2 注意事項
1. すべての API 呼び出し前に、サーバーへの接続が成功していることを確認（`connect()` が `True` を返す）。未接続時は失敗を返します。
2. コールバック関数は極力簡潔に実装し、ブロックしないでください。コールバックは受信スレッド上で動作するため、ブロックするとメッセージ受信に影響します。
3. ハートビートタイムアウト（20 秒）が発生すると自動的に接続が閉じられます。再接続には `connect()` を再実行してください。
4. クライアント ID は切断後に無効となり、再接続時は新しい ID が割り当てられます。
5. 文字列メッセージはデフォルトで UTF-8 エンコードされます。他のエンコードを使用する場合は手動でバイト列を処理してください。
6. グループ登録後、原則として登録者のみが当該グループを削除可能です（サーバーロジックに依存）。
7. ブロードキャストメッセージは自分自身を含むすべてのオンラインクライアントに送信されます。
8. プログラム終了前に `close()` を呼び出し、リソースリークを防いでください。

## 8. 内部実装の説明（任意）
### 8.1 コアクラス `_CakeClient`
- 外部には公開されず、グローバルインスタンス `_global_client` を通じてサービスを提供
- コアメソッド：
  - `connect()`：接続確立、ID 取得、スレッド起動を処理
  - `_recv_messages()`：受信スレッドのメインロジック。パケット解析、コールバック呼び出し
  - `_heartbeat_loop()`：ハートビートスレッド。定期的にハートビートを送信し、状態を監視
  - 各種メッセージ/グループ操作メソッド：パケットのエンコード・デコードと送信処理をカプセル化

### 8.2 スレッドモデル
- 受信スレッド（`recv_thread`）：ブロッキングでサーバーからのデータを受信し、パケットを解析してコールバックを実行
- ハートビートスレッド（`heartbeat_thread`）：定期的にハートビートを送信し、接続状態を監視
- すべてのスレッドはデーモンスレッド（`daemon=True`）で動作し、メインプログラム終了時に自動的に終了

### 8.3 同期リクエスト処理
- サーバーからの応答待ちが必要な操作（グループ登録、グループ一覧取得、オンライン一覧取得など）には以下を使用：
  - `sync_response_lock`：応答データのスレッドセーフを保護
  - `sync_response_event`：応答待ち用イベント通知
  - タイムアウト機構（10 秒）により無限待機を防止