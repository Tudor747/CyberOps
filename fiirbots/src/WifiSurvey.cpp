#include <Arduino.h>
#include <atomic>
#include <esp_event.h>
#include <esp_netif.h>
#include <esp_wifi.h>
#include "WifiSurvey.h"

namespace {
constexpr unsigned dwellMs = 300;
constexpr unsigned scanTimeoutMs = 10000;
constexpr unsigned resultIdleMs = 30000;
constexpr unsigned pageSize = 12;
constexpr int workerPending = -2;

// Only the worker calls the blocking IDF scan. The Arduino loop owns the driver
// lifecycle and result snapshot, so retries return the same page.
std::atomic<int> workerResult{ESP_OK};
bool workerActive = false;
bool driverInitialized = false;
bool driverStarted = false;
char scanId[33] = {};
char cancelledId[33] = {};
unsigned long startedAt = 0, lastRequestAt = 0;
esp_err_t scanError = ESP_OK;
wifi_ap_record_t* records = nullptr;
uint16_t count = 0;

void scanWorker(void*) {
    wifi_scan_config_t config = {};
    config.show_hidden = true;
    config.scan_type = WIFI_SCAN_TYPE_PASSIVE;
    config.scan_time.passive = dwellMs;
    workerResult.store(esp_wifi_scan_start(&config, true));
    vTaskDelete(nullptr);
}

void stopDriver() {
    if (driverStarted) {
        if (workerActive) esp_wifi_scan_stop();
        esp_wifi_stop();
        driverStarted = false;
    }
    if (driverInitialized && !workerActive) {
        esp_wifi_deinit();
        driverInitialized = false;
    }
}

esp_err_t startScan() {
    static bool networkInitialized = false;
    if (!networkInitialized) {
        esp_err_t err = esp_netif_init();
        if (err != ESP_OK) return err;
        err = esp_event_loop_create_default();
        if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) return err;
        networkInitialized = true;
    }
    wifi_init_config_t init = WIFI_INIT_CONFIG_DEFAULT();
    esp_err_t err = esp_wifi_init(&init);
    if (err != ESP_OK) return err;
    driverInitialized = true;
    err = esp_wifi_set_storage(WIFI_STORAGE_RAM);
    if (err == ESP_OK) err = esp_wifi_set_mode(WIFI_MODE_STA);
    if (err == ESP_OK) err = esp_wifi_start();
    if (err != ESP_OK) return err;
    driverStarted = true;
    workerResult.store(workerPending);
    workerActive = xTaskCreate(scanWorker, "wifi-survey", 4096, nullptr, 1, nullptr) == pdPASS;
    return workerActive ? ESP_OK : ESP_ERR_NO_MEM;
}

esp_err_t collectResults() {
    esp_err_t err = esp_wifi_scan_get_ap_num(&count);
    if (err == ESP_OK && count > 0) {
        records = static_cast<wifi_ap_record_t*>(calloc(count, sizeof(*records)));
        if (!records) return ESP_ERR_NO_MEM;
        const uint16_t expected = count;
        err = esp_wifi_scan_get_ap_records(&count, records);
        if (err == ESP_OK && count != expected) return ESP_FAIL;
    }
    return err;
}

const char* securityName(wifi_auth_mode_t mode) {
    switch (mode) {
    case WIFI_AUTH_OPEN: return "Open";
    case WIFI_AUTH_WEP: return "WEP";
    case WIFI_AUTH_WPA_PSK: return "WPA-PSK";
    case WIFI_AUTH_WPA2_PSK: return "WPA2-PSK";
    case WIFI_AUTH_WPA_WPA2_PSK: return "WPA/WPA2-PSK";
    case WIFI_AUTH_WPA2_ENTERPRISE: return "WPA2-Enterprise";
    case WIFI_AUTH_WPA3_PSK: return "WPA3-PSK";
    case WIFI_AUTH_WPA2_WPA3_PSK: return "WPA2/WPA3-PSK";
    case WIFI_AUTH_WAPI_PSK: return "WAPI-PSK";
    default: return "Unknown";
    }
}

