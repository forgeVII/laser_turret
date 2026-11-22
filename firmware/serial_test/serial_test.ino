// Minimal USB-serial sanity test for the Blue Pill.
// Prints ALIVE every 500ms and echoes anything received.
void setup() {
  Serial.begin(115200);
}

void loop() {
  Serial.println("ALIVE");
  if (Serial.available()) {
    String s = Serial.readStringUntil('\n');
    Serial.print("GOT:");
    Serial.println(s);
  }
  delay(500);
}
