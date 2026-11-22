/*
  ESP32 SOFTAP -> UART TRANSPARENT BRIDGE  (laser turret)
  -------------------------------------------------------
  The ESP32 is ALWAYS an access point: TURRET_LINK @ 192.168.4.1, TCP 8888.
  There is no station/mobile-hotspot mode and no Wi-Fi password in this sketch.
  The PC joins TURRET_LINK for the turret link; internet stays on Bluetooth
  tethering, so the phone's Wi-Fi hotspot is not involved at all.

  SETUP (once):
    1. Flash via CP2102 on the PSU header (BOOT held, tap EN), or OTA once online.
    2. Remove the CP2102 signal wires, restore PA9 -> header 4, power on.
    3. On the PC join Wi-Fi "TURRET_LINK" (open).
    4. Run the simulator - it connects straight to 192.168.4.1:8888.

  HARDWARE UART - ESP32'S ORIGINAL TX/RX (UART0)
    GPIO1  TX  -> PSU header 3 -> Blue Pill PA10 (UART1 RX)
    GPIO3  RX  <- PSU header 4 <- Blue Pill PA9  (UART1 TX)
    GND        -> PSU header 5
  CP2102 must be removed from header 3/4 during normal operation: its TX would
  contend with the Blue Pill's PA9 on GPIO3.

  DEBUG: Serial1 TX on GPIO26 (optional, not needed for operation).
  UART0: 115200 8N1. Payload is unchanged: S<pan>,<tilt>\n / F\n

  OVER-THE-AIR UPDATES (no more opening the box):
    Once this sketch is flashed, later updates go over the same AP:
      espota.py -i 192.168.4.1 -p 3232 -a turret -f <firmware.bin>
    OTA reboots straight into the new sketch, so you never touch EN/BOOT again.
*/
#include <WiFi.h>
#include <ArduinoOTA.h>

static const char* AP_SSID = "TURRET_LINK";
static const IPAddress AP_IP(192, 168, 4, 1);
static const IPAddress AP_GW(192, 168, 4, 1);
static const IPAddress AP_MASK(255, 255, 255, 0);

static const uint16_t TCP_PORT = 8888;
static const int DEBUG_TX = 26;           // Serial1 TX only (optional)

// Serial = UART0 = GPIO1 TX / GPIO3 RX = the PSU header pins already wired.
#define LINK Serial

WiFiServer server(TCP_PORT);
WiFiClient client;

unsigned long lastBlink = 0;
bool ledState = false;

static void blink(unsigned long period) {
  unsigned long now = millis();
  if (now - lastBlink >= period) {
    lastBlink = now;
    ledState = !ledState;
    digitalWrite(2, ledState ? HIGH : LOW);
  }
}

void startServer() {
  server.begin();
  server.setNoDelay(true);
}

static void setupOTA() {
  ArduinoOTA.setHostname("turret-bridge");
  ArduinoOTA.setPassword("turret");
  ArduinoOTA.onStart([]() {
    Serial1.println("[OTA] update started");
    digitalWrite(2, LOW);
  });
  ArduinoOTA.onEnd([]() {
    Serial1.println("\n[OTA] done - rebooting");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial1.printf("[OTA] %u%%\r", (progress * 100) / total);
    digitalWrite(2, !digitalRead(2));
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial1.print("[OTA] ERROR "); Serial1.println(error);
  });
  ArduinoOTA.begin();
  Serial1.println("[OTA] ready on UDP/TCP 3232");
}

void setup() {
  LINK.begin(115200);                     // turret UART on original TX/RX
  Serial1.begin(115200, SERIAL_8N1, 25, DEBUG_TX);  // debug only

  pinMode(2, OUTPUT);
  digitalWrite(2, LOW);

  Serial1.println("--- ESP32 turret bridge (AP-only, UART0) ---");
  Serial1.print("[WiFi] SoftAP "); Serial1.println(AP_SSID);

  WiFi.mode(WIFI_AP);
  WiFi.softAPConfig(AP_IP, AP_GW, AP_MASK);
  WiFi.softAP(AP_SSID);

  Serial1.print("[WiFi] AP IP="); Serial1.println(WiFi.softAPIP());

  startServer();
  setupOTA();
}

void loop() {
  ArduinoOTA.handle();                    // firmware updates, no box opening

  // One blink every loop in every state (the old STA build froze the LED ON
  // while online with no client).
  unsigned long ledPeriod = (client && client.connected()) ? 200UL : 1000UL;
  blink(ledPeriod);

  if (!client || !client.connected()) {
    client = server.available();
    if (client) {
      client.setNoDelay(true);
      // Greeting doubles as discovery + confirmation the right bridge was found.
      client.println("TURRET_LINK_READY");
      Serial1.print("[WiFi] client connected, IP="); Serial1.println(client.remoteIP());
      Serial1.print("[WiFi] serving on "); Serial1.println(WiFi.softAPIP());
    }
  }

  // TCP -> ESP32 TX -> Blue Pill PA10
  // No per-byte debug here: it delays forwarding and can starve UART TX.
  if (client && client.connected()) {
    while (client.available() > 0) {
      int b = client.read();
      if (b >= 0) LINK.write((uint8_t)b);
    }
  }

  // Blue Pill PA9 -> ESP32 RX -> TCP.
  // Chunked read/write, drained even with no client. A per-byte Serial1.printf
  // used to live here; at 115200 it was slower than the UART feed and dropped
  // the tail of long replies (e.g. the H help text over WiFi).
  uint8_t buf[128];
  size_t n = 0;
  while (LINK.available() > 0 && n < sizeof(buf)) {
    buf[n++] = (uint8_t)LINK.read();
  }
  if (n > 0 && client && client.connected()) client.write(buf, n);
}
