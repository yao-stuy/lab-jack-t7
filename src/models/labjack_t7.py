"""
LabJack T7 — Viam Sensor Model
================================
Multifunction DAQ (14 analog inputs, 2 analog outputs, 23 digital I/O) read
over USB / Ethernet / WiFi via LabJack's LJM library.

Unlike a raw ADC chip (ADS1115 / MCP3008 over I2C/SPI), the T7 is a complete
instrument reached through the cross-platform **LJM** driver. LJM speaks the
device's Modbus register map for us and returns *already-calibrated volts*, so
there is no per-chip bit-twiddling here — we open a device handle and read named
registers such as "AIN0".

Connection
----------
  The host machine (Pi, x86 box, etc.) connects to the T7 over:
    USB       — plug-and-play, no config
    ETHERNET  — give the T7's IP as `identifier`
    WIFI      — T7-Pro only

  The LJM native library must be installed on the host (see README / first_run).
  The `labjack-ljm` pip package is only a thin wrapper around it.

Readings returned by get_readings()
--------------------------------------
  "channel_N_voltage": float  calibrated volts on AIN N (already scaled by LJM)
  ... one per channel listed in active_channels

  Plus three diagnostics every reading:
  "board_sample_rate_hz": float  AIN samples/sec the T7 achieved this reading
                                  (channels ÷ time spent reading). Hardware rate.
  "viam_reading_rate_hz":  float  how often viam-server is calling get_readings,
                                  i.e. your data-capture / poll rate. 0 on the
                                  first call (no interval yet). Viam's rate.
  "samples_per_reading":   int    channels read this reading.

Configuration attributes (set in app.viam CONFIGURE tab)
----------------------------------------------------------
  connection_type   str    "ANY" (default), "USB", "ETHERNET", "WIFI", "TCP"
  identifier        str    "ANY" (default), or serial number / IP / device name
  device_type       str    "T7" (default); "ANY" also works
  active_channels   list   AIN channels to read, e.g. [0,1,2]. Default [0]. 0–13.
  voltage_range     float  ± full-scale range applied to every active channel:
                             10.0 (default), 1.0, 0.1, 0.01. Smaller range =
                             more resolution on small signals.
  resolution_index  int    0–12. 0 (default) = LJM's default. Higher = slower,
                             lower-noise conversions (more effective bits).
  settling_us       float  Analog settling time in microseconds. 0 (default) =
                             auto. Raise for high source impedance.
"""

from __future__ import annotations

import threading
import time
from typing import Any, ClassVar, Dict, Mapping, Optional, Sequence, Tuple

from typing_extensions import Self
from viam.components.sensor import Sensor
from viam.proto.app.robot import ComponentConfig
from viam.proto.common import Geometry, ResourceName
from viam.resource.base import ResourceBase
from viam.resource.easy_resource import EasyResource
from viam.resource.types import Model, ModelFamily
from viam.utils import SensorReading, ValueTypes


# ── Constants ──────────────────────────────────────────────────────────────────

DEFAULT_CONNECTION_TYPE = "ANY"    # let LJM pick USB/Ethernet/WiFi
DEFAULT_IDENTIFIER      = "ANY"    # first device found
DEFAULT_DEVICE_TYPE     = "T7"
DEFAULT_VOLTAGE_RANGE   = 10.0     # ±10 V, the T7's widest AIN range
DEFAULT_RESOLUTION_INDEX = 0       # 0 = LJM default
DEFAULT_SETTLING_US     = 0.0      # 0 = auto

NUM_AIN_CHANNELS = 14              # T7 has AIN0–AIN13
VALID_RANGES     = (10.0, 1.0, 0.1, 0.01)   # ±V full-scale options
MAX_RESOLUTION_INDEX = 12          # T7 resolution index range is 0–12

VALID_CONNECTION_TYPES = ("ANY", "USB", "ETHERNET", "WIFI", "TCP")


# ── LJM helper ─────────────────────────────────────────────────────────────────

