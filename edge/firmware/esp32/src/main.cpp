// Remote I/O firmware for an ESP32 dev board: Modbus TCP server on port 502, same register map as the simulation.
// NOT flashed or run on hardware in this project. Compile status is reported in docs/EDGE.md.
//
// Demo hardware only: LEDs or small low-voltage relay modules with an isolated supply. Not for mains or a real
// plant. See the safety note in docs/EDGE.md before wiring anything.
//
// Three layers of failing safe:
//   1. Relay pins are driven LOW before anything else at boot, so reset and boot leave outputs off.
//   2. IoCore's communication watchdog forces outputs off when control writes stop for wdTimeoutMs.
//   3. The ESP32 task watchdog resets the chip if this loop hangs, which lands in case 1.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_random.h>
#include <esp_task_wdt.h>

#include "io_core.h"
#include "regmap.h"
#include "wifi_secrets.h"  // WIFI_SSID and WIFI_PASSWORD. Copy wifi_secrets.h.example; git ignores the copy.

namespace {
// Longer than the simulation default: Wi-Fi round trips are slower and bursty. Tune on the bench.
constexpr uint32_t WD_TIMEOUT_MS = 1000;
constexpr uint32_t LEASE_TTL_MS = 500;
constexpr uint32_t TASK_WDT_S = 3;
constexpr size_t MBAP_LEN = 7;
constexpr uint8_t RELAY_ON = HIGH;  // Set LOW for active-low relay boards, and also change the boot state below.
constexpr float LEVEL_FULL_SCALE_M = 6.0f;  // A potentiometer stands in for the level sensor.
constexpr float FLOW_FULL_SCALE_M3H = 360.0f;

WiFiServer server(502);
WiFiClient clients[regmap::MAX_CLIENTS];
IoCore *core = nullptr;
uint32_t lastTick = 0;

void applyOutputs() {
  digitalWrite(regmap::PIN_RELAY_1, core->output(0) ? RELAY_ON : !RELAY_ON);
  digitalWrite(regmap::PIN_RELAY_2, core->output(1) ? RELAY_ON : !RELAY_ON);
}

void readField() {
  FieldInputs field;
  field.level = analogRead(regmap::PIN_LEVEL_ADC) * LEVEL_FULL_SCALE_M / 4095.0f;
  field.flow = analogRead(regmap::PIN_FLOW_ADC) * FLOW_FULL_SCALE_M3H / 4095.0f;
  // Inputs are active low with the internal pull-up: a closed contact to GND reads as true.
  field.fb1 = digitalRead(regmap::PIN_FB_1) == LOW;
  field.fb2 = digitalRead(regmap::PIN_FB_2) == LOW;
  field.trip1 = digitalRead(regmap::PIN_TRIP_1) == LOW;
  field.trip2 = digitalRead(regmap::PIN_TRIP_2) == LOW;
  field.autoSwitch = digitalRead(regmap::PIN_AUTO_SWITCH) == LOW;
  core->setField(field);
}

// Answer at most one complete frame per call, so one chatty client cannot starve the others or the tick.
void serviceClient(WiFiClient &client) {
  if (!client || !client.connected() || client.available() < static_cast<int>(MBAP_LEN)) {
    return;
  }
  uint8_t header[MBAP_LEN];
  client.peek();
  if (client.read(header, MBAP_LEN) != static_cast<int>(MBAP_LEN)) {
    client.stop();
    return;
  }
  const uint16_t protocol = (header[2] << 8) | header[3];
  const uint16_t length = (header[4] << 8) | header[5];
  if (protocol != 0 || length < 2 || length > 254) {
    client.stop();
    return;
  }
  uint8_t pdu[253];
  const size_t pduLen = length - 1;
  const uint32_t deadline = millis() + 50;
  size_t got = 0;
  while (got < pduLen && static_cast<int32_t>(millis() - deadline) < 0) {
    const int n = client.read(pdu + got, pduLen - got);
    if (n > 0) got += n;
  }
  if (got != pduLen) {
    client.stop();
    return;
  }
  uint8_t response[MBAP_LEN + 256];
  const size_t responseLen = core->handlePdu(pdu, pduLen, response + MBAP_LEN, millis());
  memcpy(response, header, 4);  // Transaction and protocol id are echoed.
  response[4] = static_cast<uint8_t>((responseLen + 1) >> 8);
  response[5] = static_cast<uint8_t>((responseLen + 1) & 0xFF);
  response[6] = header[6];
  client.write(response, MBAP_LEN + responseLen);
  applyOutputs();  // A control write takes effect at once, not at the next tick.
}

void acceptClients() {
  WiFiClient incoming = server.available();
  if (!incoming) {
    return;
  }
  incoming.setNoDelay(true);
  for (WiFiClient &slot : clients) {
    if (!slot || !slot.connected()) {
      slot.stop();
      slot = incoming;
      return;
    }
  }
  incoming.stop();  // All slots taken.
}
}  // namespace

void setup() {
  // Safe state first, before Wi-Fi or anything else that could block.
  pinMode(regmap::PIN_RELAY_1, OUTPUT);
  pinMode(regmap::PIN_RELAY_2, OUTPUT);
  digitalWrite(regmap::PIN_RELAY_1, !RELAY_ON);
  digitalWrite(regmap::PIN_RELAY_2, !RELAY_ON);
  for (uint8_t pin : {regmap::PIN_FB_1, regmap::PIN_FB_2, regmap::PIN_TRIP_1, regmap::PIN_TRIP_2, regmap::PIN_AUTO_SWITCH}) {
    pinMode(pin, INPUT_PULLUP);
  }
  analogReadResolution(12);

  Serial.begin(115200);
  // ADC1 pins only: ADC2 does not work while Wi-Fi is on.
  esp_task_wdt_init(TASK_WDT_S, true);
  esp_task_wdt_add(nullptr);

  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);  // Modem sleep adds hundreds of ms of latency.
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    esp_task_wdt_reset();
    delay(100);
  }
  Serial.print("st2fb remote I/O at ");
  Serial.println(WiFi.localIP());

  // A random first epoch: a token from before a reboot cannot match by accident.
  core = new IoCore(static_cast<uint16_t>(esp_random() % 0xFFF0) + 1, WD_TIMEOUT_MS, LEASE_TTL_MS, millis());
  server.begin();
  server.setNoDelay(true);
}

void loop() {
  esp_task_wdt_reset();
  acceptClients();
  for (WiFiClient &client : clients) {
    serviceClient(client);
  }
  const uint32_t now = millis();
  if (now - lastTick >= regmap::TICK_MS) {
    lastTick = now;
    readField();
    core->tick(now);
    applyOutputs();
  }
  delay(1);  // Yield to the Wi-Fi task.
}
