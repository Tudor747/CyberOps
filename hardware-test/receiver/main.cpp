#include <Arduino.h>
#include <SPI.h>
#include <RF24.h>

// Single NRF24 receiver, adapted from the user's example.
RF24 radio(16, 4, 1000000);
const uint64_t pipeIn = 0xE9E8F0F0E1LL;
bool ready = false;
uint32_t lastStatus = 0, packets = 0;

void beginReceiver() {
    ready = false;
    Serial.println("\nNRF24 RECEPTOR UNIC: CE=16 CSN=4 SCK=18 MISO=19 MOSI=23");
    if (!radio.begin()) {
        Serial.println("FAIL: initializare SPI. Verifica firele/alimentarea; t = reincearca.");
        return;
    }
    radio.stopListening();
    radio.setChannel(40);
    uint8_t first = radio.getChannel();
    radio.setChannel(76);
    uint8_t second = radio.getChannel();
    Serial.printf("Canal: scris 40/citit %u; scris 76/citit %u\n", first, second);
    if (!radio.isChipConnected() || first != 40 || second != 76) {
        radio.powerDown();
        Serial.println("FAIL: verificare registre SPI. t = reincearca.");
        return;
    }
    radio.setDataRate(RF24_1MBPS);
    radio.setPALevel(RF24_PA_MIN);
    radio.setAddressWidth(5);
    radio.setCRCLength(RF24_CRC_16);
    radio.setAutoAck(true);
    radio.disableDynamicPayloads();
    radio.setPayloadSize(sizeof(uint16_t));
    radio.flush_rx();
    radio.openReadingPipe(1, pipeIn);
    radio.startListening();
    ready = true; packets = 0; lastStatus = millis();
    Serial.println("SPI PASS. Astept un emitator compatibil.");
    Serial.println("Adresa E9E8F0F0E1, canal 76, 1Mbps, CRC16, payload fix uint16_t (2 octeti).");
    Serial.println("Lipsa pachetelor NU inseamna modul defect. t = reinitializare.");
}

void setup() {
    Serial.begin(115200); delay(1000);
    pinMode(16, OUTPUT); digitalWrite(16, LOW);
    pinMode(4, OUTPUT); digitalWrite(4, HIGH);
    SPI.begin(18, 19, 23);
    beginReceiver();
}

void loop() {
    if (Serial.available() && Serial.read() == 't') beginReceiver();
    if (!ready) { delay(20); return; }
    // Bound reads so a disconnected bus cannot trap the program in this loop.
    for (uint8_t i = 0; i < 3 && radio.available(); ++i) {
        uint16_t value = 0;
        radio.read(&value, sizeof(value));
        if (!radio.isChipConnected() || radio.getChannel() != 76) {
            ready = false;
            Serial.println("FAIL: SPI pierdut; date ignorate. t = reinitializare.");
            return;
        }
        Serial.printf("RX: valoare=%u, pachet=%lu\n", value, (unsigned long)++packets);
    }
    if (millis() - lastStatus >= 5000) {
        lastStatus = millis();
        if (!radio.isChipConnected() || radio.getChannel() != 76) {
            ready = false;
            Serial.println("FAIL: SPI pierdut. t = reinitializare.");
        } else Serial.printf("Receptor activ; pachete primite=%lu.\n", (unsigned long)packets);
    }
    delay(1);
}
