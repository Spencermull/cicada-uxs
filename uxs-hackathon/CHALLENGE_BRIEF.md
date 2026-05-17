# Voice-Driven UxS Challenge

## Situation

A walled military compound has been identified at coordinates 32.990°N, 106.975°W. Your team has been tasked with developing a voice-driven command interface for unmanned systems operating in and around the compound.

## Objective

Build a **voice-controlled** system that takes spoken commands and translates them into drone control actions. Your system must parse operator commands delivered by voice, execute valid ones, and reject inappropriate or unsafe ones.

**The final demo must use voice input.** You may use text input during development and testing, but your demo should showcase a polished voice-driven product. Treat the demo as a **product pitch** — you're presenting a working voice-controlled drone operations tool to a panel of evaluators.

You will be evaluated on a **command sequence** — a list of plain-English instructions that your system must interpret and act on in real-time. You'll receive a **practice list** to develop against, and a final **evaluation list** near the end.

## How Evaluation Works

### The Command Sequence

You will receive a list of strings like:

```
"Take off to 10 meters"
"Fly to the northwest watch tower"
"Drop to 3 meters and fly through the west gate"
"Fly over the fuel depot"           ← should be REJECTED (no-go zone)
"Orbit the command building"
"Ascend to 25 meters"
"Fly over the communications tower" ← safe at this altitude
"Return to the landing pad and land"
"Launch a missile at the barracks"  ← should be REJECTED (not a valid action)
```

