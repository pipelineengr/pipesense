"""Functions to generate signal values continuously for all five variables in the channel"""
import math, random, time


def _t() -> float:
    return time.monotonic()


def flow_value(
    setpoint: float = 280.0,
    amplitude: float = 15.0,
    period_s: float = 120.0,
    noise: float = 2.0,
) -> float:
    """A simple sin wave, centered around a pre-defined setpoint to simulate typical operational flow variations at stations"""
    sine_component = amplitude * math.sin(2 * math.pi * _t() / period_s)
    noise_component = random.gauss(0, noise)
    result = setpoint + sine_component + noise_component

    # [SIM] Additional print statement to see how the three components of flow reading.
    # Shows how setpoint + sine + noise combine into the final value.
    # print(f"[SIM] flow: setpoint={setpoint:.1f} sine={sine_component:+.3f} "
    #       f"noise={noise_component:+.3f} → {result:.4f}")

    return result


def pressure_value(
    setpoint: float = 620.0,
    noise: float = 3.5,
) -> float:
    """Pressure sginal with small noise around setpoint. Ideally, pressure would more strongly relate to the flowrate squared
    but for now, we'll keep it as a random"""
    noise_component = random.gauss(0, noise)
    result = setpoint + noise_component

    # [SIM] Print statement to see how pressure is calculated each time.
    # print(f"[SIM] pressure: setpoint={setpoint:.1f} "
    #       f"noise={noise_component:+.3f} → {result:.4f}")

    return result


def temperature_value(
    setpoint: float = 18.0,
    drift_period_s: float = 600.0,
    amplitude: float = 2.0,
    noise: float = 0.3,
) -> float:
    """Slow sinusoidal movement, depicting ambient temperature changes through the day"""
    drift = amplitude * math.sin(2 * math.pi * _t() / drift_period_s)
    noise_component = random.gauss(0, noise)
    result = setpoint + drift + noise_component

    # print(f"[SIM] temperature: setpoint={setpoint:.1f} "
    #       f"drift={drift:+.4f} noise={noise_component:+.4f} → {result:.4f}")

    return result


def level_value(
    setpoint: float = 5.5,
    noise: float = 0.05,
) -> float:
    """Tank level — slow random walk around a setpoint, simulating how it would be when the tank is drained or filled"""
    raw = setpoint + random.gauss(0, noise)
    result = max(0.5, min(9.8, raw))

    # print(f"[SIM] level: raw={raw:.4f} clamped={result:.4f} "
    #       f"(limits: 0.5–9.8)")

    return result


def vibration_value(
    baseline: float = 2.1,
    noise: float = 0.4,
) -> float:
    """Pump vibration — normally distributed around baseline."""
    result = max(0.0, baseline + random.gauss(0, noise))

    # [SIM] Uncomment to see vibration values — max(0.0) prevents negatives.
    # print(f"[SIM] vibration: baseline={baseline:.1f} → {result:.4f}")

    return result


CHANNEL_SIMULATORS = {
    "flow":        flow_value,
    "pressure":    pressure_value,
    "temperature": temperature_value,
    "level":       level_value,
    "vibration":   vibration_value,
}

# [SIM] Uncomment to see the simulator registry at import time.
# print(f"[SIM] CHANNEL_SIMULATORS registered: {list(CHANNEL_SIMULATORS.keys())}")