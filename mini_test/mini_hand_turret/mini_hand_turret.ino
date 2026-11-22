#include <ESP32Servo.h>

Servo myservo;
const int SERVO_PIN = 18;
const int LASER_PIN = 4;
const int LED_PIN = 2;

bool attached = false;

void setup() {
  Serial.begin(115200);
  pinMode(LASER_PIN, OUTPUT);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LASER_PIN, LOW);
  digitalWrite(LED_PIN, LOW);
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.startsWith("S")) {
      int angle = cmd.substring(1).toInt();
      angle = constrain(angle, 0, 180);
      if (!attached) {
        myservo.attach(SERVO_PIN);
        attached = true;
      }
      myservo.write(angle);
      digitalWrite(LASER_PIN, HIGH);
      digitalWrite(LED_PIN, HIGH);
    } else if (cmd == "F") {
      myservo.detach();
      attached = false;
      digitalWrite(LASER_PIN, LOW);
      digitalWrite(LED_PIN, LOW);
    }
  }
  delay(5);
}