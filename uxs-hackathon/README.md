# Voice-Driven UxS Challenge

Build a system that takes natural language commands and controls a drone in a simulated military compound. Parse commands, execute valid ones, reject unsafe ones, and report back.

**Stack:** ArduPilot SITL + Gazebo Harmonic + pymavlink (Python)

---

## Quick Start

### 1. Install

**Linux (Ubuntu 22.04+, Pop!_OS, Debian):**
```bash
git clone https://github.com/Haxerus/voice-driven-uxs.git ~/uxs-hackathon
cd ~/uxs-hackathon
chmod +x install.sh launch_gz.sh launch_sitl.sh
./install.sh
```

**macOS:**
```bash
# Install Homebrew first if you don't have it: https://brew.sh
git clone https://github.com/Haxerus/voice-driven-uxs.git ~/uxs-hackathon
cd ~/uxs-hackathon
chmod +x install.sh launch_gz.sh launch_sitl.sh
./install.sh
```

**Windows:** See windows_setup.md, install WSL2 first, then run the same commands above inside Ubuntu.

### 2. Run the Simulation (3 terminals)

```bash
# Terminal 1 — Gazebo (3D world visualization)
cd ~/uxs-hackathon && ./launch_gz.sh

# Terminal 2 — ArduPilot SITL (flight controller)
cd ~/uxs-hackathon && ./launch_sitl.sh

# Terminal 3 — Your code
cd ~/uxs-hackathon && source venv/bin/activate
python mavsdk-app/src/demo_flight.py
```

Wait for Gazebo to fully load before starting SITL. Wait for SITL to show `EKF3 IMU0 is using GPS` before running your code.

### 3. Verify It Works

You should see the drone take off, fly a square, and land in the Gazebo window.

---

## How It Works

```
┌─────────────┐     JSON/UDP      ┌─────────────────┐
│   Gazebo     │◄────────────────►│  ArduPilot SITL  │
│  (physics +  │   physics data    │  (flight control │
│   3D render) │                   │   + autopilot)   │
└─────────────┘                   └────────┬─────────┘
                                           │ MAVLink
                                           │ UDP multicast
                                           ▼
                                    ┌──────────────┐
                                    │  Your Python  │
                                    │    code       │
                                    │  (pymavlink)  │
                                    └──────────────┘
```

- **Gazebo** simulates the 3D world, physics, and sensors
- **ArduPilot SITL** runs the real ArduPilot flight controller code in software
- **pymavlink** sends MAVLink commands and receives telemetry over UDP multicast
- **UDP multicast** means unlimited scripts can connect simultaneously — no port conflicts

---

## Connecting Your Code

Every script connects the same way:

```python
from pymavlink import mavutil

mav = mavutil.mavlink_connection("mcast:")
mav.wait_heartbeat()
print(f"Connected to system {mav.target_system}")
```

### Common Operations

```python
# Request telemetry streams (do this once after connecting)
mav.mav.request_data_stream_send(
    mav.target_system, mav.target_component,
    mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1)

# Set flight mode
mode_id = mav.mode_mapping()["GUIDED"]
mav.set_mode(mode_id)

# Arm
mav.arducopter_arm()
mav.motors_armed_wait()

# Take off to 10m
mav.mav.command_long_send(
    mav.target_system, mav.target_component,
    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
    0, 0, 0, 0, 0, 0, 0, 10)

# Fly to local NED position (relative to home)
# NED = North-East-Down, so "down" is negative for altitude
mav.mav.set_position_target_local_ned_send(
    0, mav.target_system, mav.target_component,
    mavutil.mavlink.MAV_FRAME_LOCAL_NED,
    0b0000111111111000,  # position only bitmask
    north, east, down,
    0, 0, 0, 0, 0, 0, 0, 0)

# Fly to GPS coordinate
mav.mav.command_int_send(
    mav.target_system, mav.target_component,
    mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
    mavutil.mavlink.MAV_CMD_DO_REPOSITION,
    0, 0, 0, 0, 0, 0,
    int(lat * 1e7), int(lon * 1e7), alt_agl)

# Read position
msg = mav.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=3)
if msg:
    lat = msg.lat / 1e7
    lon = msg.lon / 1e7
    alt_agl = msg.relative_alt / 1000.0  # meters

# Land
mode_id = mav.mode_mapping()["LAND"]
mav.set_mode(mode_id)
```

### Available Flight Modes

| Mode | Description |
|------|-------------|
| `GUIDED` | Accept position/velocity commands from pymavlink |
| `AUTO` | Follow uploaded waypoint mission |
| `LAND` | Autonomous landing |
| `RTL` | Return to launch point and land |
| `LOITER` | Hold current position |

---

## The Challenge

See [CHALLENGE_BRIEF.md](CHALLENGE_BRIEF.md) for the full mission briefing, compound map, and evaluation criteria.

**TL;DR:** Your system receives a list of natural language commands. Parse each one, fly the drone if it's valid, reject it if it's unsafe, and explain what you're doing. You'll be evaluated on the quality and robustness of your command parser as well as the creativity of your UX/UI.

---

## Running the Full Challenge Stack

