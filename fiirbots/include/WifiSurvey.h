#pragma once
#include <ArduinoJson.h>

void wifiSurveyCommand(const JsonDocument& command, JsonDocument& response, bool monitorActive);
void wifiSurveyTick();
void wifiSurveyStop();
