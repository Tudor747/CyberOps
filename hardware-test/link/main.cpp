#include <Arduino.h>
#include <SPI.h>
#include <RF24.h>

// Adapted from the supplied transmitter/receiver example.
// Two physical NRF24 modules on ONE ESP32, sharing SPI.
RF24 transmitter(5, 17, 1000000);
RF24 receiver(16, 4, 1000000);
const uint64_t pipeAddress = 0xE9E8F0F0E1LL;
bool ready = false;
uint16_t value = 35;
uint32_t lastSend = 0, sent = 0, received = 0, acknowledged = 0;

void configure(RF24 &radio) {
    radio.stopListening();
    radio.setChannel(76);
    radio.setDataRate(RF24_1MBPS);
    radio.setPALevel(RF24_PA_MIN);
    radio.setAddressWidth(5);
    radio.setCRCLength(RF24_CRC_16);
    radio.setAutoAck(true);
    radio.setRetries(5, 5);
    radio.disableDynamicPayloads();
    radio.setPayloadSize(sizeof(uint16_t));
    radio.flush_rx();
    radio.flush_tx();
}

void beginTest() {
    ready = false;
    bool tx = transmitter.begin();
    bool rx = receiver.begin();
    Serial.printf("NRF1 TX (CE5 CS17): %s\n", tx ? "INIT OK" : "FAIL");
    Serial.printf("NRF2 RX (CE16 CS4): %s\n", rx ? "INIT OK" : "FAIL");
    if (!tx || !rx) {
        if (tx) transmitter.powerDown();
        if (rx) receiver.powerDown();
        Serial.println("Test oprit: sunt necesare doua module care raspund prin SPI. t = reincearca.");
        return;
    }
    configure(transmitter); configure(receiver);
    ready = transmitter.isChipConnected() && receiver.isChipConnected() &&
            transmitter.getChannel() == 76 && receiver.getChannel() == 76;
    if (!ready) {
        transmitter.powerDown(); receiver.powerDown();
        Serial.println("FAIL: verificarea registrelor SPI. t = reincearca.");
        return;
    }
    transmitter.openWritingPipe(pipeAddress);
    receiver.openReadingPipe(1, pipeAddress);
    receiver.startListening();
    transmitter.stopListening();
    sent = received = acknowledged = 0; value = 35;
    Serial.println("LINK TEST: canal 76, 1Mbps, PA_MIN, un pachet/secunda. t = reinitializare.");
}

void setup() {
    Serial.begin(115200); delay(1000);
    for (uint8_t pin : {27, 17, 4, 25}) {pinMode(pin, OUTPUT); digitalWrite(pin, HIGH);}
    for (uint8_t pin : {5, 16}) {pinMode(pin, OUTPUT); digitalWrite(pin, LOW);}
    SPI.begin(18, 19, 23);
    beginTest();
}

void loop() {
    if (Serial.available() && Serial.read() == 't') beginTest();
    if (!ready || millis() - lastSend < 1000) {delay(1); return;}
    lastSend = millis();
    // Clear old data so PASS can only refer to this transmission.
    receiver.flush_rx();
    bool ack = transmitter.write(&value, sizeof(value));
    ++sent; if (ack) ++acknowledged;
    uint32_t start = millis();
    bool match = false;
    while (millis() - start < 100) {
        while (receiver.available()) {
            uint16_t actual = 0;
            receiver.read(&actual, sizeof(actual));
            if (actual == value) match = true;
            Serial.printf("RX valoare=%u (asteptat=%u)\n", actual, value);
        }
        if (match) break;
        delay(1);
    }
    if (match) ++received;
    Serial.printf("TX=%u ACK=%s RX=%s | primite=%lu/%lu ACK=%lu\n", value,
                  ack ? "DA" : "NU", match ? "PASS" : "LIPSA",
                  (unsigned long)received, (unsigned long)sent, (unsigned long)acknowledged);
    if (++value > 180) value = 35;
}
