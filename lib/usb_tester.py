import serial
import time

if __name__ == '__main__':
    ser = serial.Serial("COM3", 9600, timeout=0)
    time.sleep(0.1)   # Wait for Arduino to reset and init serial
    ser.write(bytes([127, 5, 5, 20, 0, 20]))