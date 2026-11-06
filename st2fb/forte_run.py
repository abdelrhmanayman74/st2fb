"""Run a Basic FB on real FORTE and record a trace.

    python3 -m st2fb.forte_run --fbt build/X/X.fbt --stimulus corpus/X/stimulus.json --out build/X/forte.json

Three steps:
1. Export the .fbt to C++ and compile it into FORTE inside the base image (docker/forte.Dockerfile).
   Only one file recompiles. The resulting binary is cached under build/forte_cache by content hash.
2. Boot that FORTE in a network-less container with this application:

       SERVER.IND -> SEQ.CU, SEQ.CUO -> DUT.REQ, DUT.CNF -> SERVER.RSP
       SERVER.RD_i -> DUT.<input>, DUT.<output> -> SERVER.SD_i, SEQ.CV -> SERVER.SD_last

   SERVER is FORTE's own IEC 61499 communication FB speaking FBDK ASN.1 over TCP on loopback.
3. Inside that container (the --inner mode of this file), send one request frame per scan and block
   on the reply. A scan's data goes in with the frame; the outputs come back after DUT's CNF.

Why this is synchronous and deterministic: one event chain thread runs IND -> REQ -> CNF -> RSP, and
the next frame is only sent once the reply for this one has arrived. No wall clock is read by the FB;
SCAN_DT is data. An ECC runs to completion before any event it emitted is delivered, so every RSP of
a scan samples the same final outputs.

SEQ (FORTE's E_CTU, counting IND) exists for FBs that emit CNF more than once per REQ: the surplus
replies carry the same count as the first and are discarded, so they cannot shift later scans.
A REQ that never emits CNF hits the scan timeout and the run fails.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from xml.sax.saxutils import escape

from . import export_forte, fbt

IMAGE = "st2fb-forte:efcd63c"
REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "docker" / "forte.Dockerfile"
CACHE_DIR = REPO_ROOT / "build" / "forte_cache"
RUN_DIR = REPO_ROOT / "build" / "forte_run"

SERVER_PORT = 61500  # Inside the container's own network namespace, so it cannot collide.
STARTUP_TIMEOUT_S = 15.0
MAX_SCANS = 65535  # SEQ is a UINT counter.

# FBDK ASN.1 as implemented in core/src/cominfra/fbdkasn1layer.cpp: one tag byte, then the value in
# big-endian. BOOL has no value; its tag is the value. TIME is a 64-bit count of microseconds.
BOOL_FALSE_TAG, BOOL_TRUE_TAG = 64, 65
WIRE_FORMAT = {"INT": (67, ">h"), "DINT": (68, ">i"), "UINT": (71, ">H"), "REAL": (74, ">f"), "TIME": (76, ">q")}
SEQ_TYPE = "UINT"


class RunError(RuntimeError):
    pass


# Host side


def build_plan(fb: fbt.FBType, stimulus: dict) -> dict:
    """Check the FB and stimulus against the contract and return everything the driver needs."""
    req = next((e for e in fb.event_inputs if e.name == "REQ"), None)
    cnf = next((e for e in fb.event_outputs if e.name == "CNF"), None)
    if req is None or cnf is None:
        raise RunError("the FB must have event input REQ and event output CNF")
    missing = {v.name for v in fb.input_vars} - set(req.with_vars)
    if missing:
        raise RunError(f"REQ must carry every data input; missing With for {sorted(missing)}")
    missing = {v.name for v in fb.output_vars} - set(cnf.with_vars)
    if missing:
        raise RunError(f"CNF must carry every data output; missing With for {sorted(missing)}")
    for var in fb.input_vars + fb.output_vars:
        if var.type not in fbt.V1_TYPES:
            raise RunError(f"{var.name}: type {var.type} is outside the v1 subset")

    scan_ms = stimulus.get("scan_ms")
    scans = stimulus.get("scans")
    if not isinstance(scan_ms, int) or isinstance(scan_ms, bool) or scan_ms <= 0:
        raise RunError(f"stimulus scan_ms must be a positive integer, got {scan_ms!r}")
    if not isinstance(scans, list):
        raise RunError("stimulus scans must be a list")
    if len(scans) > MAX_SCANS:
        raise RunError(f"at most {MAX_SCANS} scans are supported, got {len(scans)}")

    declared = {v.name for v in fb.input_vars}
    plan_scans = []
    for index, scan in enumerate(scans):
        values = {k: v for k, v in scan.items() if k != "SCAN_DT"}
        if "SCAN_DT" in declared:
            values["SCAN_DT"] = scan_ms
        unknown = set(values) - declared
        absent = declared - set(values)
        if unknown or absent:
            raise RunError(f"scan {index}: unknown inputs {sorted(unknown)}, missing inputs {sorted(absent)}")
        for var in fb.input_vars:
            encode_value(var.type, values[var.name], f"scan {index}: {var.name}")
        plan_scans.append(values)

    return {
        "scan_ms": scan_ms,
        "inputs": [[v.name, v.type] for v in fb.input_vars],
        "outputs": [[v.name, v.type] for v in fb.output_vars],
        "scans": plan_scans,
    }


def boot_file(fb: fbt.FBType) -> str:
    """The FORTE boot file: one management command per line, `<resource>;<request>`."""
    # SERVER_<SD count>_<RD count>; see CCommFB::createInterfaceSpec. SD carries the replies.
    server = f"iec61499::net::SERVER_{len(fb.output_vars) + 1}_{len(fb.input_vars)}"
    server_id = f'"fbdk[].ip[127.0.0.1:{SERVER_PORT}]"'
    requests = [
        ("", '<FB Name="EMB_RES" Type="iec61499::system::EMB_RES"/>', "CREATE"),
        ("EMB_RES", f'<FB Name="DUT" Type="{export_forte.NAMESPACE}::{fb.name}"/>', "CREATE"),
        ("EMB_RES", f'<FB Name="SERVER" Type="{server}"/>', "CREATE"),
        ("EMB_RES", '<FB Name="SEQ" Type="iec61499::events::E_CTU"/>', "CREATE"),
    ]

    def connect(source: str, destination: str) -> None:
        requests.append(("EMB_RES", f'<Connection Source="{source}" Destination="{destination}"/>', "CREATE"))

    def write(value: str, destination: str) -> None:
        source = escape(value, {'"': "&quot;"})
        requests.append(("EMB_RES", f'<Connection Source="{source}" Destination="{destination}"/>', "WRITE"))

    write("TRUE", "SERVER.QI")
    write(server_id, "SERVER.ID")
    write("65535", "SEQ.PV")
    connect("START.COLD", "SERVER.INIT")
    connect("START.WARM", "SERVER.INIT")
    connect("SERVER.IND", "SEQ.CU")
    connect("SEQ.CUO", "DUT.REQ")
    connect("DUT.CNF", "SERVER.RSP")
    for index, var in enumerate(fb.input_vars, start=1):
        connect(f"SERVER.RD_{index}", f"DUT.{var.name}")
    for index, var in enumerate(fb.output_vars, start=1):
        connect(f"DUT.{var.name}", f"SERVER.SD_{index}")
    connect("SEQ.CV", f"SERVER.SD_{len(fb.output_vars) + 1}")
    requests.append(("EMB_RES", None, "START"))

    lines = []
    for number, (resource, body, action) in enumerate(requests, start=1):
        request = f'<Request ID="{number}" Action="{action}"'
        request += f">{body}</Request>" if body else "/>"
        lines.append(f"{resource};{request}")
    return "\n".join(lines) + "\n"


def docker(*args: str, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(["docker", *args], text=True, **kwargs)


def ensure_image() -> str:
    """Return the image id, building the base image the first time (about ten minutes)."""
    inspect = docker("image", "inspect", "-f", "{{.Id}}", IMAGE, capture_output=True)
    if inspect.returncode != 0:
        print(f"forte_run: building {IMAGE}, this takes about ten minutes", file=sys.stderr)
        built = docker("build", "-f", str(DOCKERFILE), "-t", IMAGE, str(DOCKERFILE.parent))
        if built.returncode != 0:
            raise RunError("docker build failed")
        inspect = docker("image", "inspect", "-f", "{{.Id}}", IMAGE, capture_output=True, check=True)
    return inspect.stdout.strip()


def compile_fb(fb: fbt.FBType, image_id: str) -> Path:
    """Compile the FB into FORTE, reusing an earlier build of identical C++ on the same image."""
    files = export_forte.export_fb(fb)
    digest = hashlib.sha256(image_id.encode())
    for name in sorted(files):
        digest.update(name.encode())
        digest.update(files[name].encode())
    target = CACHE_DIR / digest.hexdigest()[:16]
    if (target / "forte").exists():
        return target

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="tmp-", dir=CACHE_DIR))
    try:
        for name, content in files.items():
            (work / name).write_text(content, encoding="utf-8")
        # Root inside the container, because the build tree in the image belongs to root; the
        # binary handed back belongs to the caller.
        script = (
            f"cp /work/{fb.name}_fbt.cpp /forte/modules/st2fb/fb.cpp"
            f" && cp /work/{fb.name}_fbt.h /forte/modules/st2fb/"
            " && ninja -C /forte/build forte"
            f" && install -o {os.getuid()} -g {os.getgid()} -m 755 /forte/build/forte /work/forte"
        )
        result = docker(
            "run", "--rm", "--network", "none", "-v", f"{work}:/work", IMAGE, "sh", "-c", script,
            capture_output=True,
        )
        if result.returncode != 0:
            raise RunError(f"compiling {fb.name} into FORTE failed:\n{result.stdout}\n{result.stderr}")
        work.chmod(0o755)
        try:
            work.rename(target)
        except OSError:  # A concurrent run built the same FB first; its copy is equally good.
            shutil.rmtree(work)
        return target
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def run_in_container(binary_dir: Path, plan: dict, boot: str, out: Path, scan_timeout: float) -> None:
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=RUN_DIR))
    try:
        (run / "plan.json").write_text(json.dumps({**plan, "scan_timeout": scan_timeout}), encoding="utf-8")
        (run / "boot.fboot").write_text(boot, encoding="utf-8")
        result = docker(
            "run", "--rm", "--user", f"{os.getuid()}:{os.getgid()}", "--network", "none",
            "-v", f"{binary_dir}:/fb:ro",
            "-v", f"{run}:/run_dir",
            "-v", f"{REPO_ROOT / 'st2fb'}:/app/st2fb:ro",
            "-w", "/app",
            IMAGE,
            "/usr/bin/python3", "-B", "-m", "st2fb.forte_run", "--inner", "/run_dir",
        )
        log = run / "forte.log"
        if log.exists():
            shutil.copyfile(log, out.with_name(out.name + ".log"))
        if result.returncode != 0:
            raise RunError(f"the FORTE run failed; see {out.name}.log next to the output")
        os.replace(run / "trace.json", out)
    finally:
        shutil.rmtree(run, ignore_errors=True)


# Container side


def encode_value(type_name: str, value, context: str) -> bytes:
    """One data point as FBDK ASN.1. TIME values are integer milliseconds in the stimulus."""
    if type_name == "BOOL":
        if not isinstance(value, bool):
            raise RunError(f"{context}: expected a JSON bool, got {value!r}")
        return bytes([BOOL_TRUE_TAG if value else BOOL_FALSE_TAG])
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RunError(f"{context}: expected a number, got {value!r}")
    tag, layout = WIRE_FORMAT[type_name]
    if type_name != "REAL":
        if value != int(value):
            raise RunError(f"{context}: expected an integer, got {value!r}")
        value = int(value) * 1000 if type_name == "TIME" else int(value)
    try:
        return bytes([tag]) + struct.pack(layout, value)
    except (struct.error, OverflowError) as exc:
        raise RunError(f"{context}: {value!r} does not fit {type_name}") from exc


class _Reader:
    """Buffered socket reader; the deadline covers one whole scan."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buffer = b""
        self.deadline = 0.0

    def exactly(self, count: int) -> bytes:
        while len(self.buffer) < count:
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            self.sock.settimeout(remaining)
            chunk = self.sock.recv(4096)
            if not chunk:
                raise RunError("FORTE closed the connection")
            self.buffer += chunk
        data, self.buffer = self.buffer[:count], self.buffer[count:]
        return data

    def value(self, type_name: str):
        tag = self.exactly(1)[0]
        if type_name == "BOOL":
            if tag not in (BOOL_FALSE_TAG, BOOL_TRUE_TAG):
                raise RunError(f"expected a BOOL tag, got {tag}")
            return tag == BOOL_TRUE_TAG
        expected, layout = WIRE_FORMAT[type_name]
        if tag != expected:
            raise RunError(f"expected {type_name} tag {expected}, got {tag}")
        value = struct.unpack(layout, self.exactly(struct.calcsize(layout)))[0]
        return value // 1000 if type_name == "TIME" else value


