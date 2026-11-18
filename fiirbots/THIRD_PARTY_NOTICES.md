# Third-party notices

The receiver-side carrier sampling design is adapted from `src/RadioScanner.cpp` in the adjacent CYBERDECK MINI ESP32 V2 project by José Ángel Chávez Félix (PepeAngell). Its MIT license is retained in `LICENSE`. The Pi application and headless ESP32 integration are newly implemented for the FIIRBots specification.

Firmware dependencies remain under their respective upstream licenses: RF24, SmartRC-CC1101-Driver-Lib, MFRC522, IRremoteESP8266 and ArduinoJson. Python dependencies likewise retain their upstream licenses. No dependency sources are vendored into the application source directories.

The LD2420 basic status protocol was checked against the ESPHome documentation and implementation; ESPHome source code is not copied into the firmware.
