import serial
import time

def send_rgb_command(indices, r, g, b, w, deciseconds):
    ser.write(bytes([indices,r,g,b,w,deciseconds]))

ser = serial.Serial(
    # by-id path: stable across boots regardless of USB enumeration order.
    # Contains the board's serial number, a replacement XIAO needs a new entry.
    port='/dev/serial/by-id/usb-Seeed_Seeed_XIAO_M0_D27D9F9850583234352E3120FF0F0E24-if00',
    baudrate=9600
)

if not ser.isOpen():
    ser.open()

print("arduino is up an running!")
send_rgb_command(255, 255, 255, 255, 255, 255)
time.sleep(0.1)
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
