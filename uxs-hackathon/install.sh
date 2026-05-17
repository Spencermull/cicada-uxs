#!/usr/bin/env bash
#
# UxS Hackathon — One-shot environment setup
#
# Installs: ArduPilot SITL, Gazebo Harmonic, ardupilot_gazebo plugin, pymavlink
#
# Supports:
#   - Ubuntu 22.04 / 24.04 (native or WSL2)
#   - macOS (Homebrew)
#
# Usage:
#   chmod +x install.sh
#   ./install.sh
#
# Safe to re-run — skips anything already installed.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARDUPILOT_DIR="${SCRIPT_DIR}/ardupilot"
GZ_PLUGIN_DIR="${SCRIPT_DIR}/ardupilot_gazebo"
VENV_DIR="${SCRIPT_DIR}/venv"

# ── Helpers ──────────────────────────────────────────────────────────────────

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[FAIL]${NC}  $*" >&2; }
step()  { echo -e "\n${GREEN}>>>${NC} $*"; }

check_command() { command -v "$1" &>/dev/null; }

# ── OS Detection ─────────────────────────────────────────────────────────────

detect_os() {
    case "$(uname -s)" in
        Linux*)
            if grep -qiE "ubuntu|debian" /etc/os-release 2>/dev/null; then
                echo "ubuntu"
            else
                error "Unsupported Linux distro. Please use Ubuntu 22.04+ (native or WSL2)."
                exit 1
            fi ;;
        Darwin*) echo "macos" ;;
        MINGW*|MSYS*|CYGWIN*)
            error "Native Windows is not supported."
            error "Install WSL2:  wsl --install -d Ubuntu-22.04"
            exit 1 ;;
        *) error "Unknown OS: $(uname -s)"; exit 1 ;;
    esac
}

is_wsl() { grep -qi "microsoft\|wsl" /proc/version 2>/dev/null; }

# ── Step 1: System Dependencies ─────────────────────────────────────────────

install_system_deps_ubuntu() {
    step "Installing system dependencies..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq \
        git curl wget lsb-release gnupg ca-certificates \
        python3 python3-pip python3-venv python3-dev \
        cmake build-essential pkg-config \
        > /dev/null
    info "System dependencies installed."
}

install_system_deps_macos() {
    if ! check_command brew; then
        error "Homebrew is required. Install from https://brew.sh"
        exit 1
    fi
    step "Installing system dependencies via Homebrew..."
    brew install --quiet cmake python@3.11 wget git 2>/dev/null || true
    info "System dependencies installed."
}

# ── Step 2: Gazebo Harmonic ─────────────────────────────────────────────────

install_gazebo_harmonic_ubuntu() {
    if check_command gz && gz sim --version 2>/dev/null | grep -q "^Gazebo Sim, version 8\."; then
        info "Gazebo Harmonic already installed."
        return
    fi

    step "Installing Gazebo Harmonic..."
    sudo curl -sSL https://packages.osrfoundation.org/gazebo.gpg \
        -o /usr/share/keyrings/pkgs-osrf-archive-keyring.gpg

    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/pkgs-osrf-archive-keyring.gpg] \
http://packages.osrfoundation.org/gazebo/ubuntu-stable $(lsb_release -cs) main" \
        | sudo tee /etc/apt/sources.list.d/gazebo-stable.list > /dev/null

    sudo apt-get update -qq
    sudo apt-get install -y -qq gz-harmonic > /dev/null
    info "Gazebo Harmonic installed: $(gz sim --version 2>/dev/null | head -1)"
}

install_gazebo_harmonic_macos() {
    if check_command gz && gz sim --version 2>/dev/null | grep -q "^Gazebo Sim, version 8\."; then
        info "Gazebo Harmonic already installed."
        return
    fi

    step "Installing Gazebo Harmonic via Homebrew..."
    brew tap osrf/simulation
    brew install gz-harmonic
    info "Gazebo Harmonic installed."
}

# ── Step 3: ArduPilot SITL ──────────────────────────────────────────────────

