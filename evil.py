#!/usr/bin/env python3
"""
Local-only TCP control-handler security test for the SCADA simulator.

Default target is 127.0.0.1:21000. It sends malformed/unknown commands first.
A valid GEN ON command is sent only if the operator explicitly confirms.
Use only with your own local simulator.
"""
import socket

HOST = "127.0.0.1" #directs test to this computer
PORT = 21000 #TCP port used by the simulator's control handler.
TIMEOUT_SECONDS = 3 #Prevent a connection attempt from hanging indefinitely.


def send_test(label, payload):
    # Show exactly which bytes are being sent for each test case.
    print(f"\n[{label}] Sending {payload!r}")
    try:
        # Open a fresh TCP connection for this command and close it afterward.
        with socket.create_connection((HOST, PORT), timeout=TIMEOUT_SECONDS) as sock:
            sock.settimeout(TIMEOUT_SECONDS)
            # Send the command exactly as provided by the caller.
            sock.sendall(payload)
            # The current handler does not send replies; closing ends the test.
        print("Connection completed. Check the outstation PowerShell window for logs.")
    except OSError as exc:
        # Connection errors commonly mean the simulator is not running/listening.
        print(f"Connection failed: {exc}")
        print("Confirm the simulator is running and listening on port 21000.")


def main():
    print(f"Testing only {HOST}:{PORT}")
    print("Run this only against your own local SCADA simulator.")

    # These malformed/unknown inputs are intended to test validation without
    # requesting a valid equipment-state change.
    # These should not change generator or breaker state.
    send_test("Try password", b"AUTH test\n")
    send_test("try gen on", b"GEN ON\n")
    send_test("Unknown command", b"BOGUS TEST\n")
    send_test("Missing action", b"GEN\n")
    send_test("Invalid generator action", b"GEN MAYBE\n")
    send_test("Invalid breaker action", b"BRK MAYBE\n")
    send_test("Extra arguments", b"GEN ON EXTRA\n")

    # Check the simulator's own log and GUI; a successful TCP send alone does
    # not tell us whether the handler accepted or rejected the command.
    print("\nReview the simulator log and verify that none of the tests above")
    print("changed generator or breaker state. Note: the current handler logs")
    print("unknown commands, but silently ignores several invalid forms.")

    # This is the only test below that intentionally sends a valid control.
    # It can turn on the simulated generator, so require explicit confirmation.
    confirm = input(
        "\nOptional authorization check: send 'GEN ON' to the local simulator? "
        "This WILL change the simulated generator state. Type YES to continue: "
    ).strip()

    if confirm == "YES":
        # Tests whether a valid command is accepted without credentials/session data.
        send_test("Unauthenticated valid control test", b"GEN ON\n")
        print(
            "If the generator turns on without credentials or a session token, "
            "the TCP control interface currently accepts unauthenticated control."
        )
    else:
        print("Skipped valid control test; no intended state change was requested.")


if __name__ == "__main__":
    # Run the tests only when this file is executed directly.
    main()
