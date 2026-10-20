#include <WiFi.h>

// Set to the 2.4 GHz router SSID. BSSID filtering is recommended when multiple APs share SSID.
const char* TARGET_SSID = "YOUR_WIFI_SSID";
const char* TARGET_BSSID = ""; // Optional, e.g. "AA:BB:CC:DD:EE:FF"
const uint32_t SCAN_INTERVAL_MS = 1200;
uint32_t lastScan = 0;

void setup() {
  Serial.begin(115200);
  delay(1500);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  Serial.println("READY,ESP32S3_WIFI_MAPPING");
  Serial.println("DATA_FORMAT,epoch_ms,bssid,channel,rssi");
}

void loop() {
  if (millis() - lastScan < SCAN_INTERVAL_MS) return;
  lastScan = millis();
  int n = WiFi.scanNetworks(false, true, false, 300);
  bool found = false;
  for (int i = 0; i < n; i++) {
    String bssid = WiFi.BSSIDstr(i);
    if (WiFi.SSID(i) == TARGET_SSID &&
        (strlen(TARGET_BSSID) == 0 || bssid.equalsIgnoreCase(TARGET_BSSID))) {
      Serial.printf("DATA,%lu,%s,%d,%d\n", millis(), bssid.c_str(), WiFi.channel(i), WiFi.RSSI(i));
      found = true;
    }
  }
  if (!found) Serial.println("WARN,TARGET_NOT_FOUND");
  WiFi.scanDelete();
}
