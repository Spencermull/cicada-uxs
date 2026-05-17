#!/usr/bin/env bash
#
# Launch Gazebo Harmonic with the hackathon compound world.
# Run this FIRST, then launch_sitl.sh in another terminal.
#
# Usage:
#   ./launch_gz.sh                   # default world
#   ./launch_gz.sh my_world.sdf      # custom world file
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GZ_PLUGIN_DIR="${SCRIPT_DIR}/ardupilot_gazebo"
WORLD="${1:-${SCRIPT_DIR}/worlds/compound_ops.sdf}"

# Set up Gazebo resource paths
export GZ_SIM_RESOURCE_PATH="${SCRIPT_DIR}/worlds:${GZ_PLUGIN_DIR}/models:${GZ_PLUGIN_DIR}/worlds:${GZ_SIM_RESOURCE_PATH:-}"
export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_PLUGIN_DIR}/build:${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"

if [ ! -f "${WORLD}" ]; then
    echo "ERROR: World file not found: ${WORLD}"
    exit 1
fi

echo "══════════════════════════════════════════════════════"
echo " Gazebo Harmonic — UxS Hackathon"
echo ""
echo "  World: $(basename "${WORLD}")"
echo ""
echo "  Next: run ./launch_sitl.sh in another terminal"
echo "══════════════════════════════════════════════════════"
echo ""

exec gz sim -v4 -r "${WORLD}"
