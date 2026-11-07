"""Runs in a container on the field network, at the plant's address. Replays one stimulus into the simulated I/O.

Each scan's field inputs go out over the UDP field link every 100 ms of wall time. ACK is written to the coil.
Setpoints are written once by Modbus. Standard library only.
"""
import json
import socket
import struct
import sys
import time

REMOTE_IO = "172.30.1.20"


def modbus_request(sock, pdu, tid=[0]):
    tid[0] = (tid[0] + 1) & 0xFFFF
    sock.sendall(struct.pack(">HHHB", tid[0], 0, len(pdu) + 1, 1) + pdu)
    header = sock.recv(7)
    length = struct.unpack(">H", header[4:6])[0]
    return sock.recv(length - 1)


def real_words(value):
    return struct.pack(">f", value)


def main():
    scans = json.load(open(sys.argv[1]))["scans"]
    period = json.load(open(sys.argv[1]))["scan_ms"] / 1000.0
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def send_field(scan):
        message = "S {:.5f} {:.3f} {} {} {} {} {}".format(
            scan["RAW_LEVEL"], scan["FLOW"], int(scan["FB_1"]), int(scan["FB_2"]), int(scan["TRIP_1"]), int(scan["TRIP_2"]), int(scan["AUTO_MODE"]))
        udp.sendto(message.encode(), (REMOTE_IO, 5020))

    # Hold the first inputs until the controller has had time to start and take the lease.
    idle = dict(scans[0], AUTO_MODE=False, RAW_LEVEL=0.5, FLOW=0.0)
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        send_field(idle)
        time.sleep(0.02)
    tcp = socket.create_connection((REMOTE_IO, 502), timeout=2)
    tcp.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    first = scans[0]
    payload = b"".join(real_words(first[n]) for n in ("STOP_LEVEL", "START_LEVEL", "LAG_LEVEL", "HIGH_LEVEL"))
    modbus_request(tcp, struct.pack(">BHHB", 16, 100, 8, 16) + payload)
    print(f"playing {len(scans)} scans", flush=True)
    time.sleep(float(sys.argv[2]) / 1000.0 if len(sys.argv) > 2 else 0.0)
    start_ns = time.monotonic_ns()
    next_t = time.monotonic()
    ack = False
    late = 0
    for scan in scans:
        send_field(scan)
        if scan["ACK"] != ack:
            ack = scan["ACK"]
            modbus_request(tcp, struct.pack(">BHH", 5, 0, 0xFF00 if ack else 0))
        next_t += period
        sleep = next_t - time.monotonic()
        if sleep > 0:
            time.sleep(sleep)
        else:
            late += 1
    print("done " + json.dumps({"t_start_ns": start_ns, "t_end_ns": time.monotonic_ns(), "late_slots": late}), flush=True)


if __name__ == "__main__":
    main()
