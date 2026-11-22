/*
  TURRET MAIN FIRMWARE - STM32 Blue Pill (Arduino_STM32 core)

  Pins:
    PA1  servo X (pan)    centre 80, WORKING 20..140, REST 180
    PA0  servo Y (tilt)   centre 75, WORKING 30..130, REST 180
    PA2  laser            HIGH = ON (1kR -> BC547 base, low-side switch)
    PA9  UART1 TX  -> ESP32 RX
    PA10 UART1 RX  <- ESP32 TX

  Two independent serial interfaces:
    Serial  (USB, COM9) : bench/debug commands
    Serial1 (UART1)     : real link from ESP32, 115200

  LINK PROTOCOL (Serial1, 115200, newline terminated):
    S<pan>,<tilt>   engage: move both to target, laser ON
    F               release: laser OFF, servos HOLD position

  WORKING ENVELOPE (hard-enforced in firmware):
    X 20..140   (centre 80 +/- 60)
    Y 30..130
  REST is the only way past X140:
    X180 first, then Y180, laser forced OFF.

  WATCHDOG (link commands only):
    2s  no valid command -> laser OFF
    15s no valid command -> REST (auto-park)

  Debug loops also obey the working envelope.
*/
#include <Servo.h>

// ---------- pulse helper ----------
// Exactly matches this core's Servo::write(): map(angle, 0,180, 544,2400)
// with integer truncation at whole degrees, but interpolates between them.
// Same endpoints as write() -> no change to the safe envelope.
static uint16_t degToUs(float a) {
  if (a < 0.0f) a = 0.0f;
  if (a > 180.0f) a = 180.0f;
  int lo = (int)a;
  if (lo > 179) lo = 179;
  float frac = a - (float)lo;
  uint32_t u0 = 544UL + ((uint32_t)lo * 1856UL) / 180UL;
  uint32_t u1 = 544UL + ((uint32_t)(lo + 1) * 1856UL) / 180UL;
  return (uint16_t)(u0 + frac * (float)(u1 - u0) + 0.5f);
}

// ---------- pins ----------
const int PIN_X = PA1;
const int PIN_Y = PA0;
const int PIN_LASER = PA2;

// ---------- geometry ----------
const int CENTRE_X  = 100;   // new alignment: X centre 100
const int CENTRE_Y  = 80;    // new alignment: Y centre 80
const int X_WORK_MIN = 50;   // centre +/- 50 (reduced 10 each side)
const int X_WORK_MAX = 150;
const int Y_MIN      = 40;   // below 40 laser hides in the mount
const int Y_MAX      = 140;
const int X_REST     = 180;
const int Y_REST     = 180;

// ---------- timing ----------
const int STEP_MS = 10;                  // ms per 1 degree of target logic
const unsigned long DRIVE_MS = 5;        // servo output tick (sub-degree interpolation)
const unsigned long REPORT_MS = 100;     // feedback throttle (was every step -> ~20ms Serial block)
const unsigned long LASER_TIMEOUT = 2000;
const unsigned long REST_TIMEOUT  = 15000;

Servo servoX;
Servo servoY;

int posX = CENTRE_X;
int posY = CENTRE_Y;
int targetX = CENTRE_X;
int targetY = CENTRE_Y;
bool laserState = false;

unsigned long lastLink = 0;
unsigned long lastUsb = 0;
bool linkSeen = false;
unsigned long lastStep = 0;

// --- sub-degree output layer: servo sees smooth pulses, logic stays integer ---
float smoothX = CENTRE_X;
float smoothY = CENTRE_Y;
unsigned long lastDrive = 0;
unsigned long lastReport = 0;

// --- smooth diagnostic ---
// J0 stop | J1/J2 slow X/Y | J3/J4 fast X/Y | J5 both slow | J6 both fast
int diagAxis = 0;                 // 0 off, 1 X, 2 Y, 3 both
float diagPosX = CENTRE_X, diagPosY = CENTRE_Y;
int diagDirX = 1, diagDirY = 1;
float diagStepDeg = 0.1f;
unsigned long lastDiag = 0;
unsigned long diagTickMs = 10;
const unsigned long DIAG_MS_SLOW = 10;  // 0.1deg/10ms = 10 deg/s
const unsigned long DIAG_MS_FAST = 2;   // 0.5deg/2ms  = 250 deg/s

// rest state machine:
// 0 normal | 1 fold X to 180 | 2 lower Y to 180
// 3 raise Y back to 130 | 4 return X to working range
int restPhase = 0;
bool atRest = false;
int resumeX = CENTRE_X;
int resumeY = CENTRE_Y;
bool resumeLaser = false;

// debug loop state
int loopMode = 0;              // 0 off, 1 straight, 2 infinity
int loopTgtX = CENTRE_X;
int loopTgtY = CENTRE_Y;
int f8Phase = 0;
unsigned long lastHold = 0;

