#include <Arduino.h>
#include <SPI.h>
#include <RF24.h>

// Standalone receive scanner, following the RadioScanner.cpp sampling approach.
RF24 radio1(5,17,1000000), radio2(16,4,1000000);
RF24* radios[]={&radio1,&radio2};
bool ready[2]={false,false}, scanning=true;
constexpr int channels=80, samples=30;
uint8_t hits[2][channels];
void initRadios(){
    for(int i=0;i<2;i++){
        auto &r=*radios[i];
        ready[i]=r.begin()&&r.isChipConnected();
        if(ready[i]){
            r.stopListening();r.setAutoAck(false);r.disableCRC();
            r.setDataRate(RF24_1MBPS);
            r.setChannel(40);bool a=r.getChannel()==40;
            r.setChannel(76);ready[i]=a&&r.getChannel()==76;
            r.powerDown();
        }
        Serial.printf("NRF%d CE=%d CS=%d: %s\n",i+1,i?16:5,i?4:17,ready[i]?"SPI OK":"FAIL SPI - scanare indisponibila");
    }
}
void setup(){
    Serial.begin(115200);delay(1000);
    // Other devices remain deselected on the shared bus.
    for(uint8_t pin:{27,17,4,25}){pinMode(pin,OUTPUT);digitalWrite(pin,HIGH);}
    for(uint8_t pin:{5,16,32}){pinMode(pin,OUTPUT);digitalWrite(pin,LOW);}
    SPI.begin(18,19,23);
    Serial.println("\nRADIO SCANNER - 2x NRF24 - pini conform cablajului tau");
    Serial.println("2400..2479 MHz; 30 probe/canal. Receptie, fara transmisie.");
    Serial.println("t=reinitializare; p=pauza; s=scanare. CC1101 nu este inclus in acest scanner NRF.");
    initRadios();
}
void loop(){
    if(Serial.available()){
        char c=Serial.read();
        if(c=='t')initRadios();
        if(c=='p'){scanning=false;Serial.println("PAUZA");}
        if(c=='s')scanning=true;
    }
    if(!scanning||(!ready[0]&&!ready[1])){delay(20);return;}
    memset(hits,0,sizeof(hits));
    for(int ch=0;ch<channels;ch++){
        for(int n=0;n<samples;n++){
            for(int i=0;i<2;i++)if(ready[i]){
                radios[i]->setChannel(ch);radios[i]->startListening();
            }
            delayMicroseconds(200);
            for(int i=0;i<2;i++)if(ready[i]){
                if(radios[i]->testCarrier())hits[i][ch]++;
                radios[i]->stopListening();
            }
        }
        delay(1);
    }
    Serial.println("\nSpectru: fiecare caracter = 1 MHz; . = 0 detectii, 1..9 = activitate crescatoare");
    for(int i=0;i<2;i++)if(ready[i]){
        radios[i]->powerDown();
        if(!radios[i]->isChipConnected()){
            ready[i]=false;Serial.printf("NRF%d: conexiune SPI pierduta; rezultate eliminate\n",i+1);continue;
        }
        int total=0,peak=0;
        Serial.printf("NRF%d 2400 |",i+1);
        for(int ch=0;ch<channels;ch++){
            total+=hits[i][ch];if(hits[i][ch]>hits[i][peak])peak=ch;
            Serial.print(hits[i][ch]?char('0'+(hits[i][ch]*8/samples+1)):'.');
        }
        Serial.println("| 2479 MHz");
        if(total)Serial.printf("  Detectii=%d/%d; varf=%d MHz (%d/%d probe)\n",total,channels*samples,2400+peak,hits[i][peak],samples);
        else Serial.println("  Fara activitate detectata in aceasta trecere; antena nu poate fi declarata defecta.");
    }
}