```bash
# Terminal 1: Gazebo world
./launch_gz.sh

# Terminal 2: ArduPilot SITL
./launch_sitl.sh

# Terminal 3: Your code
source venv/bin/activate
python your_solution.py
```

---

## Project Structure

```
├── install.sh                  # Environment setup
├── launch_gz.sh                # Start Gazebo with compound world
├── launch_sitl.sh              # Start ArduPilot SITL
├── README.md                   # This file
├── CHALLENGE_BRIEF.md          # Mission briefing + scoring rules
├── windows_setup.md            # Windows WSL2 setup guide
│
├── worlds/
│   └── compound_ops.sdf        # Military compound 3D environment
│
├── mavsdk-app/
│   ├── requirements.txt        # Python dependencies (pymavlink)
│   └── src/
│       ├── demo_flight.py      # Example: arm, takeoff, fly square, land
│       ├── demo_rover.py       # Example: drive rover waypoint mission
│       └── telemetry_monitor.py # Example: stream live telemetry
│
├── challenge/
│   ├── config.py               # Compound coordinates, no-go zones
│   ├── scorer.py               # Optional scoring tool (waypoint tracking)
│   └── practice_commands.txt   # Practice command list for development
│
├── venv/                       # Python venv (created by install.sh)
├── ardupilot/                  # ArduPilot source (created by install.sh)
└── ardupilot_gazebo/           # Gazebo plugin (created by install.sh)
```

---

## Troubleshooting

### Installation Issues

**`install.sh` fails with apt errors:**
```bash
sudo apt-get update && sudo apt-get upgrade -y
./install.sh  # re-run
```

**`install.sh` fails building ArduPilot:**
```bash
cd ardupilot
Tools/environment_install/install-prereqs-ubuntu.sh -y
. ~/.profile
./waf configure --board sitl && ./waf copter
```

**`install.sh` fails building ardupilot_gazebo:**
```bash
sudo apt-get install -y rapidjson-dev libopencv-dev libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev
cd ardupilot_gazebo/build && cmake .. && make -j$(nproc)
```

**macOS: Homebrew not found:**
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### Simulation Issues

**Gazebo window doesn't appear:**
- WSL2: Run `wsl --update` in PowerShell. Check GPU with `glxinfo | grep renderer` — if it says "llvmpipe", update GPU drivers.
- Linux: Install GPU drivers. Check with `glxinfo | grep renderer`.
- If Gazebo crashes on start, try: `gz sim -v4 -r worlds/compound_ops.sdf` directly for error messages.

**SITL exits immediately / "model JSON" error:**
- Make sure Gazebo is running FIRST and the world is fully loaded.
- Check that `ardupilot_gazebo` plugin is built: `ls ardupilot_gazebo/build/libArduPilotPlugin.so`
- Verify environment: `echo $GZ_SIM_SYSTEM_PLUGIN_PATH` should include `ardupilot_gazebo/build`

**SITL runs but drone doesn't move:**
- Wait for `EKF3 IMU0 is using GPS` in the SITL terminal — takes ~10-15 seconds.
- If it never appears, Gazebo may not be sending sensor data. Restart both.

**"No heartbeat" / pymavlink can't connect:**
- SITL must be running with `--mcast` (our launch script does this).
- Check: `ss -ulnp | grep 14550` — should show `arducopter` on UDP multicast.
- If nothing: `pkill -f arducopter && ./launch_sitl.sh` to restart.

**Multiple scripts conflict / "Address in use":**
- All scripts use `mavutil.mavlink_connection("mcast:")` — multicast supports unlimited clients.
- If you see "Address in use", a stale process is holding a port. Run: `pkill -f python`

**Drone won't arm:**
- Must be in `GUIDED` mode first: `mav.set_mode(mav.mode_mapping()["GUIDED"])`
- Wait for GPS fix: `EKF3 IMU0 is using GPS` in SITL terminal
- Check pre-arm: `msg = mav.recv_match(type="STATUSTEXT", blocking=True)` for error messages

**Drone takes off but doesn't move to waypoints:**
- After takeoff, you must send position targets continuously or switch to `AUTO` mode.
- `set_position_target_local_ned_send` only works in `GUIDED` mode.
- The command is a one-shot — for continuous movement, send it in a loop or wait and send the next.

### Performance Issues

**Gazebo is very slow / low FPS:**
- Close unnecessary applications
- In Gazebo GUI: try reducing shadow quality or disabling shadows
- Allocate more RAM/CPU to WSL2 if on Windows (edit `%UserProfile%\.wslconfig`)
- Headless mode: `HEADLESS=1 gz sim -r worlds/compound_ops.sdf` (no GUI, faster)

**SITL simulation is behind real-time:**
- Normal on slower machines. The sim runs at whatever speed the CPU allows.
- Reduce Gazebo physics rate if needed (edit `<max_step_size>` in the SDF)

---

## Useful pymavlink Resources

- [pymavlink documentation](https://mavlink.io/en/mavgen_python/)
- [MAVLink message reference](https://mavlink.io/en/messages/common.html)
- [ArduPilot MAVLink interface](https://ardupilot.org/dev/docs/mavlink-commands.html)
- [ArduPilot flight modes](https://ardupilot.org/copter/docs/flight-modes.html)
