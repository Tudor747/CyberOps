#include <Arduino.h>
#include <SPI.h>
#include <RF24.h>
#include <MFRC522.h>
#include <IRrecv.h>
#include <IRsend.h>
#include <IRutils.h>
#include <ELECHOUSE_CC1101_SRC_DRV.h>
#include "Pins.h"
#include "Peripherals.h"

// Carrier-detection approach adapted from Cyberdeck Mini's RadioScanner.cpp.
// No local display, deauthentication, replay or RF transmit operations.
static RF24 radio1(Pins::NRF1_CE,Pins::NRF1_CS,1000000);
static RF24 radio2(Pins::NRF2_CE,Pins::NRF2_CS,1000000);
static MFRC522 rfid(Pins::RFID_CS,Pins::RFID_RST);
static IRrecv ir(Pins::IR_RX,256,15,true);
static decode_results irResult;
static HardwareSerial radar(2);
static bool radios[2]={false,false}, ccReady=false, rfidReady=false, ethReady=false;
static bool stopped=true, radarKnown=false, radarPresence=false;
static unsigned long heartbeat=0, radarAt=0, irAt=0, rfidAt=0, sampleAt=0;
static String lastRfid, lastIr;
static uint8_t counts[81]={0}, bins[81]={0}, channel=0, rounds=0;
static bool binsReady=false;
static IRsend irEmitter(Pins::IR_TX);
static JsonDocument diagnostic;
static bool testSession=false, ccTestConfigured=false;
static unsigned long testStarted=0, testDuration=0, testSampleAt=0, testRadarAt=0;
static uint32_t testSamples=0, testHits=0;
static uint8_t testAddress=4;
static String testComponent;
static volatile uint32_t pulseLast=0;
static volatile uint16_t pulseCount=0;
static volatile uint32_t pulseTimes[256];
static volatile bool pulseOverflow=false;
static portMUX_TYPE pulseMux=portMUX_INITIALIZER_UNLOCKED;
static bool pulseAttached=false;
static constexpr uint32_t IR_TEST_CODE=0xF1A500FF;
static void diagnosticTick();
static void diagnosticCleanup();
static bool testRunning() {return testSession && diagnostic["state"]=="RUNNING";}
static void finishTest(const char* state,const char* code,const char* message) {
    diagnostic["state"]=state;diagnostic["code"]=code;diagnostic["message"]=message;
    diagnostic["elapsed_ms"]=millis()-testStarted;
    if(pulseAttached) {detachInterrupt(Pins::CC_GDO0);pulseAttached=false;}
}

static void releaseBus() {
    for (auto pin:Pins::CHIP_SELECTS) digitalWrite(pin,HIGH);
}

static uint8_t registerRead(uint8_t cs,uint16_t address,bool ethernet) {
    releaseBus();
    SPI.beginTransaction(SPISettings(1000000,MSBFIRST,SPI_MODE0));
    digitalWrite(cs,LOW);
    if (ethernet) {
        SPI.transfer(address>>8);SPI.transfer(address&0xff);SPI.transfer(0x00);
    } else SPI.transfer((address&0x3f)|0xc0);
    uint8_t value=SPI.transfer(0);
    digitalWrite(cs,HIGH);
    SPI.endTransaction();
    return value;
}

void peripheralsStop() {
    if(testRunning())finishTest("CANCELLED","CANCELLED","Test stopped");
    diagnosticCleanup();
    stopped=true;
    digitalWrite(Pins::NRF1_CE,LOW);digitalWrite(Pins::NRF2_CE,LOW);
    if (radios[0]) {radio1.stopListening();radio1.powerDown();}
    if (radios[1]) {radio2.stopListening();radio2.powerDown();}
    if (rfidReady) rfid.PCD_AntennaOff();
    if (ccReady) ELECHOUSE_cc1101.setSidle();
    ir.disableIRIn();
    digitalWrite(Pins::IR_TX,LOW);
    memset(counts,0,sizeof(counts));memset(bins,0,sizeof(bins));
    binsReady=false;channel=0;rounds=0;
    releaseBus();
}

