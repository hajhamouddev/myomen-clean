#!/usr/bin/env bash
# backup.sh - copy the whole OmenSense git history to a folder, as one file.
#
#   bash tools/backup.sh [folder]      # default: the "baby" USB stick
#
# Writes two files to <folder>/OmenSense-backup/:
#   omensense-<date>.bundle        every commit, in one file that works on any
#                                  filesystem (the stick is exFAT). Restore with
#                                  git clone omensense-<date>.bundle OmenSense
#   omensense-local-<date>.tar.gz  local/: the Claude chats and memory (refreshed
#                                  first), settings and evidence kept out of git.
#                                  Restore with tar xzf ... -C OmenSense
# Only committed work is in the bundle - commit first.

set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
dest="${1:-/run/media/$USER/baby}/OmenSense-backup"

[ -d "$(dirname "$dest")" ] || { echo "not found: $(dirname "$dest") - is the stick plugged in?"; exit 1; }
if [ -n "$(git -C "$HERE" status --porcelain)" ]; then
    echo "note: there are uncommitted changes; they are not in the backup"
fi

mkdir -p "$dest"
bundle="$dest/omensense-$(date +%Y%m%d-%H%M).bundle"
git -C "$HERE" bundle create "$bundle" --all
git bundle verify "$bundle" >/dev/null 2>&1
echo "backed up $(git -C "$HERE" rev-list --count --all) commits to $bundle ($(du -h "$bundle" | cut -f1))"

if [ -d "$HERE/local" ]; then
    python3 "$HERE/tools/export-chat.py" >/dev/null || echo "note: chat export failed; backing up the last one"
    archive="$dest/omensense-local-$(date +%Y%m%d-%H%M).tar.gz"
    tar czf "$archive" -C "$HERE" local
    tar tzf "$archive" >/dev/null
    echo "backed up local/ ($(tar tzf "$archive" | wc -l) entries) to $archive ($(du -h "$archive" | cut -f1))"
fi
sync
