# Cyberdeck desktop validation - 2026-11-18

- Python: 21 tests passed, including adapter/scope validation, action tokens,
  locked/running configuration rejection, Windows TCP timeout handling, AI
  schemas, missing keys, secret redaction and rejection of unobserved AI targets.
- JavaScript syntax check passed.
- Chrome: seven tabs, tool catalog/filter, system info, module shortcuts,
  enrollment dialog and physical-button focus passed. No JavaScript errors or
  horizontal page overflow at 800x480, 1440x900 or 390x844. Screenshots are in
  the ignored test-results directory.
- Real LAN discovery completed on Wi-Fi, 192.168.0.0/24: six devices observed.
  Native Windows ARP worked without Npcap. TCP connected to 80/443 on the router
  and 445/8080 on this PC. Port labels are inferred, not service fingerprints.
  All devices are unregistered because the inventory is empty.
- Wi-Fi: the OS returned three visible networks with BSSID/channel/signal and
  security information. Host CPU/RAM/disk/battery returned real observations.
- Gemini: live connection and synthetic structured output succeeded. After the
  user's explicit approval to transfer LAN observations, real analysis completed
  and was saved for the six-device scan. Scores are model judgments; an empty
  inventory does not establish that a device is malicious.
- Export JSON contains the completed scan, AI report and retest. A real retest
  confirmed that the router's port 80 remains OPEN (no remediation was applied).
- Fixed Windows connect_ex timeout code 10035 being treated as a fatal error.
  It is now NO_RESPONSE. Gemini uses a compact response_json_schema, with strict
  Pydantic constraints and observed-target validation still enforced locally.
- Earlier browser failures were resolved by running Chrome outside the restricted
  environment. The earlier missing-key status is obsolete: the user supplied a
  working Gemini key.

## Limits

No Raspberry Pi, ESP32, GPIO, RF/RFID/IR/radar/GPS or microSD was tested. The
catalog marks unimplemented functions explicitly. It is not full feature parity
with the CYBERDECK MINI firmware. See README for desktop tools and requirements.

Run ./start-preview.ps1, open http://127.0.0.1:8000, and reload after a restart.
Network selection is session-only and must be applied again after restarting.
Scan history and reports persist in data/dashboard-preview.db.
