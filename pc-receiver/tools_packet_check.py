import socket
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import receiver

r = receiver.Receiver(0, True, 10.0)          # console 模式：不创建虚拟手柄
r.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
r.status = "test"
r.running = True

c = bytearray(20)
c[0] = ord("X")
btn = 4105                      # A + X + LB
c[1] = (btn >> 8) & 0xFF
c[2] = btn & 0xFF
c[3] = 3                        # hat = 右下
for i, f in enumerate((100, -50, 20, 0, 128, 200)):
    c[4 + i] = f & 0xFF
ts = 1234567890123
for i in range(8):
    c[10 + i] = (ts >> (56 - 8 * i)) & 0xFF
c[18] = 0
c[19] = 9                       # srtt
r.handle_data(bytes(c), ("192.168.42.2", 40000))
print("紧凑包 → packet_count=%d invalid=%d format=%s" % (r.packet_count, r.invalid_count, r.packet_format))
print("state:", r.prev)

# JSON 仍然要能用（老接收端 / prefs compact=false）
j = b'{"t":"state","buttons":4105,"hat":3,"lx":100,"ly":-50,"rx":20,"ry":0,"lt":128,"rt":200,"srtt":9,"ts":1234567890123}'
r.handle_data(j, ("192.168.42.2", 40000))
print("JSON 包 → packet_count=%d invalid=%d format=%s" % (r.packet_count, r.invalid_count, r.packet_format))

# ping（只有 ping 时界面也要能看到来源）
r.handle_data(b'{"t":"ping","ts":123}', ("192.168.42.2", 40000))
print("ping → ping_count=%d source=%s" % (r.ping_count, r.last_sender))
r.sock.close()
