#!/bin/sh
# maps_watch.sh <out>: copies RobloxPlayer's /proc maps every 50 ms while it lives (up to 120 s).
out=$1; end=$(( $(date +%s) + 120 )); seen=
while [ "$(date +%s)" -lt "$end" ]; do
  pid=$(ps -eo pid,comm,args | awk '$2=="Main" && $3=="./RobloxPlayer" {print $1; exit}')
  if [ -n "$pid" ]; then seen=1; cp /proc/$pid/maps "$out.tmp" 2>/dev/null && mv "$out.tmp" "$out"; elif [ -n "$seen" ]; then exit 0; fi
  sleep 0.05
done
