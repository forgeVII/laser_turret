/*
  HISTORICAL TEST SKETCH - OLD GEOMETRY (centre X80 Y75, rest at 180).
  Do not flash on the current turret; use firmware/turret_main instead.
  Current build: centre X100 Y80, limits X50..150 Y40..140, no rest.

  Center both servos, switch the laser ON, and run test loops.

  X (pan / laser) -> PA1 : centre 80, range 0..180
  Y (tilt)        -> PA0 : centre 75
  Laser           -> PA2 : HIGH = ON (1kR -> BC547 base, low-side switch)

  SAFETY ENVELOPE (components around the mechanism):
    - Y never below 30
    - Y above 130 ONLY when X == 180
    - moving X away from 180 first pulls Y back to 130

  Serial (115200 baud, newline terminated):
    C        centre (X80, Y75) + laser ON
    O        laser ON
    F        laser OFF
    X<n>     set X angle
    Y<n>     set Y angle
    S        safe rest: X180 first, then Y180
    L        toggle STRAIGHT loop (X0/Y30 <-> X180/Y130)
    I  or 8  toggle INFINITY / figure-8 loop
    H        help

  Angles are tracked in plain variables - this core's Servo.read() is buggy.
*/
#include <Servo.h>

Servo servoX;   // PA1 - pan / laser
Servo servoY;   // PA0 - tilt

const int LASER_PIN = PA2;
const int CENTRE_X  = 80;
const int CENTRE_Y  = 75;

const int Y_MIN       = 30;    // never below this
const int Y_MAX_SAFE  = 130;   // max unless X is folded away at 180
const int Y_MAX_FOLD  = 180;   // allowed only when X == 180

// ---- straight loop ----
const int LOOP_X_A = 0;        // pan left,  tilt up
const int LOOP_Y_A = 30;
const int LOOP_X_B = 180;      // pan right (folded), tilt down to safe max
const int LOOP_Y_B = 130;
const int STEP_MS  = 25;       // ms per 1 degree
const unsigned long HOLD_MS = 900;  // pause at each end

// ---- infinity / figure-8 ----
// x = X_C + X_A*sin(t)   -> 0..180
// y = Y_C + Y_A*sin(2t)  -> 30..120 (stays clear of the 40-50 zone)
const int F8_X_C = 90;
const int F8_X_A = 90;
const int F8_Y_C = 75;
const int F8_Y_A = 45;
const int F8_STEPS = 360;      // points per full infinity
const int F8_STEP_MS = 25;     // ms per point -> ~9s per figure-8
const float F8_TAU = 6.28318530718f;

// loopMode: 0 = off, 1 = straight, 2 = infinity
int loopMode = 0;

int posX = CENTRE_X;
int posY = CENTRE_Y;

int loopTargetX = CENTRE_X;
int loopTargetY = CENTRE_Y;
unsigned long lastStep = 0;
unsigned long lastHold = 0;
int f8Phase = 0;

void show() {
  Serial.print("X=");
  Serial.print(posX);
  Serial.print("  Y=");
  Serial.print(posY);
  Serial.print("  LASER=");
  Serial.println(digitalRead(LASER_PIN) ? "ON" : "OFF");
}

void help() {
  Serial.println("--- laser center ---");
  Serial.println("C centre+laser ON   O laser ON   F laser OFF");
  Serial.println("X<n> Y<n> set angle   S safe rest   H help");
  Serial.println("L straight loop   I (or 8) infinity loop");
  Serial.println("Y limits 30..130 (180 only at X=180)");
}

int limitY(int requested) {
  int hi = (posX == 180) ? Y_MAX_FOLD : Y_MAX_SAFE;
  return constrain(requested, Y_MIN, hi);
}

void setX(int a) {
  int newX = constrain(a, 0, 180);
  if (newX != 180 && posY > Y_MAX_SAFE) {
    posY = Y_MAX_SAFE;
    servoY.write(posY);
  }
  posX = newX;
  servoX.write(posX);
  show();
}

void setY(int a) {
  posY = limitY(a);
  servoY.write(posY);
  show();
}

