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

def speed_value() -> float:
    """Compressor shaft speed in RPM — base 3000 RPM with small noise."""
    # [SIM] Simulates a running compressor shaft. Values well below 2800 or above 3200 are anomalous.
    # print(f"[simulate] speed={value:.2f} RPM")
    base  = 3000.0
    noise = random.gauss(0, 15.0)
    value = base + noise
    return round(value, 4)

def discharge_pressure_value() -> float:
    """Compressor discharge pressure in kPa — base 1200 kPa."""
    # [SIM] Downstream pressure after compression. Spike here = blocked outlet or valve issue.
    # print(f"[simulate] discharge_pressure={value:.2f} kPa")
    base  = 1200.0
    noise = random.gauss(0, 20.0)
    value = base + noise
    return round(value, 4)

def suction_pressure_value() -> float:
    """Compressor suction (inlet) pressure in kPa — base 350 kPa."""
    # [SIM] Upstream pressure before compression. Low suction = starved inlet.
    # print(f"[simulate] suction_pressure={value:.2f} kPa")
    base  = 350.0
    noise = random.gauss(0, 10.0)
    value = base + noise
    return round(value, 4)

def bearing_temperature_value() -> float:
    """Bearing temperature in degC — base 65 degC."""
    # [SIM] Bearing temps climb slowly on degradation — drift detector is key here.
    # print(f"[simulate] bearing_temperature={value:.2f} degC")
    base  = 65.0
    noise = random.gauss(0, 1.5)
    value = base + noise
    return round(value, 4)

def power_draw_value() -> float:
    """Motor power draw in kW — base 450 kW."""
    # [SIM] Power draw correlates with load. Sudden spike = mechanical resistance or fault.
    # print(f"[simulate] power_draw={value:.2f} kW")
    base  = 450.0
    noise = random.gauss(0, 8.0)
    value = base + noise
    return round(value, 4)


CHANNEL_SIMULATORS = {
    "flow":        flow_value,
    "pressure":    pressure_value,
    "temperature": temperature_value,
    "level":       level_value,
    "vibration":   vibration_value,
    "speed":               speed_value,
    "discharge_pressure":  discharge_pressure_value,
    "suction_pressure":    suction_pressure_value,
    "bearing_temperature": bearing_temperature_value,
    "power_draw":          power_draw_value,
}

# [SIM] Uncomment to see the simulator registry at import time.
# print(f"[SIM] CHANNEL_SIMULATORS registered: {list(CHANNEL_SIMULATORS.keys())}")