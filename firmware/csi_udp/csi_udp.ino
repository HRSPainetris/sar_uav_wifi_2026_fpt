// ESP32-C5, Arduino-ESP32 with ESP-IDF 5.5+ CSI HE API.
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>
#include <esp_timer.h>
#include "secrets.h"

#if !CONFIG_IDF_TARGET_ESP32C5
#error "Select ESP32C5 Dev Module and a core supporting ESP32-C5"
#endif

// Wire format is little endian, no native SDK structs on the wire.
struct __attribute__((packed)) Header {
  char magic[4];
  uint8_t version, flags;
  uint16_t node;
  uint32_t sequence;
  uint64_t timestampUs;
  uint8_t mac[6];
  int8_t rssi;
  uint8_t channel;
  uint16_t length;
};
static_assert(sizeof(Header) == 30, "wire header");
constexpr size_t MAX_CSI = 1024;
struct Frame { Header h; int8_t iq[MAX_CSI]; };
QueueHandle_t frames;
WiFiUDP udp;
IPAddress destination;
uint8_t sourceMac[6];
uint32_t sequence = 0;
volatile uint32_t queueDrops = 0;

void onCSI(void *, wifi_csi_info_t *info) {
  // Wi-Fi task callback: copy only, never send UDP or print here.
  if (!info || !info->buf || memcmp(info->mac, sourceMac, 6)) return;
  if (!info->len || info->len > MAX_CSI || (info->len & 1)) return;
  Frame f{};
  memcpy(f.h.magic, "CSI1", 4);
  f.h.version = 1;
  f.h.flags = info->first_word_invalid ? 1 : 0;
  f.h.node = 1; // assign a distinct ID for each receiver
  f.h.sequence = sequence++;
  f.h.timestampUs = esp_timer_get_time();
  memcpy(f.h.mac, info->mac, 6);
  f.h.rssi = info->rx_ctrl.rssi;
  f.h.channel = info->rx_ctrl.channel;
  f.h.length = info->len;
  memcpy(f.iq, info->buf, info->len);
  if (xQueueSend(frames, &f, 0) != pdTRUE) ++queueDrops;
}

void setup() {
  Serial.begin(115200);
  frames = xQueueCreate(16, sizeof(Frame));
  if (!frames || !destination.fromString(PC_IP)) abort();
  WiFi.mode(WIFI_STA);
  // C5 supports both bands; lock this experiment to 2.4 GHz.
  ESP_ERROR_CHECK(esp_wifi_set_band_mode(WIFI_BAND_MODE_2G_ONLY));
  ESP_ERROR_CHECK(esp_wifi_set_protocol(WIFI_IF_STA,
                                      WIFI_PROTOCOL_11B | WIFI_PROTOCOL_11G | WIFI_PROTOCOL_11N));
  ESP_ERROR_CHECK(esp_wifi_set_bandwidth(WIFI_IF_STA, WIFI_BW_HT20));
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  const uint32_t start = millis();
  while (WiFi.status() != WL_CONNECTED) {
    if (millis() - start > 30000) { Serial.println("Wi-Fi timeout"); abort(); }
    delay(100);
  }
  ESP_ERROR_CHECK(esp_wifi_set_ps(WIFI_PS_NONE));
  memcpy(sourceMac, WiFi.BSSID(), 6); // only the associated AP; avoid mixed links
  Serial.print("Node IP: "); Serial.println(WiFi.localIP());
  wifi_csi_config_t cfg{};
  cfg.enable = 1;
  cfg.acquire_csi_legacy = 1;
#if CONFIG_SOC_WIFI_MAC_VERSION_NUM == 3
  cfg.acquire_csi_force_lltf = 1;
#endif
  // HT/HE extraction disabled: do not concatenate heterogeneous LTF layouts.
  ESP_ERROR_CHECK(esp_wifi_set_promiscuous(true));
  ESP_ERROR_CHECK(esp_wifi_set_csi_rx_cb(onCSI, nullptr));
  ESP_ERROR_CHECK(esp_wifi_set_csi_config(&cfg));
  ESP_ERROR_CHECK(esp_wifi_set_csi(true));
  if (!udp.begin(5501)) abort();
}

void loop() {
  Frame f;
  if (xQueueReceive(frames, &f, pdMS_TO_TICKS(10)) == pdTRUE) {
    if (udp.beginPacket(destination, 5500)) {
      udp.write(reinterpret_cast<const uint8_t *>(&f.h), sizeof(Header));
      udp.write(reinterpret_cast<const uint8_t *>(f.iq), f.h.length);
      udp.endPacket();
    }
  }
  static uint32_t last = 0;
  if (millis() - last > 5000) {
    Serial.printf("queue drops=%lu, Wi-Fi=%d\n", (unsigned long)queueDrops, WiFi.status());
    last = millis();
  }
}