void peripheralsBegin() {
    for (auto pin:Pins::CHIP_SELECTS) {pinMode(pin,OUTPUT);digitalWrite(pin,HIGH);}
    pinMode(Pins::NRF1_CE,OUTPUT);pinMode(Pins::NRF2_CE,OUTPUT);
    digitalWrite(Pins::NRF1_CE,LOW);digitalWrite(Pins::NRF2_CE,LOW);
    pinMode(Pins::IR_TX,OUTPUT);digitalWrite(Pins::IR_TX,LOW);
    pinMode(Pins::IR_RX,INPUT);pinMode(Pins::CC_GDO0,INPUT);pinMode(Pins::CC_GDO2,INPUT);
    SPI.begin(Pins::SCK,Pins::MISO,Pins::MOSI);
    radios[0]=radio1.begin();radios[1]=radio2.begin();
    RF24* all[]={&radio1,&radio2};
    for (int i=0;i<2;i++) if(radios[i]) {
        all[i]->setAutoAck(false);all[i]->disableCRC();
        all[i]->setDataRate(RF24_1MBPS);all[i]->powerDown();
    }
    releaseBus();
    // Probe before invoking a driver that waits for the CC1101 ready signal.
    uint8_t version=registerRead(Pins::CC_CS,0x31,false);
    ccReady=version!=0 && version!=0xff;
    if (ccReady) {
        ELECHOUSE_cc1101.setSpiPin(Pins::SCK,Pins::MISO,Pins::MOSI,Pins::CC_CS);
        ELECHOUSE_cc1101.Init();
        ELECHOUSE_cc1101.setMHZ(433.92);
        ELECHOUSE_cc1101.setSidle();
    }
    releaseBus();rfid.PCD_Init();
    uint8_t rfidVersion=rfid.PCD_ReadRegister(MFRC522::VersionReg);
    rfidReady=rfidVersion!=0 && rfidVersion!=0xff;
    if(rfidReady)rfid.PCD_AntennaOff();
    ethReady=registerRead(Pins::ETH_CS,0x0039,true)==4;
    // Basic-status text mode: ON/OFF and Range. Older firmware may use 256000.
    radar.begin(RADAR_BAUD,SERIAL_8N1,Pins::RADAR_RX,Pins::RADAR_TX);
    peripheralsStop();
}

static void readRadar() {
    static char line[64];static uint8_t used=0;static bool discard=false;
    int budget=128;
    while (radar.available() && budget--) {
        char c=radar.read();
        if(c=='\r')continue;
        if(c=='\n') {
            line[used]=0;
            if(!discard && (!strcmp(line,"ON") || !strcmp(line,"OFF"))) {
                radarPresence=!strcmp(line,"ON");radarKnown=true;radarAt=millis();
            }
            used=0;discard=false;
        } else if(c>=32 && c<=126 && used<sizeof(line)-1 && !discard) line[used++]=c;
        else discard=true;
    }
}

void peripheralsTick() {
    readRadar();
    if(testSession) {
        if(millis()-heartbeat>3500)peripheralsStop();
        else if(testRunning())diagnosticTick();
        return;
    }
    if(stopped)return;
    if(millis()-heartbeat>3500) {peripheralsStop();return;}
    // One bounded channel sample per iteration keeps STOP responsive.
    RF24* selected=(channel%2 && radios[1])?&radio2:&radio1;
    bool available=(selected==&radio1)?radios[0]:radios[1];
    if(!available && radios[1]) {selected=&radio2;available=true;}
    if(available) {
        releaseBus();selected->setChannel(channel);selected->startListening();
        delayMicroseconds(150);
        if(selected->testRPD())counts[channel]++;
        selected->stopListening();
    }
    if(++channel>=81) {
        channel=0;
        if(++rounds>=8) {memcpy(bins,counts,sizeof(bins));memset(counts,0,sizeof(counts));rounds=0;binsReady=available;}
    }
    if(ir.decode(&irResult)) {lastIr=resultToHexidecimal(&irResult);irAt=millis();ir.resume();}
    if(millis()-sampleAt>=100) {
        sampleAt=millis();
        if(rfidReady && rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
            char value[3];lastRfid="0x";
            for(byte i=0;i<rfid.uid.size;i++) {snprintf(value,sizeof(value),"%02X",rfid.uid.uidByte[i]);lastRfid+=value;}
            rfidAt=millis();rfid.PICC_HaltA();rfid.PCD_StopCrypto1();
        }
    }
}

