#!/usr/bin/env bash
# Fill in the deploy/ templates for this machine and, with --apply, install them.
#
#   deploy/install.sh           render into deploy/build/ only (review first)
#   deploy/install.sh --apply   also install: systemd user units, logrotate
#                               config and crontab (the current crontab is
#                               backed up to deploy/build/crontab.previous)
#
# Placeholders and their defaults (override with environment variables):
#   @PIPELINE_DIR@  this repo's checkout (detected)
#   @DATA_DIR@      PIPELINE_DATA_DIR, default $HOME -- where the collectors'
#                   .db and .log files live
#   @PYTHON@        PYTHON, default $HOME/.venv/bin/python
#   @NODE@          NODE, default the `node` on PATH (Node 24 for Osiris and
#                   God's Eye View; with nvm, run `nvm use 24` first)
#   @HOME@          $HOME
# Services are installed but not enabled; enable the ones you want afterwards.
set -euo pipefail

PIPELINE_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DATA_DIR=${PIPELINE_DATA_DIR:-$HOME}
PYTHON=${PYTHON:-$HOME/.venv/bin/python}
NODE=${NODE:-$(command -v node || true)}
OUT=$PIPELINE_DIR/deploy/build
APPLY=0
[[ "${1:-}" == "--apply" ]] && APPLY=1

warn() { echo "warning: $*" >&2; }
[[ -x "$PYTHON" ]] || warn "Python not found at $PYTHON (set PYTHON=...)"
if [[ -z "$NODE" ]]; then
    warn "node not found on PATH; Osiris/God's Eye View units will be broken (set NODE=...)"
    NODE=/usr/bin/node
fi
NODE_DIR=$(dirname "$NODE")

render() {  # render <template> <output>
    mkdir -p "$(dirname "$2")"
    sed -e "s|@PIPELINE_DIR@|$PIPELINE_DIR|g" \
        -e "s|@DATA_DIR@|$DATA_DIR|g" \
        -e "s|@PYTHON@|$PYTHON|g" \
        -e "s|@NODE_DIR@|$NODE_DIR|g" \
        -e "s|@NODE@|$NODE|g" \
        -e "s|@HOME@|$HOME|g" \
        "$1" > "$2"
    if grep -q '@[A-Z_]*@' "$2"; then
        echo "error: unfilled placeholder in $2" >&2
        exit 1
    fi
}

rm -rf "$OUT"
render "$PIPELINE_DIR/deploy/crontab.txt" "$OUT/crontab.txt"
render "$PIPELINE_DIR/deploy/logrotate/pipeline.conf" "$OUT/logrotate/pipeline.conf"
for unit in "$PIPELINE_DIR"/deploy/systemd/*.service; do
    render "$unit" "$OUT/systemd/$(basename "$unit")"
done

echo "Rendered into $OUT"
echo "  PIPELINE_DIR=$PIPELINE_DIR"
echo "  DATA_DIR=$DATA_DIR"
echo "  PYTHON=$PYTHON"
echo "  NODE=$NODE"

if (( ! APPLY )); then
    echo "Review the files, then run: deploy/install.sh --apply"
    exit 0
fi

mkdir -p "$HOME/.config/systemd/user" "$HOME/.config/logrotate" "$DATA_DIR"
cp "$OUT"/systemd/*.service "$HOME/.config/systemd/user/"
cp "$OUT/logrotate/pipeline.conf" "$HOME/.config/logrotate/pipeline.conf"
crontab -l > "$OUT/crontab.previous" 2>/dev/null || true
crontab "$OUT/crontab.txt"
systemctl --user daemon-reload 2>/dev/null || warn "systemctl --user unavailable; units copied but not loaded"

echo "Installed. Previous crontab saved to $OUT/crontab.previous"
echo "Enable the services you need, e.g.:"
echo "  systemctl --user enable --now dashboard osiris gods-eye-view"
echo "  systemctl --user enable --now polymarket_poller kalshi_poller opensky_poller"
echo "  systemctl --user enable --now ibgateway   # needs ~/ibc set up first"
