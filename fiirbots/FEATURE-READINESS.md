# Full Cyberdeck integration readiness

Assessment date: 2026-11-18.

The existing FIIRBots monitor can proceed to a first Pi installation. Full
Cyberdeck feature parity is **not ready**. Copying the reference firmware folder
to the Pi does not provide executable Pi backends or serial commands for its tools.

## Hardware and scope

- Repository target: Raspberry Pi 5 plus NodeMCU-32S / ESP32-WROOM-32.
- Reference firmware target: ESP32-S3 with its own screen and input handling.
- User confirms an isolated, authorized Wi-Fi test laboratory.
- User accepts the repository's NodeMCU-32S / ESP32-WROOM-32 and W5500 identifiers.
  The earlier description of a second ESP "nano" does not establish its firmware,
  USB connection, or a second controllable radio.
- W5500 is listed in the repository. Its current integration checks SPI/link;
  it does not provide a Wi-Fi backend or a network gateway.
- Nonworking peripherals are excluded from live acceptance, not marked as passed.

## Pi radio evidence supplied by the user

The supplied `iw list` reports one PHY (`phy0`), 2.4/5 GHz bands, and managed,
AP, IBSS and P2P modes. Neither supported interface modes nor software interface
modes list `monitor`. The USB inventory contains root hubs and a Trust wireless
mouse; no external USB Wi-Fi adapter or ESP serial device is listed. An onboard
Wi-Fi device is a plausible explanation, but chipset/driver identity is not
established by these outputs.

| Capability | Conclusion from supplied evidence |
| --- | --- |
| Ordinary Wi-Fi observation and LAN operation | Relevant client capabilities advertised; actual FIIRBots scan still needs Pi acceptance |
| Access point | AP mode advertised; no AP service configured or tested by this assessment |
| Concurrent client + AP | Advertised combination requires one channel; do not assume independent channels |
| Raw Wi-Fi monitor capture | Monitor mode not advertised by the current driver/firmware configuration |
| Arbitrary packet injection | Unverified; TX management frame type listings are not a successful injection test |
| KARMA / Deauther | Bounded lab backends now implemented; supplied hardware still does not establish monitor/injection support or successful operation |
| ESP-controlled radio functions | Board identification alone does not supply a protocol/backend or firmware acceptance |

