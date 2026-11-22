#include <Arduino.h>
#include <ArduinoJson.h>
#include "SerialProtocol.h"
#include "Peripherals.h"

void serialProtocolTick() {
    static char line[512];
    static size_t length=0;
    static bool discard=false;
    // Bound work so a noisy host cannot starve the watchdog.
    unsigned int budget=128;
    while (Serial.available() && budget--) {
        char c=Serial.read();
        if (c=='\r') continue;
        if (c!='\n') {
            if (length<sizeof(line)-1 && !discard) line[length++]=c;
            else discard=true;
            continue;
        }
        line[length]=0;
        JsonDocument command, response;
        auto error=deserializeJson(command,line);
        if (discard || error || !command.is<JsonObject>()) {
            response["status"]="ERROR";
            response["message"]="Invalid JSON command";
        } else {
            response["request_id"]=command["request_id"] | "";
            const char* cmd=command["cmd"] | "";
            if (!strcmp(cmd,"POLL_HARDWARE")) peripheralsPoll(response);
            else if (!strcmp(cmd,"WIFI_SCAN_START") || !strcmp(cmd,"WIFI_SCAN_PAGE") || !strcmp(cmd,"WIFI_SCAN_CANCEL"))
                peripheralsWifiCommand(command,response);
            else if (!strcmp(cmd,"TEST_START") || !strcmp(cmd,"TEST_STATUS") || !strcmp(cmd,"TEST_CANCEL")) {
                peripheralsTestCommand(command,response);
            }
            else if (!strcmp(cmd,"STOP")) {
                peripheralsStop();
                response["status"]="STOPPED";
            } else {
                response["status"]="ERROR";
                response["message"]="Unsupported command";
            }
        }
        serializeJson(response,Serial);
        Serial.println();
        length=0; discard=false;
    }
}
