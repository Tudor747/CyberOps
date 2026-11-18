#include <Arduino.h>
#include <SPI.h>
#include <RF24.h>

// One NRF only: VCC 3.3V, GND, CE 16, CSN 4, SCK 18, MISO 19, MOSI 23.
RF24 radio(16, 4, 1000000);
bool ready = false;

// Independent register diagnostic: no RF24 calls, CE stays LOW.
// Software SPI uses mode 0, MSB first, deliberately slow GPIO toggling.
bool softwareSPI = false;
uint32_t diagnosticHz = 100000;
uint8_t transferByte(uint8_t out) {
    if (!softwareSPI) return SPI.transfer(out);
    uint8_t in = 0;
    for (int bit = 7; bit >= 0; --bit) {
        digitalWrite(23, (out >> bit) & 1);
        delayMicroseconds(10);
        digitalWrite(18, HIGH);
        delayMicroseconds(10);
        in = (in << 1) | digitalRead(19);
        digitalWrite(18, LOW);
    }
    return in;
}
uint8_t accessRegister(uint8_t reg, bool write = false, uint8_t value = 0) {
    if (!softwareSPI) SPI.beginTransaction(SPISettings(diagnosticHz, MSBFIRST, SPI_MODE0));
    digitalWrite(4, LOW); delayMicroseconds(10);
    transferByte((write ? 0x20 : 0x00) | reg);
    uint8_t result = transferByte(write ? value : 0xFF);
    digitalWrite(4, HIGH); delayMicroseconds(10);
    if (!softwareSPI) SPI.endTransaction();
    return result;
}
void probe(const char *label) {
    uint8_t config = accessRegister(0x00), aw = accessRegister(0x03);
    uint8_t status = accessRegister(0x07), old = accessRegister(0x05);
    accessRegister(0x05, true, 40); uint8_t a = accessRegister(0x05);
    accessRegister(0x05, true, 76); uint8_t b = accessRegister(0x05);
    accessRegister(0x05, true, old); uint8_t restored = accessRegister(0x05);
    Serial.printf("%s CONFIG=%02X AW=%02X STATUS=%02X CH=%02X | 40->%u 76->%u restore=%02X | %s\n",
        label, config, aw, status, old, a, b, restored,
        (aw >= 1 && aw <= 3 && a == 40 && b == 76 && restored == old) ? "PASS" : "FAIL");
}
void rawDiagnostics() {
    digitalWrite(16, LOW); digitalWrite(4, HIGH);
    softwareSPI = false; diagnosticHz = 100000; probe("DIRECT HW 100kHz");
    diagnosticHz = 1000000; probe("DIRECT HW 1MHz  ");
    SPI.end();
    pinMode(18, OUTPUT); digitalWrite(18, LOW);
    pinMode(23, OUTPUT); digitalWrite(23, LOW);
    pinMode(19, INPUT);
    softwareSPI = true; probe("DIRECT SOFTWARE");
    softwareSPI = false;
    SPI.begin(18, 19, 23, 4);
}

void testRadio() {
    ready = false;
    Serial.println("\n=== NRF DIAG v2: CE=16 CSN=4 SCK=18 MISO=19 MOSI=23 ===");
    Serial.printf("Build: %s %s; ESP=%s; rev=%u\n", __DATE__, __TIME__, ESP.getChipModel(), ESP.getChipRevision());
    rawDiagnostics();
    // Explicit bus pointer: RF24 does not call SPI.begin() in this overload.
    bool started = radio.begin(&SPI);
    Serial.printf("begin(): %s\n", started ? "OK" : "FAIL");
    if (!started) {
        Serial.println("RF24 begin FAIL. Compara rezultatele DIRECT de mai sus; cauza nu este stabilita. t = repeta.");
        return;
    }
    radio.stopListening();
    bool connected = radio.isChipConnected();
    Serial.printf("isChipConnected(): %s\n", connected ? "OK" : "FAIL");
    uint8_t original = radio.getChannel();
    radio.setChannel(40);
    uint8_t a = radio.getChannel();
    radio.setChannel(76);
    uint8_t b = radio.getChannel();
    radio.setChannel(original);
    Serial.printf("Registru canal: scris 40 / citit %u; scris 76 / citit %u\n", a, b);
    ready = connected && a == 40 && b == 76;
    if (!ready) {
        radio.powerDown();
        Serial.println("SPI FAIL: receptia nu poate fi testata. t = repeta.");
        return;
    }
    radio.setAutoAck(false);
    radio.disableCRC();
    radio.setDataRate(RF24_1MBPS);
    Serial.println("SPI PASS. Scanez receptia pe 2400..2479 MHz; fara transmisie.");
    Serial.println("Detectiile indica activitate, nu certifica antena. t = repeta testul SPI.");
}

void setup() {
    Serial.begin(115200);
    delay(1000);
    pinMode(16, OUTPUT); digitalWrite(16, LOW);
    pinMode(4, OUTPUT); digitalWrite(4, HIGH);
    SPI.begin(18, 19, 23, 4);
    testRadio();
}

void loop() {
    if (Serial.available() && Serial.read() == 't') testRadio();
    if (!ready) { delay(20); return; }
    uint16_t total = 0;
    uint8_t peak = 0, peakHits = 0;
    for (uint8_t ch = 0; ch < 80; ++ch) {
        uint8_t hits = 0;
        radio.setChannel(ch);
        for (uint8_t sample = 0; sample < 30; ++sample) {
            radio.startListening();
            delayMicroseconds(200);
            if (radio.testCarrier()) ++hits;
            radio.stopListening();
        }
        total += hits;
        if (hits > peakHits) { peak = ch; peakHits = hits; }
        delay(1);
    }
    if (!radio.isChipConnected() || radio.getChannel() != 79) {
        ready = false; radio.powerDown();
        Serial.println("SPI pierdut: rezultate eliminate. t = repeta.");
    } else if (total) {
        Serial.printf("RX: %u/2400 detectii; varf %u MHz (%u/30)\n", total, 2400 + peak, peakHits);
    } else {
        Serial.println("RX: 0/2400 detectii. SPI functioneaza; receptia RF nu este confirmata.");
    }
    delay(500);
}
