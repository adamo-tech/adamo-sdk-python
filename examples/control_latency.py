"""Measure control-channel RTT through the Adamo Zenoh network.

Run two copies of this script, one on each side of the link you want to
measure:

    # Against the cloud router (includes WAN latency):
    python control_latency.py --role echo --name robot-1
    python control_latency.py --role ping --name viewer --target robot-1

    # Pure SDK software latency (peer-to-peer on localhost, no router):
    python control_latency.py --role echo --name robot-1 --peer
    python control_latency.py --role ping --name viewer --target robot-1 --peer

Each ping carries a local timestamp; the echo side copies the payload
straight back. RTT = (echo-received time) − (ping-sent time), with no
clock sync required.

Messages travel as ``put``s with ``priority=REAL_TIME`` + express, which
is how real teleop control would travel — so the number you see is
representative of a joystick-command round trip.
"""
from __future__ import annotations

import argparse
import json
import statistics
import struct
import time
from threading import Event

import zenoh

import adamo


def open_peer_session() -> zenoh.Session:
    """Open a pure peer-to-peer Zenoh session on localhost.

    No API fetch, no cloud router. Both peers discover each other via
    multicast scouting on the loopback interface — this measures only
    the SDK + Zenoh framing overhead, with the network being one local
    UDP hop.
    """
    conf = zenoh.Config()
    conf.insert_json5("mode", json.dumps("peer"))
    # Listen on any free UDP/TCP port on loopback; scouting finds the peer.
    conf.insert_json5(
        "listen/endpoints",
        json.dumps(["udp/127.0.0.1:0", "tcp/127.0.0.1:0"]),
    )
    conf.insert_json5("scouting/multicast/enabled", json.dumps(True))
    conf.insert_json5("scouting/gossip/enabled", json.dumps(True))
    conf.insert_json5("transport/unicast/lowlatency", json.dumps(True))
    # lowlatency mode requires QoS disabled on both sides
    conf.insert_json5("transport/unicast/qos/enabled", json.dumps(False))
    return zenoh.open(conf)


def run_echo(zsession: zenoh.Session, self_key: str, peer_key: str, stop: Event) -> None:
    """Subscribe to inbound pings, echo the payload back immediately."""
    pub = zsession.declare_publisher(
        peer_key,
        priority=zenoh.Priority.REAL_TIME,
        congestion_control=zenoh.CongestionControl.DROP,
        express=True,
    )

    def on_ping(sample: zenoh.Sample):
        pub.put(bytes(sample.payload))

    sub = zsession.declare_subscriber(self_key, on_ping)

    print(f"echo: listening on {self_key}  →  replying on {peer_key}")
    try:
        stop.wait()
    finally:
        sub.undeclare()
        pub.undeclare()


