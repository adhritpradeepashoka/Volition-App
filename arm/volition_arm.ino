/*
 * Volition - 3-DOF Servo Arm
 * ===========================
 * 3 rotational axes + gripper.
 *
 * Wiring:
 *   Axis 1 (Base)     → Pin 9
 *   Axis 2 (Shoulder) → Pin 10
 *   Axis 3 (Elbow)    → Pin 11
 *   Gripper           → Pin 6
 *
 * Serial commands (9600 baud, newline terminated):
 *   A1:<angle>    Rotate Axis 1 to angle (0–180)
 *   A2:<angle>    Rotate Axis 2 to angle (0–180)
 *   A3:<angle>    Rotate Axis 3 to angle (0–180)
 *   GRIP:OPEN     Open gripper
 *   GRIP:CLOSE    Close gripper
 *   GRIP:TOGGLE   Toggle gripper
 *   RESET         All axes to 90°, grip open
 *   STATUS        Print current state
 */

#include <Servo.h>

Servo axis1, axis2, axis3, gripper;

int a1 = 90, a2 = 90, a3 = 90;
bool gripOpen = true;

const int GRIP_OPEN_DEG  = 0;
const int GRIP_CLOSE_DEG = 90;

// Per-axis limits
const int A1_MIN = 0,  A1_MAX = 180;
const int A2_MIN = 20, A2_MAX = 160;
const int A3_MIN = 10, A3_MAX = 170;

String buf = "";

void setup() {
  Serial.begin(9600);
  axis1.attach(9);
  axis2.attach(10);
  axis3.attach(11);
  gripper.attach(6);
  doReset();
  Serial.println("VOLITION_ARM_READY");
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') { handleCmd(buf); buf = ""; }
    else if (c != '\r') buf += c;
  }
}

void handleCmd(String cmd) {
  cmd.trim(); cmd.toUpperCase();

  if (cmd.startsWith("A1:")) {
    a1 = constrain(cmd.substring(3).toInt(), A1_MIN, A1_MAX);
    axis1.write(a1);
    Serial.println("OK:A1:" + String(a1));

  } else if (cmd.startsWith("A2:")) {
    a2 = constrain(cmd.substring(3).toInt(), A2_MIN, A2_MAX);
    axis2.write(a2);
    Serial.println("OK:A2:" + String(a2));

  } else if (cmd.startsWith("A3:")) {
    a3 = constrain(cmd.substring(3).toInt(), A3_MIN, A3_MAX);
    axis3.write(a3);
    Serial.println("OK:A3:" + String(a3));

  } else if (cmd == "GRIP:OPEN")   { setGrip(true);         }
  else if (cmd == "GRIP:CLOSE")    { setGrip(false);        }
  else if (cmd == "GRIP:TOGGLE")   { setGrip(!gripOpen);    }
  else if (cmd == "RESET")         { doReset();              }
  else if (cmd == "STATUS") {
    Serial.println("A1=" + String(a1) + " A2=" + String(a2) +
                   " A3=" + String(a3) +
                   " GRIP=" + String(gripOpen ? "OPEN" : "CLOSED"));
  } else {
    Serial.println("ERR:UNKNOWN:" + cmd);
  }
}

void setGrip(bool open) {
  gripOpen = open;
  gripper.write(open ? GRIP_OPEN_DEG : GRIP_CLOSE_DEG);
  Serial.println("OK:GRIP:" + String(open ? "OPEN" : "CLOSE"));
}

void doReset() {
  a1 = 90; a2 = 90; a3 = 90; gripOpen = true;
  axis1.write(a1); delay(50);
  axis2.write(a2); delay(50);
  axis3.write(a3); delay(50);
  gripper.write(GRIP_OPEN_DEG);
  Serial.println("OK:RESET");
}