install_ardupilot() {
    if [ -f "${ARDUPILOT_DIR}/build/sitl/bin/arducopter" ]; then
        info "ArduPilot SITL already built."
        return
    fi

    step "Setting up ArduPilot SITL..."

    if [ ! -d "${ARDUPILOT_DIR}" ]; then
        echo "    Cloning ArduPilot (this may take a few minutes)..."
        git clone --depth 1 --recurse-submodules \
            https://github.com/ArduPilot/ardupilot.git "${ARDUPILOT_DIR}"
    fi

    cd "${ARDUPILOT_DIR}"

    echo "    Installing ArduPilot prerequisites..."
    # ArduPilot's install-prereqs handles all system deps
    Tools/environment_install/install-prereqs-ubuntu.sh -y 2>/dev/null || true

    # Reload profile to get PATH updates from install-prereqs
    # shellcheck disable=SC1090
    . ~/.profile 2>/dev/null || true

    echo "    Building ArduCopter SITL..."
    ./waf configure --board sitl
    ./waf copter

    echo "    Building ArduRover SITL..."
    ./waf rover

    cd "${SCRIPT_DIR}"
    info "ArduPilot SITL built (arducopter + ardurover)."
}

# ── Step 4: ArduPilot Gazebo Plugin ─────────────────────────────────────────

install_ardupilot_gazebo_plugin() {
    if [ -f "${GZ_PLUGIN_DIR}/build/libArduPilotPlugin.so" ] || \
       [ -f "${GZ_PLUGIN_DIR}/build/libArduPilotPlugin.dylib" ]; then
        info "ardupilot_gazebo plugin already built."
        return
    fi

    step "Building ardupilot_gazebo plugin..."

    if [ ! -d "${GZ_PLUGIN_DIR}" ]; then
        git clone --depth 1 \
            https://github.com/ArduPilot/ardupilot_gazebo.git "${GZ_PLUGIN_DIR}"
    fi

    # Install build deps not pulled in by Gazebo (discovered during EC2 testing)
    sudo apt-get install -y -qq \
        rapidjson-dev libopencv-dev \
        libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev \
        > /dev/null 2>&1 || true

    cd "${GZ_PLUGIN_DIR}"
    mkdir -p build && cd build
    cmake .. -DCMAKE_BUILD_TYPE=RelWithDebInfo
    make -j"$(nproc 2>/dev/null || sysctl -n hw.ncpu)"

    cd "${SCRIPT_DIR}"
    info "ardupilot_gazebo plugin built."
}

# ── Step 5: Python Environment ───────────────────────────────────────────────

setup_python_env() {
    step "Setting up Python environment..."

    if [ ! -d "${VENV_DIR}" ]; then
        python3 -m venv "${VENV_DIR}"
    fi

    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate"
    pip install --quiet --upgrade pip
    pip install --quiet -r "${SCRIPT_DIR}/mavsdk-app/requirements.txt"
    info "Python venv ready ($(python3 --version))."
}

# ── Step 6: Configure Gazebo Resource Paths ──────────────────────────────────

configure_gazebo_paths() {
    step "Configuring Gazebo resource paths..."

    local SHELL_RC
    if [ -f "$HOME/.bashrc" ]; then
        SHELL_RC="$HOME/.bashrc"
    elif [ -f "$HOME/.zshrc" ]; then
        SHELL_RC="$HOME/.zshrc"
    else
        SHELL_RC="$HOME/.bashrc"
    fi

    local MARKER="# >>> UxS Hackathon Gazebo paths >>>"
    if grep -q "${MARKER}" "${SHELL_RC}" 2>/dev/null; then
        info "Gazebo paths already configured in ${SHELL_RC}."
    else
        cat >> "${SHELL_RC}" << EOF

${MARKER}
export GZ_SIM_RESOURCE_PATH="${SCRIPT_DIR}/worlds:\${GZ_SIM_RESOURCE_PATH:-}"
export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_PLUGIN_DIR}/build:\${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"
export GZ_SIM_RESOURCE_PATH="${GZ_PLUGIN_DIR}/models:\${GZ_SIM_RESOURCE_PATH}"
export GZ_SIM_RESOURCE_PATH="${GZ_PLUGIN_DIR}/worlds:\${GZ_SIM_RESOURCE_PATH}"
# <<< UxS Hackathon Gazebo paths <<<
EOF
        info "Gazebo paths added to ${SHELL_RC}."
    fi

    # Also export for current session
    export GZ_SIM_RESOURCE_PATH="${SCRIPT_DIR}/worlds:${GZ_SIM_RESOURCE_PATH:-}"
    export GZ_SIM_SYSTEM_PLUGIN_PATH="${GZ_PLUGIN_DIR}/build:${GZ_SIM_SYSTEM_PLUGIN_PATH:-}"
    export GZ_SIM_RESOURCE_PATH="${GZ_PLUGIN_DIR}/models:${GZ_SIM_RESOURCE_PATH}"
    export GZ_SIM_RESOURCE_PATH="${GZ_PLUGIN_DIR}/worlds:${GZ_SIM_RESOURCE_PATH}"
}

