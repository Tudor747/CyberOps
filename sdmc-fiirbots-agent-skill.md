# SKILL: SDMC 2026 FIIRBots Industrial IoT Security & Monitoring Platform Generator

## Confirmed user requirements and pending architecture decisions

These clarifications take precedence over conflicting examples below.

- **Language:** User-facing UI, messages, documentation and AI reports must be in English. The Romanian report descriptions in section 7 must be adapted accordingly.
- **ESP32 target:** NodeMCU-32S / ESP32-WROOM-32, as specified below, confirmed by the user. The ESP32-S3 project is reference code, not the target board configuration.
- **S1 behavior:** Activating S1 must stop scans and request a Raspberry Pi reboot.
- **Startup:** The local touchscreen application must start automatically when the Pi boots, including after an S1 reboot, and display in full-screen kiosk mode.
- **Reboot handling design:** Handle one reboot per switch activation, with debounce. If S1 remains active after boot, keep scans stopped and wait for switch release before accepting another activation; do not enter a reboot loop. Do not automatically resume an interrupted scan.
- **Network topology: standalone monitoring (option 1), confirmed by the user.** Pi connects as a regular network client. Provide discovery, baseline comparisons, alerts, AI recommendations and operator-triggered retests. Do not install firewall rules, act as a gateway/bridge, or claim remote isolation. The active-defense example and automatic firewall/retest cycle in section 7 are superseded by this choice.

---

This Agent Skill contains the complete technical specifications, hardware BOM, pinout mappings, software dependencies, database schema, and step-by-step implementation instructions extracted from the **SDMC 2026 FIIRBots CAD & System Documentation** (`SDMC_2026_FIIRBots_CAD_Integrat.docx`, `Schematic_test_2026-11-09.pdf`, and related specifications).

---

## 1. PROJECT OVERVIEW & ARCHITECTURE

The project is an **Industrial IoT (IIoT) Security & Monitoring Cyberdeck Platform** designed for smart manufacturing (Industry 4.0). It uses a Master-Slave architecture:
- **Master Unit (Raspberry Pi 5):** Handles IP network scanning, local database persistence (SQLite), local Web GUI (FastAPI) displayed on a 5-inch touchscreen (800x480), physical button navigation, and contextual AI risk analysis via Google Gemini API (`gemini-2.5-flash`).
- **Slave Unit (ESP32 NodeMCU-32S):** Dedicated peripheral controller managing multi-protocol physical hardware sensors (Dual nRF24L01+, CC1101 Sub-GHz, RC522 RFID, KY-005/022 IR, Hi-Link LD2420 Radar, and W5500 Ethernet), communicating with Pi 5 over USB-Serial UART.

---

## 2. HARDWARE DEPENDENCIES & BILL OF MATERIALS (BOM)

### Primary Computing & Display
- **1x Raspberry Pi 5** (Main Processor & Web Server)
- **1x ESP32 Development Board** (NodeMCU-32S / ESP32-WROOM-32)
- **1x 5-Inch Touchscreen Display** (HDMI Video Input, Capacitive/Resistive Touch, 800x480 resolution)
- **1x 5V Cooling Fan** (Connected to Raspberry Pi 5 5V/GND headers)
- **1x USB-A to USB-C Cable** (Pi 5 <-> ESP32 High-speed UART link)

### ESP32 Peripherals & Radio Modules
- **2x nRF24L01+ Modules** (2.4 GHz RF communication & spectrum analysis)
- **1x CC1101 Module** (Sub-GHz RF communication: 315/433/868/915 MHz)
- **1x RC522 Module** (13.56 MHz RFID Reader/Writer)
- **1x KY-005 Infrared Transmitter** (38 kHz IR Emitter)
- **1x KY-022 Infrared Receiver** (IR Demodulator)
- **1x Hi-Link LD2420 Module** (24 GHz Human Presence & Micromotion Radar)
- **1x WIZnet W5500 Module** (SPI Ethernet Controller for hardware network isolation)

### Physical Navigation & Safety Controls
- **5x Push Buttons (J1–J5):** Connected to Raspberry Pi 5 GPIO header for local screen navigation:
  - `J1`: Navigation UP / NEXT
  - `J2`: Navigation DOWN / PREV
  - `J3`: SELECT / ENTER
  - `J4`: BACK / CANCEL
  - `J5`: ACTION / TRIGGER AI ANALYSIS
- **1x Mechanical Safety Switch (S1):** Master Killswitch / Lock connected to Pi 5 GPIO 21.

### Power & Mechanical Enclosure
- **5V 5A USB-C Power Supply** (Powering Raspberry Pi 5)
- **3D Printed CAD Enclosure** (Custom CAD chassis with 5-inch display bezel, button mounts, ventilation slots, standoffs, and SMA antenna pass-throughs).

---

## 3. EXACT ELECTRICAL PINOUT MAPPING