def run_ping(
    zsession: zenoh.Session,
    self_key: str,
    peer_key: str,
    stop: Event,
    count: int,
    interval: float,
    warmup: int,
) -> None:
    """Emit timestamped pings, subscribe to echoes, compute RTT."""
    samples: list[float] = []
    pending: dict[int, float] = {}
    done = Event()

    def on_pong(sample: zenoh.Sample):
        now = time.perf_counter()
        if len(sample.payload) < 12:
            return
        seq, t_send = struct.unpack_from("<Qd", bytes(sample.payload))
        sent = pending.pop(seq, None)
        if sent is None:
            return
        rtt_ms = (now - sent) * 1000.0
        samples.append(rtt_ms)
        if seq >= warmup:
            print(f"  seq={seq:>4d}  rtt={rtt_ms:7.3f} ms")
        if len(samples) >= count + warmup:
            done.set()

    sub = zsession.declare_subscriber(peer_key, on_pong)
    pub = zsession.declare_publisher(
        self_key,
        priority=zenoh.Priority.REAL_TIME,
        congestion_control=zenoh.CongestionControl.DROP,
        express=True,
    )

    print(f"ping: sending {count} pings (+ {warmup} warmup) to {self_key}")
    time.sleep(0.2)  # let subscriber settle

    try:
        for seq in range(count + warmup):
            if stop.is_set():
                break
            t_send = time.perf_counter()
            pending[seq] = t_send
            pub.put(struct.pack("<Qd", seq, t_send))
            # Wait the rest of the interval
            wake = t_send + interval
            while True:
                remaining = wake - time.perf_counter()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, 0.005))
        # wait up to 2s for the remaining echoes to arrive
        done.wait(timeout=2.0)
    finally:
        sub.undeclare()
        pub.undeclare()

    useful = samples[warmup:] if len(samples) > warmup else samples
    if not useful:
        print("no RTT samples — check the echo side is running")
        return

    useful.sort()
    p50 = statistics.median(useful)
    p95 = useful[int(len(useful) * 0.95) - 1] if len(useful) >= 20 else max(useful)
    p99 = useful[int(len(useful) * 0.99) - 1] if len(useful) >= 100 else max(useful)
    print(
        f"\nRTT over {len(useful)} samples:\n"
        f"  min   {min(useful):7.3f} ms\n"
        f"  p50   {p50:7.3f} ms\n"
        f"  p95   {p95:7.3f} ms\n"
        f"  p99   {p99:7.3f} ms\n"
        f"  max   {max(useful):7.3f} ms\n"
        f"  mean  {statistics.mean(useful):7.3f} ms\n"
        f"  stdev {statistics.stdev(useful) if len(useful) > 1 else 0.0:7.3f} ms\n"
        f"\nOne-way ≈ half of RTT (≈ {p50/2:.3f} ms at p50)."
    )


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--api-key", default="ak_2M3T7rqPYGubJO2gBsxRoWswKn83z0L6")
    p.add_argument("--role", choices=("ping", "echo"), required=True)
    p.add_argument("--name", required=True, help="this participant's name")
    p.add_argument("--target", help="peer name (required for --role=ping)")
    p.add_argument("--count", type=int, default=500)
    p.add_argument("--hz", type=float, default=100.0, help="ping rate in Hz")
    p.add_argument("--warmup", type=int, default=20)
    p.add_argument("--protocol", default="udp", choices=("udp", "quic", "tcp"))
    p.add_argument(
        "--peer",
        action="store_true",
        help="Bypass the cloud router — open peer-to-peer on localhost. "
             "Measures pure SDK/Zenoh software overhead.",
    )
    args = p.parse_args()

    if args.role == "ping" and not args.target:
        p.error("--target required for --role=ping")

    if args.peer:
        zsession = open_peer_session()
        org = "local"
        print(f"PEER mode (loopback multicast) — no router, no cloud")
    else:
        adamo_session = adamo.connect(api_key=args.api_key, protocol=args.protocol)
        zsession = adamo_session.zenoh
        org = adamo_session.org
        print(f"CLOUD mode — connected to org '{org}' via {args.protocol}")

    # Keys are scoped under the participant's own name
    if args.role == "echo":
        self_key = f"{args.name}/latency/ping"
        peer_key = f"{args.name}/latency/pong"
    else:
        peer_key = f"{args.target}/latency/pong"
        # The echo side listens on its own name, so we target it:
        self_key = f"{args.target}/latency/ping"

    # Both modes agree on a common prefix so ping and echo sides see the same keys
    prefix = f"adamo/{org}/"
    self_full = prefix + self_key
    peer_full = prefix + peer_key

    stop = Event()

    try:
        if args.role == "echo":
            run_echo(zsession, self_full, peer_full, stop)
        else:
            run_ping(
                zsession, self_full, peer_full, stop,
                count=args.count,
                interval=1.0 / args.hz,
                warmup=args.warmup,
            )
    except KeyboardInterrupt:
        print("\nstopping")
    finally:
        stop.set()
        zsession.close()


if __name__ == "__main__":
    main()
