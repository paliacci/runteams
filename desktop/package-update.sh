#!/bin/bash
# 把已经签名、公证的 RunTeams.app 制作成静默更新资源，并打印 latest.json 所需字段。
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="${1:-$ROOT/desktop/RunTeams.app}"
VERSION="$(tr -d '[:space:]' < "$ROOT/VERSION")"
ARCH="$(uname -m)"
case "$ARCH" in arm64) TARGET=aarch64 ;; x86_64) TARGET=x86_64 ;; *) TARGET="$ARCH" ;; esac
OUT="$ROOT/desktop/releases/$VERSION"
ARCHIVE="$OUT/RunTeams-$VERSION-darwin-$TARGET.zip"
[ -d "$APP" ] || { echo "找不到已构建的 RunTeams.app" >&2; exit 1; }
mkdir -p "$OUT"
rm -f "$ARCHIVE"
/usr/bin/ditto -c -k --sequesterRsrc --keepParent "$APP" "$ARCHIVE"
DIGEST="$(/usr/bin/shasum -a 256 "$ARCHIVE" | awk '{print $1}')"
echo "更新资源: $ARCHIVE"
echo "latest.json:"
echo "\"darwin-$TARGET\":{\"kind\":\"macos-app-zip\",\"url\":\"https://downloads.runteams.ai/$VERSION/$(basename "$ARCHIVE")\",\"sha256\":\"$DIGEST\"}"