// figure-8 constants (inside final envelope X50..150, Y40..140)
const int F8_X_C = CENTRE_X;
const int F8_X_A = 50;         // X 50..150
const int F8_Y_C = 90;         // midpoint of 40..140
const int F8_Y_A = 50;         // Y 40..140
const int F8_STEPS = 360;
const float F8_TAU = 6.28318530718f;
unsigned long f8TickMs = 10;   // infinity speed: 10ms normal, J7 slow 40ms, J8 fast 3ms

// ---------- helpers ----------
void setLaser(bool on) {
  if (laserState == on) return;
  laserState = on;
  digitalWrite(PIN_LASER, on ? HIGH : LOW);
}

// Approach an integer target with sub-degree steps. Minimum 0.3deg (~3us) per
// output tick keeps commands outside the servo deadband -> no slow stick-slip.
static float approachDeg(float cur, float tgt) {
  float d = tgt - cur;
  if (fabs(d) < 0.05f) return tgt;
  float step = d * 0.8f;
  if (step > 0.0f && step < 0.3f) step = 0.3f;
  if (step < 0.0f && step > -0.3f) step = -0.3f;
  if (fabs(step) >= fabs(d)) return tgt;
  return cur + step;
}

void driveServos() {
  if (diagAxis != 0) return;          // diagnostic owns the servos during J1..J4
  smoothX = approachDeg(smoothX, (float)posX);
  smoothY = approachDeg(smoothY, (float)posY);
  servoX.writeMicroseconds(degToUs(smoothX));
  servoY.writeMicroseconds(degToUs(smoothY));
}

void report(Stream &s) {
  s.print("X=");
  s.print(posX);
  s.print(" Y=");
  s.print(posY);
  s.print(" LASER=");
  s.println(laserState ? "ON" : "OFF");
}

void printHelp(Stream &s) {
  s.println("--- turret main ---");
  s.println("LINK Serial1: S<pan>,<tilt> engage | F release");
  s.println("USB: C centre | X<n> Y<n> | S laser OFF | L line | I infinity");
  s.println("USB: O laser ON | F laser OFF | Q status | H help");
  s.println("USB diag: J0 stop | J1/J2 X/Y slow | J3/J4 X/Y fast");
  s.println("USB diag: J5 BOTH slow | J6 BOTH fast | J7 inf slow | J8 inf fast");
  s.println("center X100 Y80 | limits X50..150 Y40..140 | no rest");
  s.println("motion: sub-degree 5ms, feedback 100ms, watchdog 2s laser-off");
  s.print("WORK X "); s.print(X_WORK_MIN); s.print(".."); s.print(X_WORK_MAX);
  s.print("  Y "); s.print(Y_MIN); s.print(".."); s.println(Y_MAX);
  s.println("REST removed | S = laser OFF, hold position");
}

// ---------- smooth single-axis diagnostic ----------
void startDiag(int axis, bool fast) {
  if (restPhase != 0 || atRest) {
    Serial.println("diag: exit rest first (send C)");
    return;
  }
  loopMode = 0;
  setLaser(false);                 // diagnostics never fire the laser
  diagAxis = axis;
  diagStepDeg = fast ? 0.5f : 0.1f;
  diagTickMs = fast ? DIAG_MS_FAST : DIAG_MS_SLOW;
  diagDirX = 1; diagDirY = 1;
  diagPosX = (float)posX;
  diagPosY = (float)posY;
  if (axis == 1) Serial.println(fast ? "J3: X-only FAST smooth sweep" : "J1: X-only SLOW smooth sweep");
  else if (axis == 2) Serial.println(fast ? "J4: Y-only FAST smooth sweep" : "J2: Y-only SLOW smooth sweep");
  else Serial.println(fast ? "J6: BOTH FAST parallel sweep" : "J5: BOTH SLOW parallel sweep");
  lastDiag = millis();
}

void serviceDiag() {
  unsigned long now = millis();
  if (now - lastDiag < diagTickMs) return;
  lastDiag = now;

  bool bounced = false;
  if (diagAxis == 1 || diagAxis == 3) {
    diagPosX += diagDirX * diagStepDeg;
    if (diagPosX >= X_WORK_MAX) { diagPosX = X_WORK_MAX; diagDirX = -1; bounced = true; }
    if (diagPosX <= X_WORK_MIN) { diagPosX = X_WORK_MIN; diagDirX =  1; bounced = true; }
    servoX.writeMicroseconds(degToUs(diagPosX));
    smoothX = diagPosX;            // keep output state synced -> no snap on J0
    posX = (int)(diagPosX + 0.5f);
  }
  if (diagAxis == 2 || diagAxis == 3) {
    diagPosY += diagDirY * diagStepDeg;
    if (diagPosY >= Y_MAX) { diagPosY = Y_MAX; diagDirY = -1; bounced = true; }
    if (diagPosY <= Y_MIN) { diagPosY = Y_MIN; diagDirY =  1; bounced = true; }
    servoY.writeMicroseconds(degToUs(diagPosY));
    smoothY = diagPosY;            // keep output state synced -> no snap on J0
    posY = (int)(diagPosY + 0.5f);
  }
  if (bounced) report(Serial);     // throttled: one line per end of sweep
}

