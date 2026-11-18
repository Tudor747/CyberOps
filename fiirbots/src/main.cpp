#include <Arduino.h>
#include <esp_task_wdt.h>
#include "Peripherals.h"
#include "SerialProtocol.h"

void setup() {
    Serial.begin(115200);
    // A failed SPI peripheral must not leave the command loop hung indefinitely.
    esp_task_wdt_init(3,true);
    esp_task_wdt_add(nullptr);
    peripheralsBegin();
}

void loop() {
    esp_task_wdt_reset();
    serialProtocolTick();
    peripheralsTick();
    delay(1);
}
