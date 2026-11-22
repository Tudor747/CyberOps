#pragma once
#include <ArduinoJson.h>
void peripheralsBegin();
void peripheralsTick();
void peripheralsStop();
void peripheralsPoll(JsonDocument& response);
void peripheralsWifiCommand(const JsonDocument& command, JsonDocument& response);
void peripheralsTestCommand(const JsonDocument& command, JsonDocument& response);
