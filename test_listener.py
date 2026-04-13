# test_listener.py — Run on your Windows host to verify Node A is sending packets
# Usage: python test_listener.py
#
# This binds to UDP port 5001 and prints every packet received from Node A.
# Use this BEFORE building Node B to make sure the VxSim networking works.

import socket
import struct
import time

NODE_B_IP = "0.0.0.0"         # Listen on all host interfaces for VxSim NAT
NODE_B_PORT = 5001

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((NODE_B_IP, NODE_B_PORT))
sock.settimeout(5.0)  # 5 second timeout for debugging

print(f"Listening on {NODE_B_IP}:{NODE_B_PORT}...")
print(f"Waiting for packets from Node A (VxSim instance 0)...\n")

last_seq = -1
last_time = time.time()
packet_count = 0

try:
    while True:
        try:
            data, addr = sock.recvfrom(65536)
        except socket.timeout:
            print("  (no packet received in 5s — is Node A running?)")
            continue

        now = time.time()

        # Parse header: [seq_num: 4B uint32][timestamp: 8B uint64]
        if len(data) < 12:
            print(f"  WARNING: short packet ({len(data)} bytes) from {addr}")
            continue

        seq_num = struct.unpack("<I", data[0:4])[0]
        timestamp_us = struct.unpack("<Q", data[4:12])[0]
        audio_bytes = len(data) - 12
        audio_samples = audio_bytes // 2  # 16-bit samples

        # Check for dropped packets
        gap = ""
        if last_seq >= 0 and seq_num != last_seq + 1:
            missed = seq_num - last_seq - 1
            gap = f" *** MISSED {missed} PACKETS ***"

        # Inter-packet interval
        interval_ms = (now - last_time) * 1000

        print(f"  Packet #{seq_num:>5d} | ts={timestamp_us:>14d} us | "
              f"{audio_samples:>6d} samples | interval={interval_ms:>6.1f}ms | "
              f"from {addr[0]}{gap}")

        last_seq = seq_num
        last_time = now
        packet_count += 1

except KeyboardInterrupt:
    print(f"\n\nReceived {packet_count} packets total.")
    print("Listener stopped.")
finally:
    sock.close()
