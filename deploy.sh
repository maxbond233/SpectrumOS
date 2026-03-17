#!/bin/bash
# 光谱 OS · 一键部署脚本
# Usage: bash deploy.sh

set -e

echo "🔮 光谱 OS · Deploy"
echo "================================"
echo ""

# Check for .env
if [ ! -f ".env" ]; then
  echo "⚠️  未找到 .env 文件，请确保项目根目录有 .env（含 API keys）"
  echo "   继续部署（运行时需要 .env）..."
  echo ""
fi

# Install project
echo "📦 安装项目..."
pip install -e "." --break-system-packages -q 2>/dev/null || \
pip install -e "." -q

# Copy project
echo "📁 部署文件..."
sudo mkdir -p /opt/spectrum-os
sudo cp -r . /opt/spectrum-os/

# Setup systemd service
echo "⚙️  配置 systemd 服务..."
sudo cp src/spectrum/dashboard/spectrum-os.service /etc/systemd/system/

sudo systemctl daemon-reload
sudo systemctl enable spectrum-os
sudo systemctl restart spectrum-os

echo ""
echo "✅ 部署完成！"
echo ""
echo "   Dashboard: http://$(hostname -I | awk '{print $1}'):8078"
echo "   API:       http://$(hostname -I | awk '{print $1}'):8078/api/health"
echo "   服务状态:  systemctl status spectrum-os"
echo "   查看日志:  journalctl -u spectrum-os -f"
echo ""