### A. ESP32 NodeMCU-32S Pinout (Shared SPI & Dedicated GPIOs)
*All SPI devices share `SCK` (GPIO18), `MOSI` (GPIO23), and `MISO` (GPIO19) on the primary SPI bus.*

| Peripheral / Module | Signal Line | ESP32 GPIO Pin | Notes |
| :--- | :--- | :--- | :--- |
| **Shared SPI Bus** | SCK / CLK | `GPIO 18` | Shared by nRF24 #1, nRF24 #2, CC1101, RC522, W5500 |
| | MOSI / SDI | `GPIO 23` | Shared SPI Data Out |
| | MISO / SDO | `GPIO 19` | Shared SPI Data In |
| **nRF24L01+ #1** | CE | `GPIO 27` | Chip Enable Radio 1 |
| | CSN | `GPIO 14` | Chip Select Radio 1 |
| **nRF24L01+ #2** | CE | `GPIO 17` | Chip Enable Radio 2 |
| | CSN | `GPIO 16` | Chip Select Radio 2 |
| **CC1101 Sub-GHz** | CSN | `GPIO 21` | Chip Select Sub-GHz Radio |
| | GDO0 (RX) | `GPIO 35` | Signal RX Input |
| | GDO2 (TX opt) | `GPIO 15` | Optional TX Jumper for Lab Replay |
| **RC522 RFID** | CS / SS | `GPIO 5` | Chip Select RFID |
| | RST | `GPIO 22` | Reset Line |
| **Hi-Link LD2420 Radar** | TX / OT2 | `GPIO 32` | Radar TX / Presence signal |
| | RX / OT1 | `GPIO 33` | Radar RX / Command |
| **IR Transceiver** | IR TX (KY-005) | `GPIO 26` | 38 kHz PWM Emitter |
| | IR RX (KY-022) | `GPIO 34` | Demodulated Input (Input-only pin) |
| **W5500 Ethernet** | CS | `GPIO 4` | SPI Chip Select Ethernet |

### B. Raspberry Pi 5 Navigation Buttons & Switch Pinout
| Control Element | Function | RPi 5 GPIO Pin | Configuration |
| :--- | :--- | :--- | :--- |
| **Switch S1** | Master Killswitch | `GPIO 21` | `INPUT_PULLUP` (Active LOW) |
| **Button J1** | UP / NEXT | `GPIO 17` | `INPUT_PULLUP` (Active LOW) |
| **Button J2** | DOWN / PREV | `GPIO 27` | `INPUT_PULLUP` (Active LOW) |
| **Button J3** | ENTER / SELECT | `GPIO 22` | `INPUT_PULLUP` (Active LOW) |
| **Button J4** | BACK / CANCEL | `GPIO 23` | `INPUT_PULLUP` (Active LOW) |
| **Button J5** | TRIGGER AI | `GPIO 24` | `INPUT_PULLUP` (Active LOW) |

---

## 4. SOFTWARE DEPENDENCIES & TECH STACK

### Raspberry Pi 5 Environment (Python / Linux)
- **OS:** Raspberry Pi OS 64-bit (Debian Bookworm)
- **Runtime:** Python 3.11+
- **Python Libraries (`requirements.txt`):**
  ```text
  fastapi>=0.110.0
  uvicorn[standard]>=0.28.0
  pydantic>=2.6.0
  google-genai>=0.1.0
  scapy>=2.5.0
  pyserial>=3.5
  gpiozero>=2.0
  jinja2>=3.1.3
  ```
- **System Tooling:** `iptables` / `ufw` (for active defense blocking), `sqlite3`.

### ESP32 Firmware Environment (C++ / PlatformIO)
- **Build System:** PlatformIO / Arduino Framework for ESP32
- **Key C++ Libraries (`platformio.ini`):**
  ```ini
  [env:nodemcu-32s]
  platform = espressif32
  board = nodemcu-32s
  framework = arduino
  monitor_speed = 115200
  lib_deps =
      nrf24/RF24 @ ^1.4.8
      lsatan/SmartRC-CC1101-Driver-Lib @ ^2.5.7
      miguelbalboa/MFRC522 @ ^1.4.11
      jandrop/Hi-Link LD2420 @ ^1.0.0
      z3no/IRremoteESP8266 @ ^2.8.6
      bblanchon/ArduinoJson @ ^7.0.4
      wiznet/Ethernet @ ^2.0.0
  ```

---

## 5. SQLITE DATABASE SCHEMA (`factory_sec.db`)