def connect_with_retry(forte: subprocess.Popen) -> socket.socket:
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while True:
        if forte.poll() is not None:
            raise RunError(f"FORTE exited during startup with code {forte.returncode}")
        try:
            sock = socket.create_connection(("127.0.0.1", SERVER_PORT), timeout=1.0)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return sock
        except OSError:
            if time.monotonic() > deadline:
                raise RunError(f"FORTE did not open port {SERVER_PORT} within {STARTUP_TIMEOUT_S} s")
            time.sleep(0.02)


def drive(sock: socket.socket, plan: dict) -> dict:
    reader = _Reader(sock)
    records = []
    for index, values in enumerate(plan["scans"]):
        frame = b"".join(encode_value(t, values[n], n) for n, t in plan["inputs"])
        # A server with no data inputs is triggered by any one-byte frame (the ASN.1 NULL tag).
        sock.sendall(frame or b"\x05")
        reader.deadline = time.monotonic() + plan["scan_timeout"]
        try:
            while True:
                outputs = {n: reader.value(t) for n, t in plan["outputs"]}
                sequence = reader.value(SEQ_TYPE)
                if sequence == index + 1:
                    break
                if sequence != index:  # Equal to index: surplus CNF of the previous scan.
                    raise RunError(f"scan {index}: reply for sequence {sequence}, expected {index + 1}")
        except TimeoutError:
            raise RunError(f"scan {index}: no CNF within {plan['scan_timeout']} s") from None
        records.append({"t_ms": index * plan["scan_ms"], **outputs})
    return {
        "source": "forte",
        "scan_ms": plan["scan_ms"],
        "outputs": [n for n, _ in plan["outputs"]],
        "scans": records,
    }


