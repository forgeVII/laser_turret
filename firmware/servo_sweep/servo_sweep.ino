/*
  Servo auto-sweep test - NO serial needed.
  Both servos sweep 0..180..0 continuously from boot.

  X (pan)  -> PA1 (180=right/rest, 0=left)
  Y (tilt) -> PA0 (180=down/rest, 0=up)

  If a servo is powered + grounded + on the right pin, it WILL move.
*/
#include <Servo.h>

Servo servoX;
Servo servoY;

void setup() {
  servoX.attach(PA1);
  servoY.attach(PA0);
}

void loop() {
  for (int a = 0; a <= 180; a += 5) {
    servoX.write(a);
    servoY.write(a);
    delay(50);
  }
  for (int a = 180; a >= 0; a -= 5) {
    servoX.write(a);
    servoY.write(a);
    delay(50);
  }
}
