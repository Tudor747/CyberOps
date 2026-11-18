# Validation record

- NodeMCU-32S release firmware: **build passed** with PlatformIO Espressif32 6.4.0 / Arduino 2.0.11.
- Firmware memory: 23,208 bytes RAM; 370,641 bytes application flash.
- Python application: **12 tests passed** using unittest on Python 3.14. Tests cover scope limits, baseline changes, cancelled/interrupted batches, inconclusive retests, serial correlation/type checking, stale-poll suppression after S1, AI cancellation, action tokens and S1 latch behavior.
- JavaScript: `node --check static/app.js` passed.
- Deployment scripts: Bash syntax checks passed. They were not executed on this Windows development host.
- Browser: Chrome headless at 800×480; all five tabs, enrollment dialog and physical-button focus navigation passed; no JavaScript errors or horizontal page overflow. Screenshot: `test-results/dashboard-800x480.png`.
- The local preview starts without GPIO, serial, scan subnet or Gemini credentials. No live network scan, Gemini API request, board flashing or system reboot was performed.

## Hardware acceptance still required

1. Install on Raspberry Pi OS 64-bit Desktop with labwc. Set the authorized subnet, interface and stable serial path.
2. Confirm the application opens automatically after a cold boot without a keyboard login.
3. Confirm J1–J5 and S1 on the specified BCM pins. Activate S1 during a scan; verify cancellation and exactly one reboot. Leave S1 active across boot and verify no reboot loop, then release it.
4. Connect each module and compare readings with known test conditions. Check LD2420 UART baud/basic status mode in particular.
5. Unplug USB and verify stale telemetry is cleared and the ESP32 stops within its heartbeat timeout.
6. Run a scan against the authorized lab subnet. Enroll a known device, change a test service and verify the baseline difference. Confirm a timeout is not reported as proven filtering.
7. Configure a Gemini key and verify an on-demand English report. No recommendation should execute a network change.

Hardware acceptance steps are pending; passing compilation and mocked tests does not imply that they passed.