void peripheralsPoll(JsonDocument& response) {
    heartbeat=millis();
    if(testSession) {response["status"]="STOPPED";return;}
    if(stopped) {
        if(radios[0])radio1.powerUp();if(radios[1])radio2.powerUp();
        if(ccReady)ELECHOUSE_cc1101.SetRx();
        if(rfidReady)rfid.PCD_AntennaOn();
        ir.enableIRIn();stopped=false;
    }
    response["status"]="OK";
    response["uptime_ms"]=millis();
    response["radar_presence"]=nullptr;
    if(radarKnown && millis()-radarAt<5000)response["radar_presence"]=radarPresence;
    response["last_rfid"]=nullptr;
    if(lastRfid.length()) {response["last_rfid"]=lastRfid;response["rfid_age_ms"]=millis()-rfidAt;}
    response["ir_activity"]=lastIr.length()>0 && millis()-irAt<1500;
    response["ir_last_code"]=nullptr;
    if(lastIr.length())response["ir_last_code"]=lastIr;
    response["rf_subghz_rssi"]=nullptr;
    if(ccReady)response["rf_subghz_rssi"]=ELECHOUSE_cc1101.getRssi();
    response["nrf24_status"]=(radios[0]&&radios[1])?"DUAL RX":(radios[0]||radios[1])?"SINGLE RX":"NOT FOUND";
    response["rf_bins"]=nullptr;
    if(binsReady) {JsonArray output=response["rf_bins"].to<JsonArray>();for(auto value:bins)output.add(value);}
    response["rfid_status"]=rfidReady?"READY":"NOT FOUND";
    response["ethernet_status"]=!ethReady?"NOT FOUND":(registerRead(Pins::ETH_CS,0x002e,true)&1)?"LINK UP":"LINK DOWN";
}

static void IRAM_ATTR capturePulse() {
    uint32_t now=micros();
    portENTER_CRITICAL_ISR(&pulseMux);
    uint32_t elapsed=now-pulseLast;pulseLast=now;
    if(elapsed>12000 && pulseCount<16) {pulseCount=0;pulseOverflow=false;}
    else if(elapsed>=60) {
        if(pulseCount<256)pulseTimes[pulseCount++]=elapsed;
        else pulseOverflow=true;
    }
    portEXIT_CRITICAL_ISR(&pulseMux);
}

static void diagnosticCleanup() {
    if(pulseAttached) {detachInterrupt(Pins::CC_GDO0);pulseAttached=false;}
    if(ccTestConfigured && ccReady) {
        // Restore the normal monitor profile after any outcome, including STOP.
        ELECHOUSE_cc1101.Init();ELECHOUSE_cc1101.setMHZ(433.92);ELECHOUSE_cc1101.setSidle();
    }
    ccTestConfigured=false;testSession=false;
}

