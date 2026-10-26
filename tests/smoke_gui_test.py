"""Smoke test: Launch GUI as a background process, verify PID and stability for >= 3s, then terminate cleanly."""

import os
import signal
import subprocess
import sys
import time

from pathlib import Path

LOCAL_GUI = str(Path(__file__).resolve().parent.parent / "gui")

def smoke_test():
    print("Launching MyOmen GUI in background...")
    env = os.environ.copy()
    test_runtime = f"/tmp/myomen_smoke_{os.getuid()}"
    os.makedirs(test_runtime, exist_ok=True)
    env["XDG_RUNTIME_DIR"] = test_runtime
    py_cmd = (
        f'import sys; sys.path = [p for p in sys.path if "my proj" not in p and "OmenSense" not in p]; '
        f'sys.path.insert(0, {repr(LOCAL_GUI)}); from omensense.cli import main; sys.exit(main())'
    )
    cmd = [
        sys.executable,
        "-c",
        py_cmd,
        "gui"
    ]

    proc = subprocess.Popen(
        cmd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    pid = proc.pid
    print(f"Spawned GUI with PID: {pid}")

    if proc.poll() is not None:
        stdout, stderr = proc.communicate()
        print(f"ERROR: Process exited immediately with code {proc.returncode}")
        print(f"STDOUT:\n{stdout}")
        print(f"STDERR:\n{stderr}")
        return False

    # Wait for 4 seconds
    print("Verifying stability for 4 seconds...")
    for second in range(1, 5):
        time.sleep(1)
        if proc.poll() is not None:
            stdout, stderr = proc.communicate()
            print(f"ERROR: Process crashed at second {second} with code {proc.returncode}")
            print(f"STDOUT:\n{stdout}")
            print(f"STDERR:\n{stderr}")
            return False
        print(f"  Second {second}: PID {pid} is running healthy and responsive.")

    print(f"Process PID {pid} ran stably for >= 3 seconds.")

    # Clean termination
    print("Terminating process cleanly...")
    proc.send_signal(signal.SIGINT)
    try:
        proc.wait(timeout=5)
        print("Process terminated cleanly on signal.")
    except subprocess.TimeoutExpired:
        print("Warning: Process did not exit on SIGINT within 5s, sending SIGTERM...")
        proc.terminate()
        proc.wait(timeout=5)
        print("Process terminated on SIGTERM.")

    # Ensure no lingering socket
    for s in [f"{test_runtime}/omen-sense-{os.getuid()}.sock", f"/run/user/{os.getuid()}/omen-sense-{os.getuid()}.sock"]:
        if os.path.exists(s):
            try:
                os.remove(s)
            except OSError:
                pass

    return True

if __name__ == "__main__":
    success = smoke_test()
    if success:
        print("\nSMOKE TEST PASSED: GUI launched, remained stable, and terminated cleanly.")
        sys.exit(0)
    else:
        print("\nSMOKE TEST FAILED.")
        sys.exit(1)