def inner_main(run_dir: Path) -> int:
    plan = json.loads((run_dir / "plan.json").read_text(encoding="utf-8"))
    with open(run_dir / "forte.log", "wb") as log:
        forte = subprocess.Popen(
            ["/fb/forte", "-f", str(run_dir / "boot.fboot")], stdout=log, stderr=subprocess.STDOUT
        )
        try:
            sock = connect_with_retry(forte)
            with sock:
                trace = drive(sock, plan)
        except (RunError, OSError) as exc:
            print(f"forte_run: {exc}", file=sys.stderr)
            return 1
        finally:
            forte.kill()
            forte.wait()
    text = json.dumps(trace, indent=2, allow_nan=False) + "\n"
    (run_dir / "trace.json").write_text(text, encoding="utf-8")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a Basic FB on real FORTE and write a trace")
    parser.add_argument("--fbt", type=Path)
    parser.add_argument("--stimulus", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--scan-timeout", type=float, default=5.0, help="seconds to wait for CNF in one scan")
    parser.add_argument("--inner", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.inner:
        return inner_main(args.inner)
    if not (args.fbt and args.stimulus and args.out):
        parser.error("--fbt, --stimulus and --out are required")

    # A stale trace from an earlier run must not survive a failed one.
    args.out.unlink(missing_ok=True)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        fb = fbt.read_fbt(args.fbt)
        plan = build_plan(fb, json.loads(args.stimulus.read_text(encoding="utf-8")))
        binary_dir = compile_fb(fb, ensure_image())
        run_in_container(binary_dir, plan, boot_file(fb), args.out.resolve(), args.scan_timeout)
    except (OSError, ValueError, RunError) as exc:
        print(f"forte_run: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
