# hw_simulator

Lightweight, high-fidelity-ish hardware simulator for IntelliHeal.

## Purpose
- Emulate an FPGA-based board with tiles/PR regions, spares, telemetry and partial reconfiguration timing.
- Speak a simple HAL protocol (newline-delimited JSON over TCP) expected by the self-healing software.

## How to run
From the project root (where `hw_simulator` directory resides):

python simulator_cli.py --host 127.0.0.1 --port 9000 --tiles 16 --spares 3 --hb 0.1
