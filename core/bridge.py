import json
import socket
import time


def test_connection(host="localhost", port=8555, timeout=3):
    """Test connection to Unreal Engine bridge.

    Args:
        host: str - UE bridge host
        port: int - UE bridge port
        timeout: int - connection timeout in seconds

    Returns:
        tuple: (success: bool, message: str)
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()

        if result == 0:
            return (True, f"Connected to UE bridge at {host}:{port}")
        else:
            return (False, f"Cannot connect to {host}:{port}. Is UE running with bridge plugin?")
    except Exception as e:
        return (False, f"Connection error: {str(e)}")


def send_to_ue(payloads, settings):
    """Send payload data to Unreal Engine via WebSocket bridge.

    Args:
        payloads: list of dicts - payload data to send
        settings: ExportToUEPropertyGroup

    Returns:
        bool - success
    """
    host = settings.ue_host
    port = settings.ue_port

    # First test connection
    connected, msg = test_connection(host, port)
    if not connected:
        print(f"UE Bridge: {msg}")
        return False

    try:
        # Build the full message
        message = {
            "blender_version": f"{__import__('bpy').app.version_string}",
            "payloads": payloads,
            "export_count": len(payloads),
            "timestamp": time.time(),
        }

        # Send via TCP socket (simplified WebSocket-like protocol)
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10)
        sock.connect((host, port))

        # Send message length prefix + JSON data
        data = json.dumps(message).encode('utf-8')
        length = len(data)

        # 4-byte big-endian length prefix
        sock.sendall(length.to_bytes(4, byteorder='big'))
        sock.sendall(data)

        # Wait for acknowledgment
        ack = sock.recv(1024)
        if ack:
            ack_data = json.loads(ack.decode('utf-8'))
            print(f"UE Bridge: Received acknowledgment: {ack_data}")

        sock.close()
        return True

    except ConnectionRefusedError:
        print(f"UE Bridge: Connection refused at {host}:{port}")
        return False
    except socket.timeout:
        print(f"UE Bridge: Connection timed out at {host}:{port}")
        return False
    except Exception as e:
        print(f"UE Bridge error: {str(e)}")
        return False


def create_ue_bridge_plugin_instructions():
    """Return instructions for setting up the UE side bridge plugin.

    Returns:
        str - setup instructions
    """
    return """
To set up the UE Bridge connection:

1. In Unreal Engine, create a new Python plugin or use the Python script plugin
2. Add a TCP server that listens on the specified port (default: 8555)
3. The server should:
   - Accept connections from Blender
   - Read 4-byte length prefix + JSON payload
   - Parse the payload (mesh transforms, material mappings)
   - Create/Update actors in the level accordingly
   - Send back a JSON acknowledgment

Example UE Python bridge server code:
    import socket
    import json

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(('0.0.0.0', 8555))
    server.listen(5)

    while True:
        conn, addr = server.accept()
        length = int.from_bytes(conn.recv(4), 'big')
        data = conn.recv(length)
        payload = json.loads(data.decode('utf-8'))
        # Process payload...
        conn.sendall(json.dumps({"status": "ok"}).encode())
        conn.close()
"""