static void readTestTag() {
    byte atqa[2],atqaSize=2;
    auto wake=rfid.PICC_WakeupA(atqa,&atqaSize);
    if(wake!=MFRC522::STATUS_OK && wake!=MFRC522::STATUS_COLLISION)return;
    if(!rfid.PICC_ReadCardSerial()) {
        diagnostic["code"]="TAG_SELECT_RETRY";diagnostic["message"]="Tag detected; hold one tag steady";return;
    }
    JsonObject m=diagnostic["measurements"].as<JsonObject>();
    char part[3];String uid;
    for(byte i=0;i<rfid.uid.size;i++) {snprintf(part,sizeof(part),"%02X",rfid.uid.uidByte[i]);uid+=part;}
    auto type=MFRC522::PICC_GetType(rfid.uid.sak);
    m["uid"]=uid;m["tag_type"]=String(MFRC522::PICC_GetTypeName(type));m["sak"]=rfid.uid.sak;
    m["read_address"]=testAddress;m["atqa"]=uint16_t(atqa[0])|(uint16_t(atqa[1])<<8);
    lastRfid="0x"+uid;rfidAt=millis();
    bool classic=type==MFRC522::PICC_TYPE_MIFARE_MINI || type==MFRC522::PICC_TYPE_MIFARE_1K || type==MFRC522::PICC_TYPE_MIFARE_4K;
    auto status=MFRC522::STATUS_OK;
    if(classic) {
        uint16_t blocks=type==MFRC522::PICC_TYPE_MIFARE_MINI?20:type==MFRC522::PICC_TYPE_MIFARE_1K?64:256;
        if(testAddress>=blocks) {
            finishTest("PARTIAL","ADDRESS_OUT_OF_RANGE","UID read; selected block is outside this tag");
            rfid.PICC_HaltA();return;
        }
        MFRC522::MIFARE_Key key;memset(key.keyByte,0xff,6);
        m["access_method"]="MIFARE Classic factory Key A (FFFFFFFFFFFF)";
        status=rfid.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A,testAddress,&key,&rfid.uid);
        if(status!=MFRC522::STATUS_OK) {
            m["reader_error"]=String(MFRC522::GetStatusCodeName(status));
            finishTest("PARTIAL","AUTH_FAILED","UID read; memory needs a matching key or a steadier tag");
            rfid.PICC_HaltA();rfid.PCD_StopCrypto1();return;
        }
    } else if(type!=MFRC522::PICC_TYPE_MIFARE_UL) {
        finishTest("PARTIAL","UNSUPPORTED_MEMORY","UID read; this tag's memory protocol is not supported");
        rfid.PICC_HaltA();return;
    } else m["access_method"]="Unprotected Ultralight / NTAG READ (four pages)";
    byte buffer[18],size=sizeof(buffer);
    status=rfid.MIFARE_Read(testAddress,buffer,&size);
    if(status==MFRC522::STATUS_OK && size>=16) {
        String hex,ascii;
        for(int i=0;i<16;i++) {
            snprintf(part,sizeof(part),"%02X",buffer[i]);if(i)hex+=' ';hex+=part;
            ascii+=(buffer[i]>=32 && buffer[i]<=126)?char(buffer[i]):'.';
        }
        m["memory_hex"]=hex;m["memory_ascii"]=ascii;m["bytes_read"]=16;
        finishTest("PASS","TAG_READ","UID, type and 16 memory bytes read successfully");
    } else {
        m["reader_error"]=String(MFRC522::GetStatusCodeName(status));
        finishTest("PARTIAL","MEMORY_READ_FAILED","UID read; memory may be protected, out of range or unreadable");
    }
    rfid.PICC_HaltA();rfid.PCD_StopCrypto1();
}

