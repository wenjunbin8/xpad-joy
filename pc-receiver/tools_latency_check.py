import sys, time
sys.path.insert(0, r"D:\project\实训\xpad-joy\pc-receiver")
import receiver

j = b'{"t":"state","buttons":1029,"hat":8,"lx":-128,"ly":0,"rx":127,"ry":0,"lt":128,"rt":200,"rtt":12,"srtt":9,"ts":1234567890123}'

c = bytearray(20)
c[0] = ord("X")
btn = 1029
c[1] = (btn >> 8) & 0xFF
c[2] = btn & 0xFF
c[3] = 8
for i, f in enumerate((-128, 0, 127, 0, 128, 200)):
    c[4 + i] = f & 0xFF
ts = 1234567890123
for i in range(8):
    c[10 + i] = (ts >> (56 - 8 * i)) & 0xFF
c[18] = 9
c[19] = 0
c = bytes(c)

parsed = receiver.parse_compact(c)
assert parsed is not None and parsed[0] == receiver.parse_state(j), parsed

n = 20000
t0 = time.perf_counter()
for _ in range(n):
    receiver.parse_state(j)
t1 = time.perf_counter()
for _ in range(n):
    receiver.parse_compact(c)
t2 = time.perf_counter()

print("包大小: JSON %d B, 紧凑 %d B" % (len(j), len(c)))
print("JSON 解析: %.3f us/包" % ((t1 - t0) / n * 1e6))
print("紧凑包解析: %.3f us/包" % ((t2 - t1) / n * 1e6))

# 本地回环：手机→电脑这一段用 loopback 量，看纯软件下限
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.bind(("127.0.0.1", 0))
p = s.getsockname()
best = None
for _ in range(2000):
    t0 = time.perf_counter()
    s.sendto(c, p)
    data, _ = s.recvfrom(256)
    r = (time.perf_counter() - t0) * 1000.0
    if best is None or r < best:
        best = r
print("本机回环 UDP 往返 min: %.3f ms（这是软件路径的下限）" % best)
s.close()