class _LabJackT7:
    """
    Thin wrapper over an LJM device handle.

    Opens one connection to the T7, applies per-channel AIN range / resolution /
    settling once, and reads all active channels in a single batched call.
    """

    def __init__(
        self,
        connection_type: str,
        identifier: str,
        device_type: str,
        active_channels: list[int],
        voltage_range: float,
        resolution_index: int,
        settling_us: float,
    ):
        try:
            from labjack import ljm
        except ImportError as exc:
            raise ImportError(
                "labjack-ljm not installed, or the LJM native library is "
                "missing. Install the LJM installer from labjack.com and "
                "`pip install labjack-ljm`."
            ) from exc

        self._ljm = ljm

        # LJM's own calls are thread-safe per handle, but we still serialize the
        # configure/read sequences so concurrent get_readings callers (live view
        # + data capture + SDK clients) don't interleave on the shared handle.
        self._lock = threading.Lock()

        # openS takes string names for device/connection/identifier.
        self._handle = ljm.openS(device_type, connection_type, identifier)

        info = ljm.getHandleInfo(self._handle)
        # info = (deviceType, connectionType, serialNumber, ipAddr, port, maxBytesPerMB)
        self.serial_number = info[2]
        self.ip_address = ljm.numberToIP(info[3]) if info[3] else ""

        self._channels = active_channels

        # Apply AIN configuration to every active channel in one batched write.
        names: list[str] = []
        values: list[float] = []
        for ch in active_channels:
            names.append(f"AIN{ch}_RANGE")
            values.append(float(voltage_range))
            names.append(f"AIN{ch}_RESOLUTION_INDEX")
            values.append(float(resolution_index))
            names.append(f"AIN{ch}_SETTLING_US")
            values.append(float(settling_us))
        if names:
            ljm.eWriteNames(self._handle, len(names), names, values)

        # Precompute the register names read every cycle.
        self._read_names = [f"AIN{ch}" for ch in active_channels]

    def read_channels(self) -> list[float]:
        """Read all active AIN channels in one batched call; returns volts."""
        with self._lock:
            return self._ljm.eReadNames(
                self._handle, len(self._read_names), self._read_names
            )

    def read_name(self, name: str) -> float:
        """Read one arbitrary named register (e.g. 'AIN5', 'TEMPERATURE_DEVICE_K')."""
        with self._lock:
            return self._ljm.eReadName(self._handle, name)

    def write_name(self, name: str, value: float) -> None:
        """Write one named register (e.g. 'DAC0' = 2.5 to set an analog output)."""
        with self._lock:
            self._ljm.eWriteName(self._handle, name, float(value))

    def close(self):
        try:
            self._ljm.close(self._handle)
        except Exception:
            pass


# ── Viam Sensor Model ───────────────────────────────────────────────────────────