void writeRecord(JsonObject row, const wifi_ap_record_t& ap) {
    char bssid[18];
    snprintf(bssid, sizeof(bssid), "%02X:%02X:%02X:%02X:%02X:%02X", ap.bssid[0],
             ap.bssid[1], ap.bssid[2], ap.bssid[3], ap.bssid[4], ap.bssid[5]);
    char ssidHex[65];
    const char* hex = "0123456789abcdef";
    size_t len = strnlen(reinterpret_cast<const char*>(ap.ssid), 32);
    bool printable = true;
    for (size_t i = 0; i < len; ++i) {
        ssidHex[i * 2] = hex[ap.ssid[i] >> 4];
        ssidHex[i * 2 + 1] = hex[ap.ssid[i] & 15];
        if (ap.ssid[i] < 32 || ap.ssid[i] > 126) printable = false;
    }
    ssidHex[len * 2] = 0;
    row["ssid_hex"] = ssidHex;
    row["ssid"] = printable ? String(reinterpret_cast<const char*>(ap.ssid), len) : String("0x") + ssidHex;
    row["bssid"] = bssid;
    row["rssi_dbm"] = ap.rssi;
    row["channel"] = ap.primary;
    row["security"] = securityName(ap.authmode);
}

void errorResponse(JsonDocument& response, const char* message) {
    response["status"] = "ERROR";
    response["message"] = message;
}
}

void wifiSurveyStop() {
    if (scanId[0]) strlcpy(cancelledId, scanId, sizeof(cancelledId));
    scanId[0] = 0;
    free(records);
    records = nullptr;
    count = 0;
    stopDriver();
}

void wifiSurveyTick() {
    const unsigned long now = millis();
    if (workerActive) {
        int result = workerResult.load();
        if (result == workerPending) {
            if (driverStarted && now - startedAt > scanTimeoutMs) {
                scanError = ESP_ERR_TIMEOUT;
                stopDriver();
            }
            return;
        }
        workerActive = false;
        if (scanId[0] && scanError == ESP_OK) {
            scanError = result == ESP_OK ? collectResults() : result;
            if (scanError != ESP_OK) esp_wifi_clear_ap_list();
        }
        stopDriver();
    }
    if (scanId[0] && now - lastRequestAt > resultIdleMs) wifiSurveyStop();
}

void wifiSurveyCommand(const JsonDocument& command, JsonDocument& response, bool monitorActive) {
    const char* id = command["scan_id"] | "";
    const char* cmd = command["cmd"] | "";
    if (strlen(id) < 12 || strlen(id) > 32 ||
        strspn(id, "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_") != strlen(id)) {
        errorResponse(response, "Invalid Wi-Fi scan identity");
        return;
    }
    const bool match = strcmp(id, scanId) == 0;
    if (!strcmp(cmd, "WIFI_SCAN_CANCEL")) {
        if (match) wifiSurveyStop();
        else if (strcmp(id, cancelledId) != 0) {
            errorResponse(response, "Wi-Fi scan identity mismatch");
            return;
        }
        response["status"] = "STOPPED";
        return;
    }
    if (!monitorActive) {
        errorResponse(response, "Hardware monitoring must be active for a Wi-Fi scan");
        return;
    }
    bool start = !strcmp(cmd, "WIFI_SCAN_START");
    if (!match) {
        if (!start || workerActive) {
            errorResponse(response, start ? "Wi-Fi scan already running" : "Wi-Fi scan expired or changed");
            return;
        }
        wifiSurveyStop();
        strlcpy(scanId, id, sizeof(scanId));
        startedAt = millis();
        scanError = startScan();
        if (scanError != ESP_OK) stopDriver();
    }
    lastRequestAt = millis();
    if (scanError != ESP_OK) {
        response["status"] = "ERROR";
        response["message"] = String("Wi-Fi survey failed: ") + esp_err_to_name(scanError);
        return;
    }
    if (!start && !command["offset"].is<uint16_t>()) {
        errorResponse(response, "Invalid Wi-Fi page offset");
        return;
    }
    response["status"] = "WIFI_SCAN";
    response["scan_id"] = id;
    if (workerActive) {
        response["state"] = "scanning";
        return;
    }
    unsigned offset = start ? 0 : command["offset"].as<uint16_t>();
    if (offset > count) {
        errorResponse(response, "Wi-Fi page offset outside snapshot");
        return;
    }
    response["state"] = "complete";
    response["offset"] = offset;
    response["total"] = count;
    unsigned end = std::min<unsigned>(count, offset + pageSize);
    JsonArray rows = response["networks"].to<JsonArray>();
    for (unsigned i = offset; i < end; ++i) writeRecord(rows.add<JsonObject>(), records[i]);
    response["next_offset"] = nullptr;
    if (end < count) response["next_offset"] = end;
    if (response.overflowed()) {
        response.clear();
        response["request_id"] = command["request_id"] | "";
        errorResponse(response, "Insufficient memory for Wi-Fi survey page");
    }
}
