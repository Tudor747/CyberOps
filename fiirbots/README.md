# FIIRBots · Industrial Field Monitor

## Cyberdeck dashboard

### Test on a Windows PC without Raspberry Pi

Run `./start-preview.ps1`, open `http://127.0.0.1:8000`, and reload the page
after restarting the server. GPIO, reboot and serial hardware are disabled in
this launcher. The desktop database is separate (`data/dashboard-preview.db`).

1. Open **Network → Refresh adapters**. Select the real LAN/Wi-Fi adapter,
   rather than a VirtualBox or Hyper-V virtual adapter.
2. Check the suggested private IPv4 scope, then click **Apply network** and
   **Scan**. The application accepts an on-link segment of at most 256 addresses.
   The selected adapter/subnet lasts for this server session; choose it again
   after restarting. Scans never start automatically.
3. Inspect MAC addresses and open ports in **Network**. A timeout is inconclusive.
   `UNAUTHORIZED` means absent from your inventory, not proof of an intruder.
   Enroll recognized devices in **Inventory** to establish a baseline.
4. Open **Reports → Analyze with Gemini** after a completed scan, then export
   the report as JSON. This sends scan/baseline data and recent hardware events
   to Gemini only on request.
5. Open **All tools** for the complete reference-feature catalog, **Scan Wi-Fi**
   for the OS observation output, and **Refresh system info** for real host
   CPU, RAM, storage and battery readings.