// ---------- mode changes ----------
void requestRest() {
  // CALIBRATION BUILD: no fold. S = laser OFF, hold position.
  loopMode = 0;
  setLaser(false);
}

void requestEngage(int x, int y, bool laser) {
  loopMode = 0;
  resumeX = constrain(x, X_WORK_MIN, X_WORK_MAX);
  resumeY = constrain(y, Y_MIN, Y_MAX);
  resumeLaser = laser;

  if (atRest) {
    restPhase = 3;             // raise Y to 130 while still at X180
  } else if (restPhase == 2) {
    restPhase = 3;             // Y was lowering - raise it before X leaves 180
  } else if (restPhase == 1) {
    restPhase = 0;             // X still inside working range - safe to abort
    targetX = resumeX;
    targetY = resumeY;
    setLaser(resumeLaser);
  } else {
    targetX = resumeX;
    targetY = resumeY;
    setLaser(resumeLaser);
  }

}

// ---------- non-blocking rest transitions ----------
void serviceRest() {
  if (restPhase == 1) {
    if (posX < X_REST) posX++;
    else if (posX > X_REST) posX--;
    if (posX == X_REST) restPhase = 2;

  } else if (restPhase == 2) {
    if (posY < Y_REST) posY++;
    if (posY >= Y_REST) {
      restPhase = 0;
      atRest = true;
      setLaser(false);
    }

  } else if (restPhase == 3) {
    // still at X180 - bring Y back inside the safe arc first
    if (posY > Y_MAX) posY--;
    if (posY <= Y_MAX) {
      restPhase = 4;
      atRest = false;
      targetX = resumeX;
      targetY = resumeY;
    }

  } else if (restPhase == 4) {
    if (posX > targetX) posX--;
    else if (posX < targetX) posX++;
    if (posY < targetY) posY++;
    else if (posY > targetY) posY--;
    if (posX == targetX && posY == targetY) {
      restPhase = 0;
      setLaser(resumeLaser);
    }
  }
}

// ---------- stepping ----------
void stepToTarget() {
  if (posX < targetX) posX++;
  else if (posX > targetX) posX--;
  if (posY < targetY) posY++;
  else if (posY > targetY) posY--;
}

void stepLine() {
  if (posX < loopTgtX) posX++;
  else if (posX > loopTgtX) posX--;
  if (posY < loopTgtY) posY++;
  else if (posY > loopTgtY) posY--;
}

void stepInfinity() {
  float t = (float)f8Phase * F8_TAU / (float)F8_STEPS;
  int nx = F8_X_C + (int)(F8_X_A * sin(t) + 0.5f);
  int ny = F8_Y_C + (int)(F8_Y_A * sin(2.0f * t) + 0.5f);
  posX = constrain(nx, X_WORK_MIN, X_WORK_MAX);
  posY = constrain(ny, Y_MIN, Y_MAX);
  f8Phase++;
  if (f8Phase >= F8_STEPS) f8Phase = 0;
}

void serviceWatchdog() {
  if (diagAxis != 0) return;       // never interfere with diagnostics/loops
  if (loopMode != 0) return;       // leave demo loops alone
  if (!linkSeen) return;           // USB-only debugging does not trigger watchdog
  if (millis() - lastUsb < 30000UL) return;  // active USB session suppresses watchdog
  if (millis() - lastLink >= LASER_TIMEOUT) setLaser(false);  // 2s no link -> laser OFF
  // No auto-park. REST_TIMEOUT removed by design.
  (void)REST_TIMEOUT;
}

// ---------- command parsers ----------
void handleLink() {
  while (Serial1.available()) {
    String cmd = Serial1.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();

    if (cmd.startsWith("S")) {
      int c = cmd.indexOf(',');
      int x, y;
      if (c > 0) {
        x = cmd.substring(1, c).toInt();
        y = cmd.substring(c + 1).toInt();
      } else {
        x = cmd.substring(1).toInt();
        y = CENTRE_Y;
      }
      requestEngage(x, y, true);
      linkSeen = true;
      lastLink = millis();
      report(Serial1);

    } else if (cmd.startsWith("F")) {
      setLaser(false);         // release: laser off, hold position
      linkSeen = true;
      lastLink = millis();
      report(Serial1);

    } else if (cmd.startsWith("H")) {
      printHelp(Serial1);
    }
  }
}

