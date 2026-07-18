# Development tools

## SSC device simulator

`ssc_simulator.py` emulates a Neumann KH speaker over the Sennheiser Sound
Control Protocol, so the integration can be exercised end to end without
physical hardware.

```bash
python tools/ssc_simulator.py --model "KH 120 II"
python tools/ssc_simulator.py --model "KH 750" --port 8046
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--model` | `KH 120 II` | `KH 120 II` or `KH 750` |
| `--host` | `::1` | Bind address (IPv6 loopback) |
| `--port` | `8045` | TCP port |
| `--enable-schema` | off | Answer `osc/schema` / `osc/limits` instead of rejecting them |
| `--verbose` | off | Log every request and response |

Run several instances on different ports to simulate multiple devices, for
example a stereo pair plus a subwoofer.

### Why port 8045 and `::1`

Ports below 1024 require root on Linux, and the config flow accepts any port
from 1 to 65535. `::1` is a valid IPv6 address but not link-local, so no
network interface has to be selected during setup.

### Fidelity

The simulator reproduces the behaviour verified against real hardware rather
than what the khtool metadata advertises. Real devices reject considerably more
than the metadata suggests, and a permissive simulator would make the
integration look healthy while it is broken against real speakers.

- Only single leaf paths are answered; collective and container queries are
  rejected with `400`.
- Fields confirmed read-only reject a write with `405`, per model.
- Paths a model does not have return `404` — for example `dimm` on the
  KH 120 II.
- The KH 750 reports its product name as `KH 750`, without the `DSP` suffix.
- `osc/schema` and `osc/limits` are rejected with `400` unless
  `--enable-schema` is passed.
- Malformed JSON lines are ignored, matching the client's behaviour.

`tests/test_simulator.py` covers these restrictions.

## Home Assistant test environment

Home Assistant refuses to start on native Windows (`Home Assistant only
supports Linux, OSX and Windows using WSL`), so a running instance needs WSL2
or a Linux host. The setup is machine-wide rather than project-specific and is
therefore not part of this repository.

The test suite is Linux-only for a related reason:
`pytest-homeassistant-custom-component` imports `homeassistant.runner` at
collection time, which imports the Unix-only `fcntl` module. Run `pytest` under
WSL2 or in CI, not on native Windows.

Point the Home Assistant instance at a running simulator: add the integration,
choose manual setup, and enter host `::1` with the simulator's port. Leave the
interface field empty — it is only needed for link-local addresses.

Where to start the simulator when Home Assistant runs under WSL2 depends on the
WSL networking mode:

- With the default `NAT` mode WSL has its own network namespace, so its `::1` is
  not the Windows loopback. Start the simulator **inside** WSL.
- With `mirrored` mode WSL shares the host interfaces and loopback, so either
  side works. Link-local addresses to real devices are reachable from WSL too.

The simulator only uses the standard library, so the distribution's `python3` is
enough; a Windows virtualenv cannot be used from WSL either way.