Windows ARP discovery uses the native [SendARP API](https://learn.microsoft.com/en-us/windows/win32/api/iphlpapi/nf-iphlpapi-sendarp)
with a selected source address, so this path does not require Npcap. TCP checks
also bind to that source. Linux uses Scapy ARP and requires raw-packet permission.
Wi-Fi observations use `netsh wlan` on Windows or `nmcli` on Linux; adapter and
OS permissions determine what is available. The app displays the original OS
output instead of assuming locale-specific field names.

The **All tools** catalog is an implementation-status list, not a claim of
full firmware parity. `PC` tools are implemented; `HARDWARE` tools need the
FIIRBots ESP32 firmware and matching peripherals. `NOT_PORTED` means no working
application backend exists yet, even if the original firmware contains it.
BLE inventory comparison, bounded raw Wi-Fi observation, RF history/baseline,
GPS via gpsd, and limited selected-target lab radio tests now have Pi backends.
Their hardware requirements and remaining gaps are in `FEATURE-READINESS.md`.
This is not a full port: wardriving, microSD/ADC, weather, captive portal and
radio-disruption functions remain unavailable.
The original CYBERDECK firmware cannot be controlled by the FIIRBots serial
protocol without an adapter or firmware changes. No hardware is simulated.

The local dashboard now includes touch shortcuts for Network, Radio spectrum,
RFID/NFC and IR/sensors, plus a Gemini analyst panel. It retains live hardware
readings, scan history, baseline comparisons, manual tests and JSON exports.
Missing hardware is displayed as unavailable; readings are never simulated.

Local startup automatically reads `fiirbots/.env`. Existing process environment
values (including systemd's `/etc/fiirbots.env`) take precedence. Configure
`GEMINI_API_KEY` and `GEMINI_MODEL`, restart the server, then open **Reports →
Test AI connection**. This makes a small real generation request without sending
scan data. An empty key returns `NOT_CONFIGURED`; it is not an API success.
After a completed network scan, **Analyze with Gemini** sends the scan, baseline
and recent hardware events for a structured report. The key stays on the server.

On Windows, the supplied `.env` may contain Raspberry Pi paths and GPIO settings.
For a desktop preview, override them before starting:

```powershell
$env:FIIRBOTS_GPIO_ENABLED='0'
$env:FIIRBOTS_REBOOT_ENABLED='0'
$env:FIIRBOTS_SERIAL_PORT=''
$env:FIIRBOTS_SCAN_NETWORK=''
$env:FIIRBOTS_DB='data/dashboard-preview.db'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

English-language standalone monitoring application for Raspberry Pi 5 and a NodeMCU-32S / ESP32-WROOM-32 peripheral controller. Built from `sdmc-fiirbots-agent-skill.md` and the user's confirmed changes.

The Pi connects to an existing network as an ordinary client. It discovers devices, compares observations against an explicit baseline, stores results locally and requests Gemini analysis on demand. It **does not act as a gateway, change firewall rules, isolate other hosts or execute AI recommendations**.

## What is implemented

### BLE discovery

The All tools page includes **Scan BLE (10 s)**, Stop, and Refresh BLE results.
Discovery uses Bleak's standard active advertisement scanning without connecting
or pairing. It shares the exclusive job controller with LAN scans and honors
Stop/S1. Only completed observations are saved; refreshing after a cancelled or
failed scan shows the previous completed result with its timestamp.

Install the updated requirements in the application's virtual environment.
On Raspberry Pi, a working Bluetooth adapter, running BlueZ service and D-Bus
permissions for the `fiirbots` service user are required. These have not yet been
validated on the Pi. No adapter, blocked Bluetooth or denied permissions produce
an error, not a successful empty inventory. BLE addresses may rotate; this is
discovery, not persistent identity. The separate BLE inventory panel adds explicit
enrollment and comparison. Offline tests use a fake
scanner and do not demonstrate reception on hardware.

Backend API reference: [BleakScanner](https://bleak.readthedocs.io/en/stable/api/scanner.html).

### Observation and laboratory tools

All tools now provides:

- Wireless packet counts, probe observations, AP privacy/RSN flags and
  deauthentication/disassociation events. Select an existing Linux monitor
  interface. The app never changes its mode or channel. Observation lasts 1–30
  seconds and retains bounded metadata rather than traffic payloads.
- BLE enrollment/comparison against a persistent, explicit baseline. Refresh the
  latest completed scan, then enroll recognized devices individually.
- RF waterfall and baseline comparison from saved nRF24 sweeps. A baseline
  requires fresh connected hardware. Missing samples are never plotted as zeros.
- GPS observation through a separately configured local gpsd on port 2947.
  Fresh fixes are stored as tracks; saved positions can become named waypoints.
  GeoJSON exports include up to 100 recent tracks and 100 waypoints. Course over
  ground is not a stationary magnetic compass.
- A selected-client deauthentication lab test and a selected-probe KARMA beacon
  test. Both require an isolated authorized lab, an observation no older than
  five minutes and a working monitor/injection radio. Each request is limited to
  1–10 frames on the observed channel. The KARMA port advertises one selected
  SSID, like the reference beacon behavior; it is not a usable AP or portal.
  Results record submissions to the driver and always leave the actual effect
  unverified. Confirm reception/client behavior independently.

These operations share the existing exclusive job controller and Stop/S1
cancellation. Completed observations persist; cancelled observations do not
replace them. Lab transmission attempts are logged even when cancelled or failed.
The global job banner shows errors; saved results retain their original timestamps.
Export observations using the JSON link or GPS tracks using GeoJSON.

For an existing installation, copy the updated project and rerun the installer
to update Python dependencies, then restart the service. BLE additionally needs
BlueZ and D-Bus permissions for the service user; gpsd and its receiver must be
configured separately. No Pi hardware acceptance has been performed here.

API implementation references: [Scapy capture](https://scapy.readthedocs.io/en/latest/api/scapy.sendrecv.html),
[802.11 layers](https://scapy.readthedocs.io/en/latest/api/scapy.layers.dot11.html),
[gpsd protocol](https://gpsd.gitlab.io/gpsd/gpsd_json.html).

### Existing monitoring functions

- Local FastAPI dashboard sized for an 800×480 touchscreen: Overview, Network, Hardware, Inventory and Reports.
- SQLite persistence for the five specified tables, plus scan batch completion/cancellation tracking.
- On-link Scapy ARP discovery and bounded TCP connect checks, with one job at a time and cancellation. TCP probes send no application payloads.
- Explicit inventory enrollment and comparisons of observed MAC addresses and open ports.
- On-demand structured Gemini reports in English, with validated scores and target addresses. J5 triggers analysis of the latest completed scan.
- Operator-triggered retest of a previously open port; results are OPEN, CLOSED, NO_RESPONSE or ERROR. A timeout is inconclusive, never proof of filtering or successful remediation.
- USB serial polling, request correlation, validated samples, reconnection and stale-data handling. Missing sensors show unknown, not fabricated readings.
- Physical navigation using J1–J4; S1 stops jobs and requests a Pi reboot. Held S1 at boot locks operations without another reboot. Scans never restart automatically.
- A systemd service and Chromium kiosk launcher for automatic startup.

## Layout

```text
app/             Raspberry Pi server, database, scanner, GPIO and serial integration
templates/       Dashboard HTML
static/          Local CSS and JavaScript (no CDN or build step)
src/             NodeMCU-32S firmware
include/         Firmware pin map and headers
deploy/          Raspberry Pi service and installation scripts
tests/           Offline application tests
dist/            Compiled NodeMCU firmware artifacts
platformio.ini   Separate build target; does not replace the original S3 firmware
```

The adjacent `CYBERDECK-MINI-ESP32-V2` remains the reference project. Its receiver-side RF carrier-sampling approach informed the new radio monitor; its display/menu loops and transmit tools are not part of this firmware. See `THIRD_PARTY_NOTICES.md` and `LICENSE` for attribution.

## Desktop preview and tests

Python 3.11 or later:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-dev.txt
.\.venv\Scripts\python -m unittest discover -s tests -v
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`. GPIO, serial and reboot are disabled unless configured. An unconfigured subnet disables scanning. Local development is possible without a Pi, ESP32 or Gemini key; disconnected hardware is clearly displayed. Do not start multiple server workers: the GPIO, serial link and job controller have one owner.

## Install on Raspberry Pi 5

Use Raspberry Pi OS 64-bit **with Desktop and labwc**, with the 800×480 HDMI screen and its USB touch connection working first. Copy this `fiirbots` folder to the Pi, then run from it:

```bash
sudo bash deploy/install.sh
sudo nano /etc/fiirbots.env
```

Set these values for your own authorized local network:

```text
FIIRBOTS_SCAN_NETWORK=192.168.1.0/24
FIIRBOTS_SCAN_INTERFACE=eth0
FIIRBOTS_SERIAL_PORT=/dev/ttyUSB0
FIIRBOTS_GPIO_ENABLED=1
FIIRBOTS_REBOOT_ENABLED=1
FIIRBOTS_DB=/var/lib/fiirbots/factory_sec.db
GEMINI_API_KEY=your-key-here
GEMINI_MODEL=gemini-2.5-flash
```

The installer deliberately leaves the subnet empty until you configure it. Only private IPv4 ranges with at most 256 addresses are accepted. Use an on-link subnet on the selected interface; the included ARP discovery is not a routed-network inventory tool. For a stable serial path, prefer the ESP32's `/dev/serial/by-id/...` entry if present.

The installer enables **Desktop Autologin** for your existing desktop user through `raspi-config` and adds the kiosk launcher to that user's `~/.config/labwc/autostart`. If running as root directly, pass the desktop username to `install.sh`. The UI waits for the local server and reopens Chromium if it exits.

```bash
sudo systemctl restart fiirbots
sudo reboot
```

The Pi now starts the server and opens the dashboard full-screen automatically, including after an S1 reboot. The service runs as the dedicated `fiirbots` user with serial/GPIO group access and raw-packet capability. A narrowly scoped sudoers rule permits only `/usr/bin/systemctl reboot`. The web server listens on loopback and uses a per-process action token; it is not intended to be exposed directly to the LAN or Internet.

Touch-only text entry requires the Raspberry Pi desktop's on-screen keyboard, or a USB keyboard for initial enrollment. The five buttons support navigation and actions, not arbitrary text entry.

## Controls

All Pi pins use **BCM numbering**, active LOW with internal pull-ups; wire switches to GND.

| Control | GPIO | Behavior |
| --- | ---: | --- |
| J1 | 17 | Focus next visible control |
| J2 | 27 | Focus previous visible control |
| J3 | 22 | Activate focused control |
| J4 | 23 | Cancel current job; close dialog or return to Overview |
| J5 | 24 | Request AI analysis of the latest completed scan |
| S1 | 21 | Stop jobs, send STOP to ESP32, record event, request Pi reboot |

After S1 activation, the application remains locked until reboot. If S1 is still held at boot, operations remain locked until it is released. This avoids a reboot loop. A GPIO initialization failure also locks operations instead of silently disabling S1. Pi 5 RP1 GPIO chip numbering is detected from sysfs; `FIIRBOTS_GPIO_CHIP` can override it if necessary.

## Firmware and wiring

```bash
pio run
pio run -t upload
```

Target: **NodeMCU-32S / ESP32-WROOM-32, 4 MB flash**. This binary is not for the reference project's ESP32-S3.

Prebuilt files are in `dist/`. Flash `fiirbots-nodemcu32s-merged.bin` at offset `0x0`, or use the individual offsets in `dist/FLASH_OFFSETS.txt`. `dist/SHA256SUMS.txt` records the artifact checksums. Rebuild these artifacts after any firmware source change.

| Peripheral | Signals → ESP32 GPIO |
| --- | --- |
| Shared SPI | SCK 18, MOSI 23, MISO 19 |
| nRF24 #1 | CE 27, CSN 14 |
| nRF24 #2 | CE 17, CSN 16 |
| CC1101 | CSN 21, GDO0 35, GDO2 15 (input, unused for transmission) |
| RC522 | CS 5, RST 22 |
| LD2420 | Module TX → ESP RX 32; module RX → ESP TX 33 |
| IR | KY-022 RX 34; KY-005 TX 26 held LOW |
| W5500 | CS 4 |

Receiver behavior:

- **nRF24:** carrier detections across 2400–2480 MHz, eight samples per bin. This is occupancy sampling, not calibrated RSSI or packet decoding. Auto-ack is disabled.
- **CC1101:** receive-only RSSI at 433.92 MHz. No Sub-GHz replay/transmission commands are implemented in monitor mode.
- **RC522:** UID reads only. Reader field is enabled during monitoring and disabled by STOP.
- **IR:** decoded receive codes; no IR transmission.
- **LD2420:** basic text status mode (`ON` / `OFF`) over UART at 115200 baud. If your module uses older 256000-baud firmware, change `RADAR_BAUD` in `platformio.ini`. Energy/binary report mode requires module configuration or a matching parser; unsupported/silent output remains unknown. The firmware does not rewrite radar calibration or firmware settings.
- **W5500:** chip version and physical link status through direct SPI register reads. No IP stack, DHCP or network isolation is configured on the ESP32 in the selected standalone architecture.

SPI chip selects are released before switching devices. Firmware starts stopped, resumes on `POLL_HARDWARE`, and stops if polls disappear for 3.5 seconds. A task watchdog resets a stalled peripheral loop. STOP does not cut power to external modules such as the radar; S1 is a software scan-stop/reboot control, not an electrical power disconnect.

## Serial protocol

Newline-delimited JSON at 115200 baud, with a request identifier echoed by the ESP32:

```json
{"cmd":"POLL_HARDWARE","request_id":"123"}
```

Response fields include the specified `status`, `radar_presence`, `last_rfid`, `ir_activity`, `rf_subghz_rssi` and `nrf24_status`, plus `rf_bins`, `ir_last_code`, RFID age and Ethernet link status. Unknown measurements are `null`. `{"cmd":"STOP","request_id":"124"}` returns `STOPPED`; malformed and unknown commands return `ERROR`. Bootloader text and unmatched replies are ignored by the host.

## AI and interpretation

The Gemini key stays on the Pi. Pressing AI analysis or J5 sends the latest completed scan, baseline and up to 20 recent hardware events to Google Gemini. No background AI requests occur. Network-derived labels are treated as untrusted evidence, and AI output is never executed. Model name is configurable; API availability depends on your Google account.

Service names are inferred from port numbers. Missing hosts can reflect filtering or network loss, and a changed MAC can reflect legitimate replacement. These observations require context; they are not proof of compromise. Baseline authorization is an explicit operator action rather than automatic enrollment of everything discovered.

## Troubleshooting and validation limits

If installation fails with `cannot find -llgpio`, the native lgpio development
library is missing. The installer now includes `swig` and `liblgpio-dev` before
installing Python dependencies and checks that `lgpio` imports successfully.
To recover an installation made with an older installer, run from the project
folder on the Pi:

```bash
sudo apt update
sudo apt install -y liblgpio-dev swig python3-dev build-essential
sudo bash deploy/install.sh
```

Rerun the complete installer so service/environment setup after the failed pip
step also finishes. Existing `/etc/fiirbots.env` and the database are retained.
See [GPIO Zero virtual environment installation](https://gpiozero.readthedocs.io/en/stable/installing.html).

```bash
sudo systemctl status fiirbots
sudo journalctl -u fiirbots -n 100 --no-pager
ls /dev/serial/by-id/
```

- **Scanning disabled:** configure the subnet, check S1/GPIO state and restart the service.
- **Discovery error:** verify interface, on-link subnet and raw-packet capability. A failed/aborted scan does not commit a partial baseline comparison.
- **Hardware unknown:** verify the USB device, flash the NodeMCU firmware, check module power/wiring and radar baud/output mode.
- **Kiosk does not start:** verify Desktop Autologin, labwc desktop and `~/.config/labwc/autostart`. This installer does not target older X11/Wayfire sessions.
- **S1 cannot reboot:** check the service log and the installed sudoers rule. Scans remain stopped even if reboot fails.

Automated tests mock network/hardware/AI operations. A firmware build verifies compilation, not electrical operation. Physical sensor behavior, Pi GPIO, S1 reboot and boot-time kiosk startup must be checked on the assembled device. No live network scan, hardware flashing or Gemini request is performed by the test suite.

## Primary references

- [Raspberry Pi kiosk setup](https://www.raspberrypi.com/tutorials/how-to-use-a-raspberry-pi-in-kiosk-mode/)
- [Google Gen AI SDK and structured output](https://googleapis.github.io/python-genai/)
- [LD2420 baud-rate and mode notes](https://esphome.io/components/sensor/ld2420/)
- [LD2420 protocol implementation reference](https://github.com/esphome/esphome/blob/dev/esphome/components/ld2420/ld2420.cpp)