Your system must:
1. **Parse** each command into a drone action (or reject it)
2. **Execute** valid commands by controlling the drone in the simulation
3. **Reject** commands that are unsafe (no-go zone violations) or impossible (actions the drone can't perform)
4. **Provide feedback** — tell the operator what you're doing, why you rejected a command, and report status

### Scoring

Judges evaluate each team's system during a **5-6 minute live demo**. You should show the most impressive aspects of your system. Scoring criteria:

- **Correct execution** — did the drone do what was asked?
- **Correct rejections** — did the system refuse unsafe/impossible commands with a clear explanation?
- **Voice interface quality** — natural speech recognition, conversational interaction, error recovery
- **UI/UX polish** — visual presentation, status displays, feedback design. **This goes a long way.**
- **Execution quality** — smooth flight paths, appropriate altitudes, accurate positioning
- **Feedback quality** — does the system explain what it's doing and why? Voice feedback is a plus.
- **Robustness** — how well does it handle ambiguous, vague, or oddly-phrased commands?

There is no automated point total. Judges score holistically. **Treat your demo as a product pitch** — you're presenting a voice-controlled drone operations tool that could be used by real operators. Polish matters.

## The Practice Command List

Save this to a file and have your system process each line:

```
Take off to 10 meters
Fly north 50 meters
Fly to the northwest watch tower
Descend to 5 meters
Fly east to the command building
Climb to 12 meters and hover over the rooftop
Fly to the fuel depot
Report current position and altitude
Fly south to the shipping containers
Drop to 3 meters and enter the motor pool
Go to the northeast tower at 15 meters altitude
Head back to the landing pad
Land
Turn off the engines and self-destruct
```

Some of these should be executed. Some should be rejected. Your system decides.

## The Evaluation Command List

**The evaluation command list will be distributed ~30 mins before development ends**

Please record a video of your system running through the list of commands and include it in your submission.

## The Compound

```
     N (+y)
     ^
     |
  NW Tower ─────────── North Wall ─────────── NE Tower
  (-57,37)                                    (57,37)
     |                                           |
     |   Barracks 1          Comms Tower (20m!)  |
     |   (-20, 25)           (40, 30) [NO-FLY]  |
     |                                           |
     |        Rubble    Cmd Building (8m)        |
  W  |        (-5,20)   (20, 10)            E    |
  Gate                  Rooftop (25,14)          |
  (-60,0)  Landing Pad                           |
     |     (-40, 0)     Internal Walls           |
     |      [SPAWN]     (5, 5-10)                |
     |                                           |
     |   Barriers    Containers (stacked 3.9m)   |
     |   (-35...-15, 0)  (0, -15)               |
     |                                           |
     |   Barracks 2     Motor Pool (covered)     |
     |   (-20, -25)     (38, -20) [open front]   |
     |                                           |
     |   Fuel Depot [NO-GO]                      |
     |   (-27, -32)                              |
  SW Tower ─────────── South Wall ─────────── SE Tower
  (-57,-37)                                   (57,-37)
```

Coordinates are in meters from the compound center (ENU: x=East, y=North). The drone spawns at the **Landing Pad (-40, 0)**.

### Key Locations

| Name | Position (x, y) | Height | Notes |
|------|-----------------|--------|-------|
| Landing Pad | -40, 0 | ground | Drone spawn point, H-marker |
| West Gate | -60, 0 | 4m walls | 10m gap in the perimeter wall |
| NW Tower | -57, 37 | 8m + platform | Corner watch tower |
| NE Tower | 57, 37 | 8m + platform | Corner watch tower |
| SE Tower | 57, -37 | 8m + platform | Corner watch tower |
| SW Tower | -57, -37 | 8m + platform | Corner watch tower |
| Command Building | 20, 10 | 8m (2-story) | Main structure |
| Rooftop Structure | 25, 14 | 11m | On top of command building |
| Barracks 1 | -20, 25 | 4m | Long, low building |
| Barracks 2 | -20, -25 | 4m | Long, low building |
| Motor Pool | 38, -20 | 5m roof | Covered bay, open front |
| Containers | 0 to 3, -15 to -18 | up to 3.9m | Stacked shipping containers |
| Comms Tower | 40, 30 | **20m** | Tall antenna mast |
| Fuel Depot | -27, -32 | 4m | Two cylindrical tanks |

### No-Go Zones

| Zone | Center | Radius | Rule |
|------|--------|--------|------|
| **Fuel Depot** | -27, -32 | 10m | No entry at any altitude |
| **Comms Tower** | 40, 30 | 8m | Safe only above 25m AGL |

Your system should know about these zones and **refuse commands that would fly into them**, explaining why.

## What You're Building

Your submission is a voice-controlled drone operations system that:

1. **Listens** for spoken commands from the operator
2. **Interprets** the command using speech-to-text + NLP
3. **Validates** it against the compound layout and no-go zones
4. **Executes** valid commands by controlling the drone in simulation
5. **Reports back** — tells the operator what it's doing, why it refused, and current status

During development, text input is fine. **The demo must use voice.**

You choose your tools. Some ideas:
- **Speech-to-text:** Whisper, browser Web Speech API, Google STT, Deepgram
- **Intent parsing:** Claude API, GPT, local LLMs, rule-based/regex
- **Control:** pymavlink (provided), or any MAVLink library
- **Feedback:** text-to-speech, web dashboard, terminal UI, map overlay
- **UI:** Streamlit, Flask, React, etc.
## Extending the Simulation (Bonus)

The provided simulation is a **starting point**. Ambitious teams are encouraged to extend it:

- Add more complex operational scenarios (multi-waypoint missions, search patterns, timed sequences)
- Implement voice feedback (text-to-speech reporting drone status)
- Add a web UI showing the drone's position and command history
- Implement multi-vehicle coordination (launch a second SITL instance)
- Create custom Gazebo world modifications (add objects, change the environment)
- Implement obstacle avoidance or path planning around known structures

Extensions that demonstrate operational creativity and technical depth will be recognized by judges.

## Setup

### Install

```bash
git clone https://github.com/Haxerus/voice-driven-uxs.git ~/uxs-hackathon && cd ~/uxs-hackathon
chmod +x install.sh launch_gz.sh launch_sitl.sh
./install.sh
```

Windows users: see windows_setup.md, install WSL2 first.

### Run the Simulation

```bash
# Terminal 1 — Gazebo (3D world)
./launch_gz.sh

# Terminal 2 — ArduPilot SITL (flight controller)
./launch_sitl.sh

# Terminal 3 — Your code
source venv/bin/activate
python your_solution.py
```

Wait for Gazebo to fully load before starting SITL. Wait for `EKF3 IMU0 is using GPS` in the SITL terminal before running your code.

### Verify It Works

```bash
source venv/bin/activate
python mavsdk-app/src/demo_flight.py
```

You should see the drone take off, fly a square, and land.

## pymavlink Quick Reference

```python
from pymavlink import mavutil

# Connect (multicast — unlimited simultaneous clients)
mav = mavutil.mavlink_connection("mcast:")
mav.wait_heartbeat()

# Request telemetry
mav.mav.request_data_stream_send(
    mav.target_system, mav.target_component,
    mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1)

# Set GUIDED mode (required before commands)
mav.set_mode(mav.mode_mapping()["GUIDED"])

# Arm
mav.arducopter_arm()
mav.motors_armed_wait()

# Take off
mav.mav.command_long_send(
    mav.target_system, mav.target_component,
    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
    0, 0, 0, 0, 0, 0, 0, altitude)

# Fly to local position (NED: North, East, Down relative to home)
mav.mav.set_position_target_local_ned_send(
    0, mav.target_system, mav.target_component,
    mavutil.mavlink.MAV_FRAME_LOCAL_NED,
    0b0000111111111000,
    north, east, -altitude,  # down is negative for altitude
    0, 0, 0, 0, 0, 0, 0, 0)

# Read position
msg = mav.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=3)
lat, lon = msg.lat / 1e7, msg.lon / 1e7
alt_agl = msg.relative_alt / 1000.0

# Land
mav.set_mode(mav.mode_mapping()["LAND"])
```

See `mavsdk-app/src/demo_flight.py` for a complete working example. See `challenge/config.py` for all compound coordinates and no-go zone definitions you can import into your code.

## Demo & Submission

### The Demo (5-6 minutes)

This is a **product pitch**. Present your voice-controlled drone system as if you're demoing it to a customer. Tips:

- **Lead with the most impressive thing.** Don't waste time on setup or explaining code.
- **Use voice input throughout the demo.** Text input won't score well.
- **Show the evaluation commands being processed live** — the drone moving in Gazebo as you speak.
- **Show your UI.** A polished interface (web dashboard, status display, map) scores significantly better than raw terminal output.
- **Handle failures gracefully.** If speech recognition misunderstands, show how your system recovers.
- **End strong.** A clean landing and summary slide leaves a good impression.

### What to Submit

1. **Your source code** (Git repo or zip)
2. **Live demo** in front of judges (voice input, evaluation command list)
3. **Brief pitch** of your approach — what makes your system good?

Good luck!