static void diagnosticTick() {
    unsigned long elapsed=millis()-testStarted;
    diagnostic["elapsed_ms"]=elapsed;
    JsonObject m=diagnostic["measurements"].as<JsonObject>();
    if(testComponent=="nrf1" || testComponent=="nrf2") {
        RF24& radio=testComponent=="nrf1"?radio1:radio2;
        radio.setChannel(testSamples%81);radio.startListening();delayMicroseconds(150);
        if(radio.testRPD())testHits++;radio.stopListening();testSamples++;
        m["samples"]=testSamples;m["carrier_hits"]=testHits;
    } else if(testComponent=="rfid" && millis()-testSampleAt>=100) {
        testSampleAt=millis();readTestTag();
    } else if(testComponent=="cc1101" && millis()-testSampleAt>=20) {
        testSampleAt=millis();int rssi=ELECHOUSE_cc1101.getRssi();
        m["rssi_dbm"]=rssi;
        if(rssi>(m["peak_rssi_dbm"] | -160))m["peak_rssi_dbm"]=rssi;
        if(rssi>-75)testHits++;
        uint16_t count;bool overflow;uint32_t last;
        portENTER_CRITICAL(&pulseMux);count=pulseCount;overflow=pulseOverflow;last=pulseLast;portEXIT_CRITICAL(&pulseMux);
        m["edge_count"]=count;m["above_threshold_samples"]=testHits;
        if(count>=16 && (micros()-last>12000 || overflow)) {
            detachInterrupt(Pins::CC_GDO0);pulseAttached=false;
            JsonArray raw=m["pulse_us"].to<JsonArray>();
            for(uint16_t i=0;i<count;i++)raw.add(uint32_t(pulseTimes[i]));
            m["capture_truncated"]=overflow;m["protocol"]="UNKNOWN";
            finishTest("PARTIAL","RAW_CAPTURE","Raw signal edges captured; protocol and device identity are unverified");
        }
    } else if(testComponent=="ir_rx" || testComponent=="ir_tx") {
        if(ir.decode(&irResult)) {
            bool expected=irResult.decode_type==NEC && irResult.value==IR_TEST_CODE && irResult.bits==32;
            m["protocol"]=typeToString(irResult.decode_type);m["code"]=resultToHexidecimal(&irResult);
            m["bits"]=irResult.bits;m["overflow"]=irResult.overflow;
            JsonArray raw=m["pulse_us"].to<JsonArray>();
            for(uint16_t i=1;i<irResult.rawlen && i<=128;i++)raw.add(uint32_t(irResult.rawbuf[i])*kRawTick);
            m["capture_truncated"]=irResult.rawlen>129;
            lastIr=resultToHexidecimal(&irResult);irAt=millis();
            if(testComponent=="ir_tx") {
                if(expected)finishTest("PASS","IR_LOOPBACK_OK","The receiver observed the emitted NEC test code");
                else {diagnostic["code"]="OTHER_IR_SIGNAL";diagnostic["message"]="Different IR signal received; waiting for the loopback code";}
            } else if(irResult.decode_type==UNKNOWN)finishTest("PARTIAL","IR_RAW_ONLY","IR pulses captured; protocol not recognized");
            else finishTest("PASS","IR_DECODED","IR protocol and code received");
            ir.resume();
        }
    } else if(testComponent=="radar" && radarAt!=testRadarAt) {
        m["presence"]=radarPresence;m["uart_baud"]=RADAR_BAUD;
        finishTest("PASS","RADAR_REPORT","Fresh basic-status UART report received; check presence against the room");
    } else if(testComponent=="ethernet") {
        uint8_t phy=registerRead(Pins::ETH_CS,0x002e,true);m["phy_register"]=phy;
        if(phy&1) {m["speed_mbps"]=(phy&2)?100:10;m["full_duplex"]=bool(phy&4);
            finishTest("PASS","ETHERNET_LINK_UP","W5500 responds and the physical cable link is up");}
    }
    if(testRunning() && elapsed>=testDuration) {
        if(testComponent=="nrf1" || testComponent=="nrf2")
            finishTest("PASS","NRF_SPI_OK",testHits?"Radio responds; carrier activity observed":"Radio responds; no carrier detected during this test");
        else if(testComponent=="cc1101" && testHits)
            finishTest("PARTIAL","RF_ENERGY_ONLY","RF energy observed; no complete pulse capture or known protocol");
        else if(testComponent=="ir_tx")finishTest("NO_SIGNAL","IR_TX_UNVERIFIED","Test frame sent, but no matching optical loopback was received; check emitter, receiver and alignment");
        else if(testComponent=="ethernet")finishTest("NO_SIGNAL","ETHERNET_LINK_DOWN","W5500 responds but no cable link; check cable, switch port and power");
        else if(testComponent=="rfid")finishTest("NO_SIGNAL","NO_TAG","No compatible tag read; use one ISO14443A tag close to the RC522");
        else if(testComponent=="radar")finishTest("NO_SIGNAL","NO_RADAR_REPORT","No fresh ON/OFF report; check UART wiring, baud and basic-status mode");
        else finishTest("NO_SIGNAL","NO_SIGNAL","No usable signal captured; check source, wiring and selected receive profile");
    }
}

