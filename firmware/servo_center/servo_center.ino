/*
  HISTORICAL TEST SKETCH - OLD GEOMETRY (centre X80 Y75, rest at 180).
  Do not flash on the current turret; use firmware/turret_main instead.
  Current build: centre X100 Y80, limits X50..150 Y40..140, no rest.

  Servo centering / smooth open-close tool.
  Measured 2026-11-18.

  X (pan / laser) -> PA1 : 180 = right, 0 = left,  centre 80
  Y (tilt)        -> PA0 : 180 = down,  0 = up,    centre 75

  Serial commands (115200 baud):
    X<n> / Y<n> / B<n>  set angle directly
    C                   centre (X80, Y75)
    R                   full fold to rest (X180 then Y180)
    L                   toggle SMOOTH full sweep 0<->180 (both)
    H                   help

  Smooth cycle constants — tune these to taste:
*/
#include <Servo.h>

Servo servoX;   // PA1
Servo servoY;   // PA0

// ---- cycle settings (edit these) ----
const int OPEN_X   = 0;     // full open: X left, Y up
const int OPEN_Y   = 0;
const int CLOSE_X  = 180;   // full close: X right, Y down/flat
const int CLOSE_Y  = 180;
const int STEP_MS  = 25;    // ms per 1 degree (higher = slower/smoother)
const unsigned long HOLD_MS = 300;   // brief pause at each end
// --------------------------------------

int posX = OPEN_X;
int posY = OPEN_Y;
int targetX = OPEN_X;
int targetY = OPEN_Y;

bool smoothCycle = false;
unsigned long lastStep = 0;
unsigned long lastHold = 0;

void show() {
  Serial.print("X=");
  Serial.print(posX);
  Serial.print("  Y=");
  Serial.println(posY);
}

void help() {
  Serial.println("--- servo control ---");
  Serial.println("X<n> Y<n> B<n>   set angle");
  Serial.println("C centre (X80 Y75)   R full fold to rest");
  Serial.println("L smooth open/close cycle   H help");
}

void setX(int a) {
  posX = constrain(a, 0, 180);
  targetX = posX;
  servoX.write(posX);
  show();
}

void setY(int a) {
  posY = constrain(a, 0, 180);
  targetY = posY;
  servoY.write(posY);
  show();
}

void stopCycle() {
  if (smoothCycle) {
    smoothCycle = false;
    Serial.println("cycle stopped");
  }
}

// Move each servo one degree toward its target. Returns true if anything moved.
bool stepToward() {
  bool moved = false;
  if (posX < targetX) { servoX.write(++posX); moved = true; }
  else if (posX > targetX) { servoX.write(--posX); moved = true; }

  if (posY < targetY) { servoY.write(++posY); moved = true; }
  else if (posY > targetY) { servoY.write(--posY); moved = true; }

  if (moved) show();
  return moved;
}

void setup() {
  Serial.begin(115200);
  servoX.attach(PA1);
  servoY.attach(PA0);
  servoX.write(posX);
  servoY.write(posY);
  show();
  help();
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toUpperCase();
    char c = cmd.charAt(0);
    int v = cmd.substring(1).toInt();

    if (c == 'L') {
      smoothCycle = !smoothCycle;
      targetX = posX;
      targetY = posY;
      lastStep = millis();
      lastHold = millis();
      Serial.println(smoothCycle ? "smooth cycle START" : "cycle stopped");
    } else if (c == 'X') {
      stopCycle(); setX(v);
    } else if (c == 'Y') {
      stopCycle(); setY(v);
    } else if (c == 'B') {
      stopCycle(); setX(v); setY(v);
    } else if (c == 'C') {
      stopCycle(); setX(OPEN_X); setY(OPEN_Y);
    } else if (c == 'R') {
      stopCycle(); setX(180); delay(800); setY(180);
    } else if (c == 'H' || c == '?') {
      help();
    }
  }

  if (smoothCycle) {
    unsigned long now = millis();

    if (now - lastStep >= (unsigned long)STEP_MS) {
      stepToward();
      lastStep = now;
    }

    if (posX == targetX && posY == targetY) {
      // arrived - wait, then reverse direction
      if (now - lastHold >= HOLD_MS) {
        if (targetX == OPEN_X && targetY == OPEN_Y) {
          targetX = CLOSE_X;
          targetY = CLOSE_Y;
        } else {
          targetX = OPEN_X;
          targetY = OPEN_Y;
        }
        lastHold = now;
      }
    } else {
      lastHold = now;   // keep resetting while moving
    }
  }
}
