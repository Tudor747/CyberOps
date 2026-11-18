#pragma once
#include <Arduino.h>
namespace Pins {
constexpr uint8_t SCK=18, MOSI=23, MISO=19;
constexpr uint8_t NRF1_CE=27, NRF1_CS=14, NRF2_CE=17, NRF2_CS=16;
constexpr uint8_t CC_CS=21, CC_GDO0=35, CC_GDO2=15;
constexpr uint8_t RFID_CS=5, RFID_RST=22;
constexpr uint8_t RADAR_RX=32, RADAR_TX=33;
constexpr uint8_t IR_TX=26, IR_RX=34, ETH_CS=4;
constexpr uint8_t CHIP_SELECTS[]={NRF1_CS,NRF2_CS,CC_CS,RFID_CS,ETH_CS};
}