void peripheralsTestCommand(const JsonDocument& command, JsonDocument& response) {
    const char* cmd=command["cmd"] | "";
    const char* id=command["test_id"] | "";
    if(!strcmp(cmd,"TEST_CANCEL")) {
        if(testSession && diagnostic["test_id"]!=id) {response["status"]="ERROR";response["message"]="Test identity mismatch";return;}
        peripheralsStop();response["status"]="STOPPED";return;
    }
    if(!strcmp(cmd,"TEST_STATUS")) {
        if(!testSession || diagnostic["test_id"]!=id) {response["status"]="ERROR";response["message"]="Test session lost or firmware restarted";return;}
        heartbeat=millis();response["status"]="DIAGNOSTIC";response["test"]=diagnostic;return;
    }
    const char* component=command["component"] | "";
    bool valid=false;
    for(const char* name:{"nrf1","nrf2","rfid","cc1101","ir_rx","ir_tx","radar","ethernet"})if(!strcmp(name,component))valid=true;
    int duration=command["duration_s"] | 15;int address=command["address"] | 4;
    float frequency=command["frequency_mhz"] | 433.92f;
    String modulation=command["modulation"] | "OOK";
    if(!valid || strlen(id)!=32 || duration<3 || duration>30 || address<0 || address>255 || !isfinite(frequency) || frequency<433.05 || frequency>434.79 ||
       (modulation!="OOK" && modulation!="2FSK" && modulation!="GFSK")) {
        response["status"]="ERROR";response["message"]="Invalid hardware test parameters";return;
    }
    if(testSession) {response["status"]="ERROR";response["message"]="A hardware test is already active";return;}
    peripheralsStop();diagnostic.clear();testSession=true;testComponent=component;
    testStarted=millis();heartbeat=testStarted;testDuration=duration*1000;testAddress=address;
    testSampleAt=0;testSamples=0;testHits=0;testRadarAt=radarAt;
    diagnostic["test_id"]=id;diagnostic["component"]=component;diagnostic["state"]="RUNNING";
    diagnostic["code"]="WAITING";diagnostic["message"]="Waiting for a fresh measurement";
    diagnostic["elapsed_ms"]=0;diagnostic["duration_ms"]=testDuration;
    JsonObject m=diagnostic["measurements"].to<JsonObject>();
    if(testComponent=="nrf1" || testComponent=="nrf2") {
        int index=testComponent=="nrf1"?0:1;RF24& radio=index?radio2:radio1;
        radios[index]=radio.begin() && radio.isChipConnected();m["spi_connected"]=radios[index];
        if(!radios[index])finishTest("FAIL","NRF_NOT_FOUND","No nRF24 response; check 3.3V, CE, CSN and shared SPI");
        else {radio.setAutoAck(false);radio.disableCRC();radio.setDataRate(RF24_1MBPS);radio.powerUp();}
    } else if(testComponent=="rfid") {
        rfid.PCD_Init();uint8_t version=rfid.PCD_ReadRegister(MFRC522::VersionReg);m["reader_version"]=version;
        rfidReady=version!=0 && version!=0xff;
        if(!rfidReady)finishTest("FAIL","RFID_NOT_FOUND","No RC522 response; check 3.3V, CS, RST and SPI");
        else rfid.PCD_AntennaOn();
    } else if(testComponent=="cc1101") {
        uint8_t version=registerRead(Pins::CC_CS,0x31,false);ccReady=version!=0 && version!=0xff;m["chip_version"]=version;
        if(!ccReady)finishTest("FAIL","CC1101_NOT_FOUND","No CC1101 response; check 3.3V, CS and SPI");
        else {
            ELECHOUSE_cc1101.setSpiPin(Pins::SCK,Pins::MISO,Pins::MOSI,Pins::CC_CS);
            ELECHOUSE_cc1101.Init();ccTestConfigured=true;
            ELECHOUSE_cc1101.setCCMode(false);ELECHOUSE_cc1101.setModulation(modulation=="OOK"?2:modulation=="GFSK"?1:0);
            ELECHOUSE_cc1101.setMHZ(frequency);ELECHOUSE_cc1101.setRxBW(270.83);ELECHOUSE_cc1101.setDRate(4.8);
            ELECHOUSE_cc1101.setPktFormat(3);ELECHOUSE_cc1101.SpiWriteReg(0x02,0x0D);ELECHOUSE_cc1101.SetRx();
            m["frequency_mhz"]=frequency;m["modulation"]=modulation;m["bandwidth_khz"]=270.83;
            m["data_rate_kbaud"]=4.8;m["protocol"]="UNKNOWN";m["peak_rssi_dbm"]=-160;
            portENTER_CRITICAL(&pulseMux);pulseCount=0;pulseLast=micros();pulseOverflow=false;portEXIT_CRITICAL(&pulseMux);
            attachInterrupt(Pins::CC_GDO0,capturePulse,CHANGE);pulseAttached=true;
        }
    } else if(testComponent=="ir_rx" || testComponent=="ir_tx") {
        ir.enableIRIn();ir.resume();
        if(testComponent=="ir_tx") {
            irEmitter.begin();irEmitter.sendNEC(IR_TEST_CODE,32,0);
            m["emitted_code"]="0xF1A500FF";m["carrier_khz"]=38;
            diagnostic["message"]="Point KY-005 at KY-022; waiting for matching NEC loopback";
        }
    } else if(testComponent=="ethernet") {
        uint8_t version=registerRead(Pins::ETH_CS,0x0039,true);ethReady=version==4;m["chip_version"]=version;
        if(!ethReady)finishTest("FAIL","W5500_NOT_FOUND","No W5500 response; check power, CS and SPI");
    } else if(testComponent=="radar") {
        m["uart_baud"]=RADAR_BAUD;m["rx_gpio"]=Pins::RADAR_RX;
    }
    response["status"]="DIAGNOSTIC";response["test"]=diagnostic;
}
