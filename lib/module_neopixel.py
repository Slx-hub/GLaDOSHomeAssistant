import serial
import time

def send_rgb_command(indices, r, g, b, w, deciseconds):
    ser.write(bytes([indices,r,g,b,w,deciseconds]))

ser = serial.Serial(
    port='/dev/ttyACM0',
    baudrate=9600
)

if not ser.isOpen():
    ser.open()

print("arduino is up an running!")
send_rgb_command(0b00000001, 3, 15, 0, 0, 20)
time.sleep(0.1)
send_rgb_command(0b00000010, 3, 15, 0, 0, 20)
time.sleep(0.1)
send_rgb_command(0b00000100, 3, 15, 0, 0, 20)
time.sleep(0.1)
send_rgb_command(0b00001000, 3, 15, 0, 0, 20)
time.sleep(0.1)
send_rgb_command(0b00010000, 3, 15, 0, 0, 20)
time.sleep(0.1)
send_rgb_command(0b00100000, 3, 15, 0, 0, 20)
time.sleep(0.1)
send_rgb_command(0b01000000, 3, 15, 0, 0, 20)
time.sleep(0.5)
send_rgb_command(0b00101010, 20, 5, 0, 0, 30)
time.sleep(2)
send_rgb_command(0b00101010, 8, 30, 0, 0, 1)
