#include <Arduino.h>
#include <SPI.h>
#include <RF24.h>
#include <MFRC522.h>
#include <IRrecv.h>
#include <IRsend.h>
#include <IRutils.h>

// Exact wiring supplied by the user. Blank connections are not used.
constexpr uint8_t CS[] = {27,17,4,25};
RF24 nrf1(5,17,1000000), nrf2(16,4,1000000);
MFRC522 rfid(25,26);
IRrecv ir(35,256,15,true);
IRsend emitter(32);
decode_results decoded;
bool rfidOK=false, waitingIR=false;
uint32_t irStart=0, lastReport=0;
volatile uint32_t radarEdges=0, ccEdges=0;
void IRAM_ATTR radarEdge(){++radarEdges;}
void IRAM_ATTR ccEdge(){++ccEdges;}
void releaseSPI(){for(auto pin:CS) digitalWrite(pin,HIGH);}

// Bounded access: an absent CC1101 cannot block the rest of the tests.
bool ccAccess(uint8_t address, uint8_t &value, bool write=false){
    releaseSPI();
    SPI.beginTransaction(SPISettings(1000000,MSBFIRST,SPI_MODE0));
    digitalWrite(27,LOW);
    uint32_t start=micros();
    while(digitalRead(19)){
        if(micros()-start>5000){digitalWrite(27,HIGH);SPI.endTransaction();return false;}
    }
    SPI.transfer(write?address:(address | (address>=0x30?0xC0:0x80)));
    uint8_t result=SPI.transfer(write?value:0);
    if(!write)value=result;
    digitalWrite(27,HIGH);SPI.endTransaction();return true;
}

void testNRF(RF24 &radio, const char *name){
    releaseSPI();
    bool found=radio.begin() && radio.isChipConnected();
    bool registers=false;
    if(found){
        radio.stopListening();radio.setAutoAck(false);
        uint8_t old=radio.getChannel();
        radio.setChannel(40);bool a=radio.getChannel()==40;
        radio.setChannel(76);registers=a && radio.getChannel()==76;
        radio.setChannel(old);radio.powerDown();
    }
    Serial.printf("%s: %s (SPI + scriere/citire registru; nu verifica antena/CE/link RF)\n",name,found&&registers?"PASS":"FAIL");
}

void tests(){
    Serial.println("\n=== TEST CABLAJ ESP32 DEV MODULE ===");
    Serial.println("SPI SCK=18 MISO=19 MOSI=23; CC CS=27 GDO0=13");
    Serial.println("NRF1 CE=5 CS=17; NRF2 CE=16 CS=4; RC522 SS=25 RST=26");
    Serial.println("IR RX=35 TX=32; radar OT1=SVP(GPIO36), RX=33");
    testNRF(nrf1,"NRF24 #1");testNRF(nrf2,"NRF24 #2");
    uint8_t part=255,version=255,old=0,a=0x12,b=0x24,readA=0,readB=0;
    bool detected=ccAccess(0x30,part)&&ccAccess(0x31,version)&&part==0&&version!=0&&version!=255;
    bool rw=false, restored=false;
    if(detected && ccAccess(0x0A,old)){
        rw=ccAccess(0x0A,a,true)&&ccAccess(0x0A,readA)&&readA==a&&
           ccAccess(0x0A,b,true)&&ccAccess(0x0A,readB)&&readB==b;
        restored=ccAccess(0x0A,old,true);
    }
    Serial.printf("CC1101: %s part=0x%02X version=0x%02X (SPI; nu verifica receptia RF/GDO0)\n",detected&&rw&&restored?"PASS":"FAIL",part,version);
    releaseSPI();rfid.PCD_Init();
    uint8_t v=rfid.PCD_ReadRegister(MFRC522::VersionReg);
    rfidOK=v!=0&&v!=255;
    Serial.printf("RC522: %s version=0x%02X; apropie un card pentru verificarea citirii\n",rfidOK?"RASPUNDE":"FAIL",v);
    Serial.println("IR RX: astept telecomanda. IR TX: comanda i trimite un cadru NEC de test.");
    Serial.println("Radar: observare OT1 pe SVP; activitatea nu confirma modelul/protocolul/prezenta.");
    Serial.println("W5500: NETESTAT, conectat la alt ESP32-C3, fara legatura specificata cu aceasta placa.");
    Serial.println("Comenzi: t = repeta SPI; i = test IR (indreapta KY-005 spre KY-022).");
}

void setup(){
    Serial.begin(115200);delay(1000);
    for(auto pin:CS){pinMode(pin,OUTPUT);digitalWrite(pin,HIGH);}
    pinMode(5,OUTPUT);digitalWrite(5,LOW);pinMode(16,OUTPUT);digitalWrite(16,LOW);
    pinMode(13,INPUT);pinMode(36,INPUT);
    // RX on the radar is connected to ESP GPIO33. Keep it idle, send no configuration.
    pinMode(33,OUTPUT);digitalWrite(33,HIGH);
    SPI.begin(18,19,23);emitter.begin();ir.enableIRIn();
    attachInterrupt(36,radarEdge,CHANGE);attachInterrupt(13,ccEdge,CHANGE);
    tests();
}

void loop(){
    if(Serial.available()){
        char c=Serial.read();
        if(c=='t'&&!waitingIR)tests();
        if(c=='i'&&!waitingIR){
            Serial.println("IR: emit NEC 0xF1A500FF; astept receptia 3 secunde...");
            ir.resume();waitingIR=true;irStart=millis();emitter.sendNEC(0xF1A500FF,32);
        }
    }
    if(ir.decode(&decoded)){
        Serial.printf("IR RX: protocol=%s bits=%u code=%s\n",typeToString(decoded.decode_type).c_str(),decoded.bits,uint64ToString(decoded.value,16).c_str());
        if(waitingIR&&decoded.decode_type==NEC&&decoded.bits==32&&decoded.value==0xF1A500FF){
            Serial.println("IR LOOPBACK: PASS (emitator + receptor)");waitingIR=false;
        }
        ir.resume();
    }
    if(waitingIR&&millis()-irStart>3000){
        Serial.println("IR LOOPBACK: NECONFIRMAT; verifica orientarea, distanta si conexiunile.");waitingIR=false;
    }
    if(rfidOK&&rfid.PICC_IsNewCardPresent()&&rfid.PICC_ReadCardSerial()){
        Serial.print("RFID READ: PASS UID=");
        for(uint8_t i=0;i<rfid.uid.size;i++)Serial.printf("%02X",rfid.uid.uidByte[i]);
        Serial.println();rfid.PICC_HaltA();rfid.PCD_StopCrypto1();
    }
    if(millis()-lastReport>=2000){
        lastReport=millis();
        Serial.printf("OT1/SVP: nivel=%d tranzitii=%lu; CC GDO0: nivel=%d tranzitii=%lu (total)\n",digitalRead(36),(unsigned long)radarEdges,digitalRead(13),(unsigned long)ccEdges);
    }
    delay(5);
}