void laserOn()  { digitalWrite(LASER_PIN, HIGH); show(); }
void laserOff() { digitalWrite(LASER_PIN, LOW);  show(); }

void centre() {
  posX = CENTRE_X;
  posY = CENTRE_Y;
  servoX.write(posX);
  servoY.write(posY);
  digitalWrite(LASER_PIN, HIGH);
  show();
}

void safeRest() {
  posX = 180;
  servoX.write(posX);
  show();
  delay(800);
  posY = 180;
  servoY.write(posY);
  show();
}

// one 1-degree step toward the straight-loop target
void stepStraight() {
  if (posX < loopTargetX) { posX++; servoX.write(posX); }
  else if (posX > loopTargetX) { posX--; servoX.write(posX); }

  int hi = (posX == 180) ? Y_MAX_FOLD : Y_MAX_SAFE;
  int wanted = constrain(posY, Y_MIN, hi);
  if (wanted < loopTargetY) wanted++;
  else if (wanted > loopTargetY) wanted--;
  wanted = constrain(wanted, Y_MIN, hi);
  if (wanted != posY) { posY = wanted; servoY.write(posY); }

  show();
}

// advance one point on the figure-8 (Lissajous 1:2)
void stepInfinity() {
  float t = (float)f8Phase * F8_TAU / (float)F8_STEPS;
  int nx = F8_X_C + (int)(F8_X_A * sin(t)  + 0.5f);
  int ny = F8_Y_C + (int)(F8_Y_A * sin(2.0f * t) + 0.5f);

  nx = constrain(nx, 0, 180);
  ny = constrain(ny, Y_MIN, Y_MAX_SAFE);   // infinity stays in the safe arc

  posX = nx; servoX.write(posX);
  posY = ny; servoY.write(posY);

  f8Phase++;
  if (f8Phase >= F8_STEPS) f8Phase = 0;
  show();
}

void setup() {
  Serial.begin(115200);
  pinMode(LASER_PIN, OUTPUT);
  digitalWrite(LASER_PIN, LOW);
  servoX.attach(PA1);
  servoY.attach(PA0);
  centre();
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
      loopMode = (loopMode == 1) ? 0 : 1;
      if (loopMode == 1) {
        loopTargetX = posX;
        loopTargetY = posY;
        lastStep = millis();
        lastHold = millis();
      }
      Serial.println(loopMode == 1 ? "straight loop START" : "loop stopped");
    } else if (c == 'I' || c == '8') {
      loopMode = (loopMode == 2) ? 0 : 2;
      if (loopMode == 2) {
        f8Phase = 0;
        lastStep = millis();
      }
      Serial.println(loopMode == 2 ? "infinity loop START" : "loop stopped");
    } else if (c == 'C') {
      loopMode = 0; centre();
    } else if (c == 'O') {
      laserOn();
    } else if (c == 'F') {
      laserOff();
    } else if (c == 'X') {
      loopMode = 0; setX(v);
    } else if (c == 'Y') {
      loopMode = 0; setY(v);
    } else if (c == 'S') {
      loopMode = 0; safeRest();
    } else if (c == 'H' || c == '?') {
      help();
    }
  }

  unsigned long now = millis();

  if (loopMode == 1) {
    if (now - lastStep >= (unsigned long)STEP_MS) {
      stepStraight();
      lastStep = now;
    }
    if (posX == loopTargetX && posY == loopTargetY) {
      if (now - lastHold >= HOLD_MS) {
        if (loopTargetX == LOOP_X_A && loopTargetY == LOOP_Y_A) {
          loopTargetX = LOOP_X_B;
          loopTargetY = LOOP_Y_B;
        } else {
          loopTargetX = LOOP_X_A;
          loopTargetY = LOOP_Y_A;
        }
        lastHold = now;
      }
    } else {
      lastHold = now;
    }
  } else if (loopMode == 2) {
    if (now - lastStep >= (unsigned long)F8_STEP_MS) {
      stepInfinity();
      lastStep = now;
    }
  }
}
