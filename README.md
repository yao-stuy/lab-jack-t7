# LabJack T7 — Viam Sensor Module

A Viam **sensor** module for the [LabJack T7](https://labjack.com/products/t7)
multifunction DAQ. It reads calibrated voltages on any of the 14 analog inputs
(AIN0–AIN13) over USB or Ethernet, and exposes the T7's full register map
(analog outputs, digital I/O, device temperature) through `DoCommand`.

- **Model:** `yao-chen:labjack-t7:labjack-t7`
- **API:** `rdk:component:sensor`

This is a **registry module**: you build it once, upload it to the Viam registry,
and any machine that lists it in its config downloads and runs it automatically —
add it as a config block on any machine, no files copied by hand.

Unlike the sibling ADS1115 (I2C) and MCP3008 (SPI) modules, the T7 is a complete
instrument reached through LabJack's cross-platform **LJM** driver. LJM speaks the
device's register map and returns already-calibrated volts, so there's no
bit-banging here — the module opens a device handle and reads named registers.

---

## Connection & the LJM driver

The host machine (a Pi, an x86 box, etc.) talks to the T7 over **USB**
(plug-and-play), **Ethernet** (give the T7's IP), or **WiFi** (T7-Pro).

The native **LJM library** (`libLabJackM.so`) must be present on the host. The
`labjack-ljm` pip package bundled into the binary is only a thin ctypes wrapper
around it. The module's `first_run.sh` attempts to download and install LJM
automatically the first time it's deployed to a machine; if your distro/arch
isn't covered, install it manually from
<https://labjack.com/support/software/installers/ljm> — then the module just
works.

---

## Configuration

Add the component to a machine after the module is configured (see below). All
attributes are optional; the defaults open the first T7 found over any transport
and read AIN0 at ±10 V.

```json
{
  "connection_type": "USB",
  "identifier": "ANY",
  "active_channels": [0, 1, 2],
  "voltage_range": 10.0,
  "resolution_index": 0,
  "settling_us": 0
}
```

| Attribute          | Type   | Default | Notes |
|--------------------|--------|---------|-------|
| `connection_type`  | string | `"ANY"` | `"USB"`, `"ETHERNET"`, `"WIFI"`, `"TCP"`, or `"ANY"` |
| `identifier`       | string | `"ANY"` | Serial number, IP address, or device name; `"ANY"` = first found |
| `device_type`      | string | `"T7"`  | `"T7"` or `"ANY"` |
| `active_channels`  | list   | `[0]`   | AIN channels to read, 0–13 |
| `voltage_range`    | float  | `10.0`  | ± full-scale volts applied to every active channel: `10.0`, `1.0`, `0.1`, `0.01`. Smaller range = more resolution on small signals |
| `resolution_index` | int    | `0`     | 0–12. 0 = LJM default; higher = slower, lower-noise conversions |
| `settling_us`      | float  | `0`     | Analog settling time (µs). 0 = auto; raise for high source impedance |

### Readings

`GetReadings()` returns one `channel_N_voltage` (calibrated float volts) per
active channel, plus three diagnostics:

```json
{
  "channel_0_voltage": 2.0481,
  "channel_1_voltage": 0.0032,
  "board_sample_rate_hz": 920.4,
  "viam_reading_rate_hz": 5.0,
  "samples_per_reading": 2
}
```

- `board_sample_rate_hz` — AIN samples/sec the T7 achieved this reading (hardware rate).
- `viam_reading_rate_hz` — how often viam-server is calling `GetReadings` (your poll/capture rate). 0 on the first call.
- `samples_per_reading` — channels read this reading.

### DoCommand

The T7 is more than an ADC, so `DoCommand` exposes its whole register map:

```jsonc
{ "read_channel": 5 }                                 // → { "channel": 5, "voltage": 1.999 }
{ "read_name": "TEMPERATURE_DEVICE_K" }               // → { "name": ..., "value": 298.7 }
{ "write_name": { "name": "DAC0", "value": 2.5 } }    // set analog output DAC0 to 2.5 V
```

---

## Repo layout

```
lab-jack/
├── meta.json                  # registry metadata + build steps (setup/build/first_run/arch)
├── run.sh                     # entrypoint: builds the venv on first launch, runs the module
├── setup.sh                   # creates venv, installs requirements.txt
├── build.sh                   # packages the source into dist/archive.tar.gz
├── first_run.sh               # installs the native LJM driver on the machine, once
├── requirements.txt           # viam-sdk, labjack-ljm
├── src/
│   ├── main.py                # Module.run_from_registry()
│   └── models/labjack_t7.py   # the sensor model
└── .github/workflows/deploy.yml   # cloud build + publish on version tags
```

`meta.json` declares the build pipeline. `entrypoint` is `run.sh`. Unlike the
sibling ADS1115/MCP3008 modules, this one ships **source, not a PyInstaller
binary**: the `labjack-ljm` wrapper `ctypes`-loads the native `libLabJackM.so`
driver at runtime, which doesn't survive freezing. So `run.sh` builds a venv from
`requirements.txt` on the machine at first launch — the machine therefore needs
**Python 3.10+ and internet** the first time it starts the module (plus the LJM
system driver, which `first_run.sh` installs).

---

## Prerequisites (once)

```bash
# Install / update the Viam CLI, then log in
viam login

# Confirm your org namespace is "yao-chen" (the namespace in meta.json must match an org you own)
viam organizations list
```

If you use a different org, update the namespace in `meta.json` (`module_id` and
each `models[].model`), in `src/models/labjack_t7.py` (the `MODEL` triple), and in
`.viam-gen-info`.

---

## One-time: register the module in the registry

This creates the registry entry that `module_id` points at. Run from the module dir:

```bash
# create it first if it doesn't exist:
viam module create --name labjack-t7 --public-namespace yao-chen

viam module update --module meta.json
```

---

## Development loop — hot reload (`viam module reload`)

Use this while iterating. It builds the module **on the target machine**, syncs
the new binary into the running `viam-server`, and restarts just the module — no
manual upload, no machine restart.

```bash
# Find your machine's part id:  viam machines list   (or copy from the app)
viam module reload --part-id <PART_ID>

# then watch it come up
viam machines part logs --tail
```

Edit `src/models/labjack_t7.py`, `viam module reload --part-id <PART_ID>` again,
re-check the logs. That's the whole dev rhythm.

> Reload builds for the architecture of the machine you reload onto. This module
> ships `linux/arm64` and `linux/amd64` — reload onto a matching part.

---

## Release — publish to the registry for production

**A. Cloud build via GitHub Actions (recommended).** `deploy.yml` runs Viam's
build-action on a tag and publishes `linux/arm64` + `linux/amd64` builds. Set the
repo secrets `viam_key_id` and `viam_key_value` (an org API key from
`viam organizations api-key create`), then:

```bash
git tag v0.1.0
git push origin v0.1.0
```

**B. Cloud build from the CLI** (no GitHub needed):

```bash
viam module build start --version 0.1.0      # builds in Viam's infra
viam module build logs --wait                # follow the build
```

---

## Use it on a machine (add it as a config block)

Once a version is published, add the module + component to any machine's config
(Viam app → **CONFIGURE** → **+** → **Modular resource** → search `labjack`), or
edit the raw JSON:

```json
{
  "modules": [
    {
      "type": "registry",
      "name": "labjack-t7",
      "module_id": "yao-chen:labjack-t7",
      "version": "0.1.0"
    }
  ],
  "components": [
    {
      "name": "daq",
      "api": "rdk:component:sensor",
      "model": "yao-chen:labjack-t7:labjack-t7",
      "attributes": { "connection_type": "USB", "active_channels": [0, 1], "voltage_range": 10.0 }
    }
  ]
}
```

`viam-server` downloads the module from the registry and runs it — nothing lives
on the host by hand except the LJM driver (installed by `first_run.sh`). Pin a
specific `version` for production; use `"latest"` only while developing.

---

## Local smoke test (optional, on the host with a T7 attached)

```bash
./setup.sh
sudo ./first_run.sh              # install the LJM driver if needed
venv/bin/python src/main.py      # runs as a module; Ctrl-C to stop
```