# ── Verification ─────────────────────────────────────────────────────────────

verify_install() {
    local PASS=true

    echo ""
    echo "══════════════════════════════════════════════════════"
    echo " Verification"
    echo "══════════════════════════════════════════════════════"

    if check_command gz && gz sim --version 2>/dev/null | grep -q "8\."; then
        info "Gazebo Harmonic  $(gz sim --version 2>/dev/null | head -1)"
    else
        error "Gazebo Harmonic not found"; PASS=false
    fi

    if [ -f "${ARDUPILOT_DIR}/build/sitl/bin/arducopter" ]; then
        info "ArduCopter SITL  ${ARDUPILOT_DIR}/build/sitl/bin/arducopter"
    else
        error "ArduCopter SITL not built"; PASS=false
    fi

    if [ -f "${ARDUPILOT_DIR}/build/sitl/bin/ardurover" ]; then
        info "ArduRover SITL   ${ARDUPILOT_DIR}/build/sitl/bin/ardurover"
    else
        error "ArduRover SITL not built"; PASS=false
    fi

    if [ -f "${GZ_PLUGIN_DIR}/build/libArduPilotPlugin.so" ] || \
       [ -f "${GZ_PLUGIN_DIR}/build/libArduPilotPlugin.dylib" ]; then
        info "Gazebo Plugin    ardupilot_gazebo"
    else
        error "ardupilot_gazebo plugin not built"; PASS=false
    fi

    # shellcheck disable=SC1091
    source "${VENV_DIR}/bin/activate" 2>/dev/null
    if python3 -c "from pymavlink import mavutil" 2>/dev/null; then
        info "pymavlink        $(pip show pymavlink 2>/dev/null | grep Version)"
    else
        error "pymavlink not importable"; PASS=false
    fi

    if [ -f "${SCRIPT_DIR}/worlds/compound_ops.sdf" ]; then
        info "World            compound_ops.sdf"
    else
        error "Custom world not found"; PASS=false
    fi

    echo "══════════════════════════════════════════════════════"

    if $PASS; then
        echo ""
        info "All checks passed! You're ready."
        echo ""
        echo "  Open two terminals, then:"
        echo ""
        echo "  Terminal 1 (Gazebo):    ./launch_gz.sh"
        echo "  Terminal 2 (ArduPilot): ./launch_sitl.sh"
        echo ""
        echo "  Then in a third terminal:"
        echo "    source venv/bin/activate"
        echo "    python mavsdk-app/src/demo_flight.py"
        echo ""
    else
        echo ""
        error "Some checks failed. Review errors above and re-run ./install.sh"
        return 1
    fi
}

# ── Main ─────────────────────────────────────────────────────────────────────

main() {
    echo "══════════════════════════════════════════════════════"
    echo " UxS Hackathon — Environment Setup"
    echo " ArduPilot SITL + Gazebo Harmonic"
    echo "══════════════════════════════════════════════════════"

    OS=$(detect_os)
    info "OS: ${OS}$(is_wsl 2>/dev/null && echo ' (WSL2)' || true)"

    case "$OS" in
        ubuntu)
            install_system_deps_ubuntu
            install_gazebo_harmonic_ubuntu
            ;;
        macos)
            install_system_deps_macos
            install_gazebo_harmonic_macos
            ;;
    esac

    install_ardupilot
    install_ardupilot_gazebo_plugin
    setup_python_env
    configure_gazebo_paths
    verify_install
}

main "$@"
