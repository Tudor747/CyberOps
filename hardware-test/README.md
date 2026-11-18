# Diagnostic pentru cablajul furnizat

## Receptor cu un singur NRF (exemplul utilizatorului adaptat)

Cod: `receiver/main.cpp`. Conecteaza numai un NRF: CE16, CSN4, SCK18, MISO19, MOSI23, VCC3.3V, GND comun, IRQ liber. Modifica firele cu USB scos.

```powershell
.\run.ps1 -ReceiverOnly -Port COM5
```

Inlocuieste COM5 cu portul placii. Incarcarea inlocuieste firmware-ul curent. Nu foloseste servo sau potentiometru. Verifica SPI, apoi afiseaza fiecare valoare primita si un status la 5 secunde; `t` reinitializeaza. Fara emitator, zero pachete este normal si nu certifica antena. Receptorul trimite confirmari automate pentru pachetele adresate lui.

Emitatorul trebuie sa foloseasca exact adresa `0xE9E8F0F0E1`, canal 76, 1Mbps, adresa pe 5 octeti, CRC16 si payload fix de 2 octeti (`uint16_t`). Este compatibil cu modul TX din `link/main.cpp`. Exemplul original nemodificat poate avea alte setari implicite si alt payload; seteaza explicit acesti parametri pe emitator.

## Test TX/RX bazat pe exemplul furnizat

`link/main.cpp` adapteaza exemplul cu adresa `0xE9E8F0F0E1` pentru DOUA NRF24 pe ACELASI ESP32. NRF1 transmite (CE5, CS17), NRF2 receptioneaza (CE16, CS4). Ambele folosesc SCK18, MISO19, MOSI23, 3.3V si GND comun. Conecteaza modulele cu USB scos. Pastreaza condensatoarele si antenele montate. Celelalte module nu sunt necesare.

```powershell
.\run.ps1 -LinkTest -Port COM5
```

Acest mod inlocuieste firmware-ul curent. Trimite o valoare 35..180 pe secunda, fara servo sau potentiometru. Foloseste payload explicit uint16_t, Serial.begin(115200), canal 76, CRC16, auto-ack si putere PA_MIN. `RX=PASS` necesita citirea aceleiasi valori pe al doilea modul; `ACK=DA` arata si confirmarea radio. Un test local reusit confirma legatura in conditiile testului, nu castigul/adaptarea antenelor. FAIL la initializare impiedica testul. Un singur modul nu poate executa acest test de legatura. `t` reinitializeaza.

## Un singur NRF conectat direct

Versiunea `NRF DIAG v2` din `-SingleNrf` verifica registrele independent de RF24: SPI hardware la 100kHz si 1MHz, apoi SPI software lent pe aceiasi pini. In fiecare caz scrie/citeste canalul 40 si 76, apoi restaureaza valoarea originala; CE ramane LOW. Apoi initializeaza RF24 cu magistrala explicita `radio.begin(&SPI)`. Raportul include data compilarii pentru identificarea firmware-ului incarcat. Testul cere un singur modul conectat.

Interpretare: DIRECT PASS cu RF24 FAIL indica o diferenta intre accesul simplu si initializarea bibliotecii, nu dovedeste singur cauza. Software PASS cu hardware FAIL directioneaza investigatia spre configuratia/timingul SPI hardware. Esecul tuturor cailor nu identifica automat cablajul ca vinovat: alimentarea, modulul, placa si configuratia raman de verificat. Trimite cele trei randuri DIRECT si rezultatul begin().

Cu USB scos, deconecteaza celelalte module. Leaga doar NRF: VCC la 3.3V, GND la GND, CE la GPIO16, CSN la GPIO4, SCK la GPIO18, MISO la GPIO19, MOSI la GPIO23. IRQ ramane liber. Pastreaza condensatoarele indicate in cablaj intre 3.3V si GND langa NRF (respecta polaritatea celui de 100uF). Foloseste marcajele pinilor, nu pozitia presupusa dintr-o fotografie. VCC al NRF se leaga la 3.3V, nu la 5V.

```powershell
.\run.ps1 -SingleNrf -Port COM5
```

Cod: `single-nrf/main.cpp`. Inlocuieste COM5 cu portul placii. Incarcarea inlocuieste firmware-ul curent. Monitor: 115200 baud; EN/RESET reia raportul initial. `t` repeta initializarea. Programul afiseaza separat rezultatul initializarii, identificarea si valorile citite dupa scrierea canalelor 40 si 76. Dupa SPI PASS scaneaza activitatea de receptie. Cu un singur modul nu verifica transmisia sau un link intre doua radiouri. Nu poate certifica antena sau alimentarea sub sarcina.

## Scanner radio similar Cyberdeck Mini

Pentru cele doua NRF24, foloseste:

```powershell
.\run.ps1 -RadioOnly -Port COM5
```

Inlocuieste COM5 cu portul placii. Acest mod incarca scannerul in locul diagnosticului general. Foloseste aceeasi idee de detectie `testCarrier()` ca `CYBERDECK-MINI-ESP32-V2/src/RadioScanner.cpp`, cu 80 de canale si 30 de probe per canal. Aici fiecare NRF scaneaza intreaga banda separat, pentru comparatie, cu o noua fereastra de receptie la fiecare proba. Afiseaza doua randuri de spectru in monitorul serial; nu necesita ecran.

Comenzi: `p` pauza, `s` reia, `t` reinitializeaza radiourile. Pentru verificare, observa schimbarile cand exista trafic pe propria retea de 2.4 GHz. Punctele inseamna lipsa detectiilor, cifrele 1..9 indica activitate crescatoare. Valorile nu sunt dBm, numar de pachete sau masuratori ale castigului antenei. Absenta activitatii nu dovedeste ca antena este defecta. Acest test nu masoara adaptarea antenei/SWR.

Scannerul foloseste NRF1 CE=5 CS=17, NRF2 CE=16 CS=4 si SPI 18/19/23. CC1101 si RC522 sunt deselectate; radarul si IR nu sunt testate. Nu transmite pachete si dezactiveaza auto-ack. Daca un NRF raporteaza FAIL SPI, scannerul nu poate folosi acel modul; trebuie rezolvata mai intai comunicatia SPI. CC1101 de 433 MHz nu este inclus in acest scanner NRF de 2.4 GHz.

Proiect separat pentru ESP32 Dev Module, alimentat USB. Incarcarea inlocuieste firmware-ul de pe placa. Inchide orice aplicatie care foloseste portul serial inainte de rulare. W5500 de pe ESP32-C3 nu poate fi verificat prin aceasta placa fara o legatura intre placi.

## Rulare in PowerShell

PlatformIO este deja instalat pe acest calculator. Din acest director:

```powershell
.\run.ps1 -BuildOnly
.\run.ps1
.\run.ps1 -Port COM5
```

A doua comanda listeaza porturile; inlocuieste COM5 cu portul ESP32 Dev Module. Ultima compileaza, incarca si deschide monitorul la 115200 baud. Apasa EN/RESET daca nu vezi raportul initial. Ctrl+C inchide monitorul. Poti deschide acest director si in extensia PlatformIO pentru VS Code.

## Interpretare

- NRF1/NRF2: PASS confirma comunicatia SPI si scrierea/citirea unui registru. Nu confirma CE, antena, amplificatorul sau un link radio. Nu se transmit pachete radio.
- CC1101: PASS confirma identificarea si scrierea/citirea registrului de canal, restaurat dupa test. Nu confirma receptia la 433 MHz sau cablul GDO0. Accesul are timeout.
- RC522: RASPUNDE indica un registru de versiune diferit de 00/FF. Apropie un card compatibil de 13.56 MHz: RFID READ PASS si UID confirma citirea.
- KY-022: apasa un buton pe o telecomanda IR pentru a vedea codul receptionat.
- KY-005: indreapta-l spre KY-022 si trimite `i` in monitor. Un singur cadru NEC este emis; PASS necesita receptia codului exact. Lipsa receptiei nu identifica singura modulul defect.
- Radar: nivelul OT1/SVP si numarul total de tranzitii sunt afisate la 2 secunde. Un nivel constant sau tranzitiile nu confirma/infirmă singure prezenta, modelul sau protocolul. Nu se presupune ca OT1 este TX UART. GPIO33, conectat la RX radar, ramane HIGH fara comenzi.
- `t` repeta testele SPI. Pinii necompletati in lista nu sunt folositi.

## Pini

| Modul | GPIO ESP32 |
|---|---|
| SPI comun | SCK 18, MISO 19, MOSI 23 |
| CC1101 | CSN 27, GDO0 13; GDO2 neconectat |
| NRF24 #1 | CE 5, CSN 17 |
| NRF24 #2 | CE 16, CSN 4 |
| RC522 | SDA/SS 25, RST 26 |
| KY-022 | S 35 |
| KY-005 | S 32 |
| LD2410 | OT1 SVP (GPIO36), RX 33 |
| W5500 | Pe alt ESP32-C3 SuperMini |

Alimentarea este consemnata exact conform listei: module 3.3V de la ESP32, GND comun; radar VCC=3.3 si separat „Sursa 5V pentru radar=esp32”. Programul nu poate determina tensiunea fizica, capacitatea sursei sau montajul condensatoarelor. Pentru fiecare NRF ai indicat 100uF si 104 intre 3.3V si GND. Testele SPI nu certifica stabilitatea alimentarii sub sarcina.