void handleUsb() {
  while (Serial.available()) {
    lastUsb = millis();
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();
    char c = cmd.charAt(0);
    int v = cmd.substring(1).toInt();

    if (c == 'C') {
      requestEngage(CENTRE_X, CENTRE_Y, true);
      report(Serial);

    } else if (c == 'X') {
      requestEngage(v, posY, laserState);
      report(Serial);

    } else if (c == 'Y') {
      requestEngage(posX, v, laserState);
      report(Serial);

    } else if (c == 'S') {
      requestRest();
      report(Serial);

    } else if (c == 'O') {
      setLaser(true);
      report(Serial);

    } else if (c == 'F') {
      setLaser(false);
      report(Serial);

    } else if (c == 'L') {
      loopMode = (loopMode == 1) ? 0 : 1;
      if (loopMode == 1 && restPhase == 0 && !atRest) {
        loopTgtX = posX; loopTgtY = posY;
        lastHold = millis();
      }
      Serial.println(loopMode == 1 ? "line loop START" : "loop stopped");

    } else if (c == 'I' || c == '8') {
      loopMode = (loopMode == 2) ? 0 : 2;
      if (loopMode == 2) { f8Phase = 0; f8TickMs = 10; }
      Serial.println(loopMode == 2 ? "infinity loop START" : "loop stopped");

    } else if (c == 'J') {
      if (v == 0) {
        diagAxis = 0;
        loopMode = 0;                     // also stop infinity/line loops
        targetX = posX; targetY = posY;   // no jump back to an old target
        Serial.println("diag stopped");
      } else if (v == 1) startDiag(1, false);
      else if (v == 2) startDiag(2, false);
      else if (v == 3) startDiag(1, true);
      else if (v == 4) startDiag(2, true);
      else if (v == 5) startDiag(3, false);   // both axes, slow, parallel
      else if (v == 6) startDiag(3, true);    // both axes, fast, parallel
      else if (v == 7) { loopMode = 2; f8Phase = 0; f8TickMs = 40; Serial.println("J7: infinity SLOW"); }
      else if (v == 8) { loopMode = 2; f8Phase = 0; f8TickMs = 3;  Serial.println("J8: infinity FAST"); }
    } else if (c == 'Q') {
      report(Serial);
    } else if (c == 'H' || c == '?') {
      printHelp(Serial);
    }
  }
}

// ---------- setup / loop ----------
void setup() {
  Serial.begin(115200);
  Serial1.begin(115200);
  Serial.setTimeout(20);
  Serial1.setTimeout(20);

  pinMode(PIN_LASER, OUTPUT);
  digitalWrite(PIN_LASER, LOW);

  servoX.attach(PIN_X);
  servoY.attach(PIN_Y);
  servoX.writeMicroseconds(degToUs((float)posX));
  servoY.writeMicroseconds(degToUs((float)posY));

  report(Serial);              // laser starts OFF; use O to arm
  printHelp(Serial);
}

void loop() {
  handleLink();
  handleUsb();

  unsigned long now = millis();

  if (now - lastDrive >= DRIVE_MS) {   // sub-degree output, independent of target rate
    driveServos();
    lastDrive = now;
  }

  // feedback only when state changed, and at most every 100ms
  static int repX = -999, repY = -999;
  static bool repL = true;
  if (diagAxis == 0 && now - lastReport >= REPORT_MS &&
      (posX != repX || posY != repY || laserState != repL)) {
    report(Serial);
    repX = posX; repY = posY; repL = laserState;
    lastReport = now;
  }

  if (diagAxis != 0) {             // single-axis smooth sweep overrides normal motion
    serviceDiag();
    return;
  }

  if (restPhase != 0) {
    if (now - lastStep >= (unsigned long)STEP_MS) {
      serviceRest();
      lastStep = now;
    }
    return;
  }

  serviceWatchdog();

  if (loopMode != 0 && !atRest) {
    unsigned long loopTick = (loopMode == 2) ? f8TickMs : (unsigned long)STEP_MS;
    if (now - lastStep >= loopTick) {
      if (loopMode == 1) stepLine();
      else stepInfinity();
      lastStep = now;
    }
    if (loopMode == 1) {
      if (posX == loopTgtX && posY == loopTgtY) {
        if (now - lastHold >= 900) {
          if (loopTgtX == X_WORK_MIN && loopTgtY == Y_MIN) {
            loopTgtX = X_WORK_MAX; loopTgtY = Y_MAX;
          } else {
            loopTgtX = X_WORK_MIN; loopTgtY = Y_MIN;
          }
          lastHold = now;
        }
      } else {
        lastHold = now;
      }
    }
    return;
  }

  if (!atRest && now - lastStep >= (unsigned long)STEP_MS) {
    stepToTarget();
    lastStep = now;
  }
}