```sql
-- 1. Baseline Inventory (Authorized Factory Devices)
CREATE TABLE IF NOT EXISTS baseline_inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_ip TEXT UNIQUE NOT NULL,
    mac_address TEXT,
    device_name TEXT,
    role TEXT, -- e.g., 'PLC', 'Gateway', 'Operator_HMI', 'WLAN_AP'
    authorized_ports TEXT, -- JSON Array: "[80, 443, 502]"
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Live Network Scans & Observations
CREATE TABLE IF NOT EXISTS network_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_batch_id TEXT NOT NULL,
    device_ip TEXT NOT NULL,
    mac_address TEXT,
    open_ports TEXT, -- JSON Array: "[23, 80]"
    detected_services TEXT, -- JSON Object: "{\"23\": \"Telnet\", \"80\": \"HTTP\"}"
    status TEXT NOT NULL, -- 'ONLINE', 'MISSING', 'UNAUTHORIZED', 'CONFIG_CHANGED'
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. ESP32 Hardware Events
CREATE TABLE IF NOT EXISTS hardware_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_module TEXT NOT NULL, -- 'nRF24', 'CC1101', 'RC522_RFID', 'IR', 'LD2420_Radar'
    event_type TEXT NOT NULL, -- 'RF_SWEEP', 'RFID_READ', 'PRESENCE_DETECTED', 'IR_CAP'
    payload_data TEXT, -- JSON string
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 4. Remediation & Active Defense Logs
CREATE TABLE IF NOT EXISTS remediation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    target_ip TEXT NOT NULL,
    target_port INTEGER NOT NULL,
    action_taken TEXT NOT NULL, -- 'BLOCK_TCP', 'ISOLATE_HOST', 'ALERT'
    status_before TEXT, -- e.g., 'OPEN'
    status_after TEXT, -- e.g., 'FILTERED'
    is_success INTEGER, -- 1 = True, 0 = False
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 5. On-Demand Gemini AI Reports
CREATE TABLE IF NOT EXISTS ai_analysis_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_batch_id TEXT NOT NULL,
    overall_threat_score INTEGER NOT NULL, -- 0 to 100
    report_json TEXT NOT NULL, -- Pydantic structured output JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. USB-SERIAL JSON COMMUNICATION PROTOCOL

The Pi 5 sends commands to ESP32 over Serial (`/dev/ttyUSB0` @ 115200 baud):
- **Command from Pi 5 -> ESP32:**
  `{"cmd": "POLL_HARDWARE"}\n`
- **Response from ESP32 -> Pi 5:**
  ```json
  {
    "status": "OK",
    "radar_presence": true,
    "last_rfid": "0x90A12B33",
    "ir_activity": false,
    "rf_subghz_rssi": -65,
    "nrf24_status": "ACTIVE"
  }
  ```

---

## 7. GEMINI AI ANALYSIS & CLOSED-LOOP RETEST SPECIFICATION

### Pydantic Schema for Gemini Structured Output
```python
from pydantic import BaseModel, Field

class VulnerabilityFinding(BaseModel):
    target_ip: str
    risk_level: str = Field(description="CRITICAL, HIGH, MEDIUM, LOW, or INFO")
    is_justified: bool = Field(description="True if legitimate OT exposure, False if anomaly")
    description: str = Field(description="Summary of finding in Romanian")
    recommended_remediation: str = Field(description="Action to execute, e.g., BLOCK_TCP_23")

class AIAnalysisReport(BaseModel):
    overall_threat_score: int = Field(description="Overall threat rating from 0 to 100")
    summary: str = Field(description="Executive summary in Romanian")
    findings: list[VulnerabilityFinding]
```

### Closed-Loop Retest Cycle:
1. **Observe:** Run Scapy ARP/TCP sweep + collect ESP32 hardware logs.
2. **Analyze:** Send JSON payload to `gemini-2.5-flash` on-demand via `J5` button press or API. Save output to `ai_analysis_reports`.
3. **Remediate:** Execute active defense command (e.g., `sudo iptables -A INPUT -p tcp --dport 23 -j DROP`).
4. **Retest:** Automatically re-probe target port with Scapy. Log `status_before` (OPEN) vs `status_after` (FILTERED) in `remediation_logs` and update screen UI.

---

## 8. CODEBASE DIRECTORY STRUCTURE

```
/
├── platformio.ini              # ESP32 firmware build setup
├── src/                        # ESP32 C++ source files
│   ├── main.cpp                # SPI multiplexer & serial handler
│   ├── SerialProtocol.cpp      # JSON RPC UART parser
│   └── Peripherals.cpp         # Drivers for RF, RFID, IR, Radar, W5500
├── app/                        # Raspberry Pi 5 Python Application
│   ├── main.py                 # FastAPI Web Server entry point
│   ├── hardware_buttons.py     # GPIO button listener (J1-J5, S1)
│   ├── network_engine.py       # Scapy scanner & SQLite baseline diff
│   ├── ai_analyzer.py          # Google Gemini 2.5 API integration
│   ├── defense_engine.py       # Iptables blocking & auto-retest logic
│   └── database.py             # SQLite database initializer & DAO
├── templates/                  # HTML UI for 800x480 touchscreen
│   └── index.html              # Cyberdeck Dashboard UI
└── requirements.txt            # Python dependencies
```