class LabJackT7(Sensor, EasyResource):
    """
    Viam sensor model for the LabJack T7 multifunction DAQ.

    Registry model triple:  yao-chen:labjack-t7:labjack-t7
    """

    MODEL: ClassVar[Model] = Model(
        ModelFamily("yao-chen", "labjack-t7"), "labjack-t7"
    )

    _dev: _LabJackT7 | None
    _active_channels: list[int]
    _last_read_ts: Optional[float]   # perf_counter() of the previous get_readings

    # ── Config validation (called before new()) ─────────────────────────────

    @classmethod
    def validate_config(
        cls, config: ComponentConfig
    ) -> Tuple[Sequence[str], Sequence[str]]:
        """
        Viam calls this before creating the resource. Raise with a clear message
        on bad config. Returns (required_deps, optional_deps) — empty here.
        """
        fields = config.attributes.fields

        if "connection_type" in fields:
            ct = fields["connection_type"].string_value.upper()
            if ct not in VALID_CONNECTION_TYPES:
                raise ValueError(
                    f"'connection_type' must be one of {list(VALID_CONNECTION_TYPES)}, "
                    f"got '{ct}'"
                )

        if "active_channels" in fields:
            for v in fields["active_channels"].list_value.values:
                ch = int(v.number_value)
                if not (0 <= ch < NUM_AIN_CHANNELS):
                    raise ValueError(
                        f"Each value in 'active_channels' must be 0–{NUM_AIN_CHANNELS - 1}, "
                        f"got {ch}. The T7 has analog inputs AIN0–AIN13."
                    )

        if "voltage_range" in fields:
            vr = fields["voltage_range"].number_value
            if vr not in VALID_RANGES:
                raise ValueError(
                    f"'voltage_range' must be one of {list(VALID_RANGES)} (±V), got {vr}"
                )

        if "resolution_index" in fields:
            ri = int(fields["resolution_index"].number_value)
            if not (0 <= ri <= MAX_RESOLUTION_INDEX):
                raise ValueError(
                    f"'resolution_index' must be 0–{MAX_RESOLUTION_INDEX}, got {ri}. "
                    f"0 = LJM default; higher = slower, lower-noise."
                )

        if "settling_us" in fields:
            su = fields["settling_us"].number_value
            if su < 0:
                raise ValueError(f"'settling_us' must be >= 0, got {su}")

        return [], []  # No component dependencies

    # ── Constructor ──────────────────────────────────────────────────────────

    @classmethod
    def new(
        cls,
        config: ComponentConfig,
        dependencies: Mapping[ResourceName, ResourceBase],
    ) -> Self:
        """
        Called by viam-server when the component is created or reconfigured.
        Reads config, opens the T7 over LJM, applies AIN settings, returns ready.
        """
        sensor = super().new(config, dependencies)
        fields = config.attributes.fields

        connection_type = (
            fields["connection_type"].string_value.upper()
            if "connection_type" in fields else DEFAULT_CONNECTION_TYPE
        )
        identifier = (
            fields["identifier"].string_value
            if "identifier" in fields else DEFAULT_IDENTIFIER
        )
        device_type = (
            fields["device_type"].string_value.upper()
            if "device_type" in fields else DEFAULT_DEVICE_TYPE
        )
        voltage_range = (
            fields["voltage_range"].number_value
            if "voltage_range" in fields else DEFAULT_VOLTAGE_RANGE
        )
        resolution_index = (
            int(fields["resolution_index"].number_value)
            if "resolution_index" in fields else DEFAULT_RESOLUTION_INDEX
        )
        settling_us = (
            fields["settling_us"].number_value
            if "settling_us" in fields else DEFAULT_SETTLING_US
        )

        if "active_channels" in fields:
            sensor._active_channels = sorted({
                int(v.number_value)
                for v in fields["active_channels"].list_value.values
            })
        else:
            sensor._active_channels = [0]

        sensor._last_read_ts = None
        sensor._dev = _LabJackT7(
            connection_type,
            identifier,
            device_type,
            sensor._active_channels,
            voltage_range,
            resolution_index,
            settling_us,
        )

        sensor.logger.info(
            "LabJack T7 ready — serial=%s conn=%s ip=%s channels=%s range=±%sV "
            "resolution_index=%d settling=%.0fus",
            sensor._dev.serial_number, connection_type,
            sensor._dev.ip_address or "n/a", sensor._active_channels,
            voltage_range, resolution_index, settling_us,
        )
        return sensor

    # ── GetReadings ──────────────────────────────────────────────────────────

    async def get_readings(
        self,
        *,
        extra: Optional[Mapping[str, Any]] = None,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Mapping[str, SensorReading]:
        """
        Called by viam-server on every data-capture tick and whenever a client
        calls GetReadings.

        Returns one key per active channel:
          "channel_N_voltage" — float, calibrated volts on AIN N (LJM-scaled)

        Example with active_channels=[0,1]:
          {
            "channel_0_voltage": 2.0481,
            "channel_1_voltage": 0.0032,
            "board_sample_rate_hz": 920.4,
            "viam_reading_rate_hz": 5.0,
            "samples_per_reading": 2
          }
        """
        if self._dev is None:
            raise RuntimeError("LabJack T7 not initialized")

        results: dict[str, SensorReading] = {}

        # Viam reading rate: how often viam-server calls this method (your
        # data-capture / poll frequency), from the gap since the last call.
        now = time.perf_counter()
        if self._last_read_ts is not None and now > self._last_read_ts:
            viam_rate = round(1.0 / (now - self._last_read_ts), 3)
        else:
            viam_rate = 0.0   # first call — no interval yet
        self._last_read_ts = now

        # Board sample rate: AIN samples/sec the T7 achieved over the link during
        # this reading. Time only the conversion work.
        conversions = 0
        read_start = time.perf_counter()
        try:
            volts = self._dev.read_channels()
            for ch, v in zip(self._active_channels, volts):
                results[f"channel_{ch}_voltage"] = round(v, 6)
                conversions += 1
                self.logger.debug("AIN%d: %.6fV", ch, v)
        except Exception as exc:
            self.logger.error("Failed to read T7 channels: %s", exc)
            for ch in self._active_channels:
                results[f"channel_{ch}_voltage"] = -99999.0
        read_elapsed = time.perf_counter() - read_start

        board_rate = round(conversions / read_elapsed, 1) if (read_elapsed > 0 and conversions) else 0.0

        results["board_sample_rate_hz"] = board_rate   # AIN samples/sec the T7 achieved
        results["viam_reading_rate_hz"] = viam_rate     # get_readings calls/sec from viam-server
        results["samples_per_reading"]  = conversions   # channels read this reading

        return results

    # ── do_command — manual reads/writes ─────────────────────────────────────

    async def do_command(
        self,
        command: Mapping[str, ValueTypes],
        *,
        timeout: Optional[float] = None,
        **kwargs,
    ) -> Mapping[str, ValueTypes]:
        """
        Ad-hoc access to the T7's full register map — handy from the Test tab.

          {"read_channel": N}
              Read one AIN channel. → {"channel": N, "voltage": 2.001}

          {"read_name": "TEMPERATURE_DEVICE_K"}
              Read any named register. → {"name": ..., "value": 298.7}

          {"write_name": {"name": "DAC0", "value": 2.5}}
              Write any named register — e.g. set an analog output or DIO.
              → {"name": "DAC0", "wrote": 2.5}
        """
        if self._dev is None:
            raise RuntimeError("LabJack T7 not initialized")

        if "read_channel" in command:
            ch = int(command["read_channel"])
            if not (0 <= ch < NUM_AIN_CHANNELS):
                return {"error": f"channel must be 0–{NUM_AIN_CHANNELS - 1}"}
            voltage = round(self._dev.read_name(f"AIN{ch}"), 6)
            return {"channel": ch, "voltage": voltage}

        if "read_name" in command:
            name = str(command["read_name"])
            return {"name": name, "value": self._dev.read_name(name)}

        if "write_name" in command:
            spec = command["write_name"]
            if not isinstance(spec, Mapping) or "name" not in spec or "value" not in spec:
                return {"error": "write_name requires {'name': str, 'value': number}"}
            name = str(spec["name"])
            value = float(spec["value"])
            self._dev.write_name(name, value)
            return {"name": name, "wrote": value}

        raise NotImplementedError(
            "Supported commands: {'read_channel': int}, {'read_name': str}, "
            "{'write_name': {'name': str, 'value': number}}"
        )

    # ── Lifecycle ────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Called by viam-server when the component is removed or reconfigured."""
        if self._dev is not None:
            try:
                self._dev.close()
                self.logger.info("LabJack T7: connection closed cleanly")
            except Exception as exc:
                self.logger.warning("LabJack T7: error closing connection: %s", exc)
            self._dev = None

    async def get_geometries(
        self,
        *,
        extra: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Sequence[Geometry]:
        raise NotImplementedError()