Linux distinguishes managed, AP and monitor operation; see the official
[wireless modes documentation](https://wireless.docs.kernel.org/en/latest/en/users/documentation/modes.html).
The documented [mac80211 injection path](https://www.kernel.org/doc/html/latest/networking/mac80211-injection.html)
uses a monitor interface. Do not treat AP support as proof of that path.

Full radio acceptance therefore remains blocked on a suitable, verified execution
backend and physical verification. Existing monitor-free features
can proceed independently. No claim is made that a different firmware or an ESP
backend is impossible; neither has been validated here.

## Evidence collected

- 56 offline Python tests passed on Windows with Python 3.14, including seven new
  Linux-backend contract tests. Linux subprocess and Scapy operations are mocked.
- New coverage checks Wi-Fi command output, permission denial, missing commands,
  timeout, ARP response scope, raw-packet permission errors, and cancellation
  before and after discovery.
- JavaScript syntax checks passed for `app.js` and `tools.js`.
- Chrome smoke tests passed at 800x480, 1440x900 and 390x844, including the new
  tool panels and empty/unavailable states. No JS errors or horizontal overflow.
- Scapy 2.8.0 and Bleak 3.1.0 were installed into an ignored verification directory;
  frame parsing tests use real Scapy packet objects. Receive/transmit sockets and
  BLE devices are replaced in offline tests. No packets were transmitted by tests.
- No Pi deployment, live radio transmission, board flashing, or hardware test
  was performed for this assessment. Historical desktop live checks are recorded
  separately in CYBERDECK-VALIDATION.md.

## Implementation and acceptance matrix

These groups cover the existing UI catalog. A catalog entry alone is not a
working implementation, and an implemented function is not automatically tested
on the Pi.

| Functions | Current integration | Remaining acceptance / work |
| --- | --- | --- |
| LAN discovery, bounded TCP scan, baseline inventory | Implemented; offline coverage | Real Pi scan on the selected lab interface; known open/closed/timeout controls; persistence and cancellation |
| WiFi Scanner | OS command backend; Linux contract tests | Real adapter and service-account permissions on Pi |
| Mission Dashboard, reports / Gemini, settings / system info, clock, reference catalog | Implemented; selected offline coverage and historical browser checks | Pi touchscreen/kiosk, host readings, report export and optional live AI acceptance |
| Threat Monitor, WiFi Audit, Probe Sniffer, Packet Monitor | Implemented: bounded capture, frame counts, probe metadata, AP privacy/RSN observations and management events | Existing Linux monitor interface and real reception validation; counts are not attack verdicts |
| Physical activity indicators / buzzer | NOT_PORTED | GPIO mapping and real indicator backend |
| Deauther | Bounded selected-client lab test, 1–10 frames, recently observed pair, channel check, cancellation and audit trail | Working monitor/injection radio; independent over-air and client-effect validation |
| KARMA / beacon test | Bounded selected-probe SSID advertising, matching reference beacon behavior; temporary BSSID; 1–10 frames | Working 2.4 GHz monitor/injection radio; verify reception; no AP service, association handler or continuous flooding |
| Evil Portal | NOT_PORTED | No captive portal or credential collection backend |
| 2.4 GHz spectrum, nRF24 #1/#2 diagnostics | Hardware integration exists | Known-input physical validation; carrier occupancy is not calibrated dBm |
| RF Waterfall / frequency bins, RF Baseline | Implemented: timestamped historical occupancy, fresh-sample baseline, delta comparison | Known RF samples on working nRF24 modules; no inferred Wi-Fi channel decoding |
| BLE Scanner | Implemented with Bleak, exclusive cancellable jobs, saved completed observations and UI; four offline backend tests | Install updated dependencies; verify Bluetooth service/permissions and real Pi discovery |
| BLE Defense | Implemented: explicit enrollment, persisted baseline, changed/unregistered/not-observed comparison | Real device acceptance; rotating addresses can change apparent identity |
| BLE Spam, BT Disruptor, BT Jammer, Channel jammer | NOT_PORTED | Separate capability and scope review; unavailable functions must remain explicit |
| GPS dashboard, tracks, waypoints, course over ground | Implemented via local gpsd protocol v3, fresh finite fixes, saved tracks/waypoints and GeoJSON export | Working GPS receiver and gpsd on 127.0.0.1:2947; no stationary magnetic compass or embedded map |
| Snapshot / wardriving | NOT_PORTED | Correlated GPS and wireless observation logging |
| MicroSD Manager / Info, ESP32 battery ADC | NOT_PORTED | Board-specific storage/ADC protocol and measurements; host disk/battery is separate |
| Weather / on-screen keyboard | Weather NOT_PORTED; keyboard delegated to OS | Weather integration if required; actual touch text-entry acceptance |
| RFID/NFC, 433 MHz receive, IR receive / loopback, radar, W5500 | Hardware/diagnostic integration exists | Per-module physical acceptance; exclude broken modules and preserve unavailable/error states |
| GPIO buttons, S1 stop/reboot, serial reconnect/watchdog | Implemented; partial offline coverage | Pi GPIO and real serial/reboot acceptance; disabled in hardware-free deployment |

## Integration sequence

1. Initial Pi `iw list` and USB evidence has been received. Collect the remaining
   OS, driver and service inventory with `bash deploy/preflight.sh`; it does not
   scan networks or transmit test frames.
2. Verify board connections/firmware and the Wi-Fi chipset. Select the actual execution
   backend for each missing feature; do not flash an S3 build onto a WROOM board.
3. Establish Pi acceptance for the implemented scan/dashboard/storage functions.
4. Implement and test missing observation backends and their UI integration.
5. Define each active laboratory test separately, including participating devices,
   duration, stop behavior and an independent observable success criterion.
6. Retain per-feature evidence: source revision, OS/driver/firmware versions,
   automated results, actual devices, observed outcome and remaining limitations.

Full-feature readiness requires working backends and actual acceptance evidence.
Neither a successful build nor mocked tests can substitute for radio validation.

## Current limits of the port

This is not full feature parity. The remaining NOT_PORTED entries are deliberate
status reports, not runnable buttons. Firmware for the user's ESP boards has not
been changed by this integration. Existing sensor functionality is reused.
The original UI, autonomous channel hopping, continuous beacon flooding, captive
portal, BLE advertising disruption, radio jammers, ESP microSD/ADC integration,
weather and wardriving are not supplied by these new Pi backends.

Full validation on the supplied Pi is blocked for raw Wi-Fi functions because
its current driver does not advertise monitor mode. The implementation does not
switch interfaces, install alternative radio firmware or change NetworkManager.
