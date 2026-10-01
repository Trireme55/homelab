#!/usr/bin/env bash
# Installs smartmontools and configures smartd to monitor all SMART-capable drives.
# Run with:  sudo bash hosts/debian/bootstrap/setup-smartd.sh
set -euo pipefail

[ "$(id -u)" -eq 0 ] || { echo "Run with sudo"; exit 1; }

echo "== 1/3 Install smartmontools"
apt-get update
apt-get install -y smartmontools

echo "== 2/3 Configure smartd"
[ -f /etc/smartd.conf ] && cp /etc/smartd.conf /etc/smartd.conf.bak
# -a            monitor all SMART attributes/health
# -o on -S on   enable automatic offline testing + attribute autosave
# -n standby,q  don't wake spun-down HDDs just to check them
# -s ...        short self-test daily 02:00, long self-test Saturdays 03:00
# -W 4,45,55    log temp changes >=4C, warn at 45C, critical at 55C
# -M exec ...   run Debian's smartd-runner (scripts in /etc/smartmontools/run.d/)
cat > /etc/smartd.conf <<'EOF'
DEVICESCAN -a -o on -S on -n standby,q -s (S/../.././02|L/../../6/03) -W 4,45,55 -m root -M exec /usr/share/smartmontools/smartd-runner
EOF

echo "== 3/3 Enable and start"
systemctl enable smartmontools
systemctl restart smartmontools
sleep 2

echo
echo "-- smartd status"
systemctl --no-pager --lines=0 status smartmontools | head -5
echo
echo "-- Drives smartd is monitoring"
journalctl -u smartmontools -b --no-pager | grep -E 'Device: /dev/|monitoring|Opened|No such' | tail -15
echo
echo "-- Quick health check"
for d in /dev/sda /dev/sdb; do
  echo "## $d"
  smartctl -H -i "$d" | grep -E 'Model|Device Model|Serial|overall-health|result'
  smartctl -A "$d" | grep -Ei 'Temperature|Reallocated_Sector|Power_On_Hours|Wear_Leveling|Percent_Lifetime|Current_Pending|Offline_Uncorrectable'
done
