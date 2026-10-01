#!/bin/bash
# Offline (VM powered off) snapshots of the Windows 11 VM.
#   vmsnap.sh create <purpose>   snapshot named YYYYMMDD-HHMM-<purpose>, plus a copy of the TPM state + UEFI vars
#   vmsnap.sh list               show snapshots (works while the VM runs)
#   vmsnap.sh revert <name>      roll the disk back (and restore that snapshot's TPM/UEFI copy)
#   vmsnap.sh delete <name>      remove one snapshot
#   vmsnap.sh prune [N]          keep only the newest N snapshots (default 5)
# Policy: snapshot BEFORE any risky change (drivers, disk/NIC type, big installs, registry hacks). VM must be off.
DIR=/var/lib/windows-vm/win11; IMG="$DIR/win11.qcow2"; COMP="$DIR/snapshots"; mkdir -p "$COMP"
running() { systemctl is-active --quiet win11 || ! qemu-img info "$IMG" >/dev/null 2>&1; }   # unit up, or the disk image is write-locked by a QEMU
case "$1" in
  list)   qemu-img snapshot -U -l "$IMG" ;;
  create) running && { echo "VM is running - shut it down first (Windows: shutdown /s, then wait for the win11 unit to stop)"; exit 1; }
          [ -n "$2" ] || { echo "usage: vmsnap.sh create <purpose>"; exit 2; }
          n="$(date +%Y%m%d-%H%M)-$2"
          qemu-img snapshot -c "$n" "$IMG" && tar czf "$COMP/$n.tgz" -C "$DIR" tpm OVMF_VARS.fd && echo "created snapshot: $n" ;;
  revert) running && { echo "VM is running - shut it down first"; exit 1; }
          [ -n "$2" ] || { echo "usage: vmsnap.sh revert <name>"; exit 2; }
          qemu-img snapshot -a "$2" "$IMG" && { [ -f "$COMP/$2.tgz" ] && tar xzf "$COMP/$2.tgz" -C "$DIR"; echo "reverted to: $2"; } ;;
  delete) running && { echo "VM is running - shut it down first"; exit 1; }
          qemu-img snapshot -d "$2" "$IMG" && rm -f "$COMP/$2.tgz" && echo "deleted: $2" ;;
  prune)  running && { echo "VM is running - shut it down first"; exit 1; }
          keep="${2:-5}"
          qemu-img snapshot -U -l "$IMG" | awk 'NR>2{print $2}' | sort | head -n -"$keep" | while read -r n; do qemu-img snapshot -d "$n" "$IMG" && rm -f "$COMP/$n.tgz" && echo "pruned: $n"; done ;;
  *) sed -n '2,9p' "$0"; exit 2 ;;
esac
