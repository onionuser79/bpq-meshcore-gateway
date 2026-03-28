# BPQ32-MeshCore Gateway

A Python gateway that bridges a **MeshCore private LoRa channel** to a **BPQ32 packet radio node** via Telnet, allowing MeshCore mesh network users to access BPQ Chat over LoRa.

## How It Works

```
MeshCore LoRa Channel  <-->  Gateway (Python)  <-->  BPQ32 Telnet
   (Heltec V3 etc.)          serial USB               TCP port
```

1. A MeshCore user sends `username/password` on the configured private channel
2. The gateway opens a Telnet session to BPQ32 and authenticates
3. BPQ Chat mode is entered automatically
4. All messages are relayed bidirectionally between the channel and BPQ Chat
5. The user sends `DISCONNECT` to end the session

**One connection at a time** is enforced — other users see a "busy" message.

## Prerequisites

- **Debian 12+** (or any Linux with Python 3.10+)
- A MeshCore companion node connected via USB serial (e.g. Heltec V3)
- A BPQ32 node with TelnetServer enabled

### Install

```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv
sudo usermod -aG dialout $USER   # for serial port access
# log out and back in after the group change

cd /opt
sudo mkdir bpq-meshcore-gateway
sudo chown $USER:$USER bpq-meshcore-gateway
git clone https://github.com/YOUR_USER/bpq-meshcore-gateway.git
cd bpq-meshcore-gateway

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Copy the example config and edit it:

```bash
cp config.yaml.example config.yaml
nano config.yaml
```

```yaml
gateway:
  callsign: "IW2OHX-7"       # Gateway identity (for logging)
  idle_timeout: 300           # Seconds before auto-disconnect

bpq:
  host: "192.168.1.201"      # BPQ32 host
  port: 8010                  # BPQ TelnetServer port

meshcore:
  connection: "serial"        # serial | ble | tcp
  device: "/dev/ttyUSB0"     # Serial device path
  baud: 115200
  channel_idx: 4             # Private channel index
```

## Usage

```bash
cd /opt/bpq-meshcore-gateway
venv/bin/python -m gateway.main
```

Or with a custom config path:

```bash
venv/bin/python -m gateway.main /path/to/config.yaml
```

### Run as a systemd service

```bash
sudo tee /etc/systemd/system/bpq-meshcore-gw.service << 'EOF'
[Unit]
Description=BPQ-MeshCore Gateway
After=network.target

[Service]
Type=simple
User=YOUR_USER
WorkingDirectory=/opt/bpq-meshcore-gateway
ExecStart=/opt/bpq-meshcore-gateway/venv/bin/python -m gateway.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now bpq-meshcore-gw
```

Check logs: `journalctl -u bpq-meshcore-gw -f`

## User Guide (MeshCore side)

From any MeshCore device on the configured private channel:

| Message | Action |
|---|---|
| `username/password` | Authenticate and connect to BPQ Chat |
| *(any text)* | Relayed to BPQ Chat |
| `DISCONNECT` | End the session |

## Project Structure

```
bpq-meshcore-gateway/
  config.yaml.example    # Example configuration
  requirements.txt       # Python dependencies
  gateway/
    __init__.py
    main.py              # Entry point
    config.py            # YAML config loader
    telnet_client.py     # Raw TCP telnet to BPQ32
    meshcore_client.py   # MeshCore channel listener
    session_manager.py   # Single-session state machine
```

## License

MIT
