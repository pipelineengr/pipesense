"""Smoke tests for the virtual OPC-UA server."""

from pipesense.sources.simulate import CHANNEL_SIMULATORS, flow_value, pressure_value


def test_flow_value_in_range():
    for _ in range(50):
        v = flow_value(setpoint=280.0, amplitude=15.0, noise=2.0)
        # print (v)
        assert 230.0 < v < 330.0


def test_pressure_value_near_setpoint():
    values = [pressure_value(setpoint=620.0, noise=3.5) for _ in range(100)]
    mean = sum(values) / len(values)
    # print (mean)
    assert 610.0 < mean < 630.0


def test_all_simulator_types_return_float():
    for ch_type, fn in CHANNEL_SIMULATORS.items():
        result = fn()
        # print(f"DEBUG: Testing {ch_type} | Function: {fn.__name__} | Result: {result}")
        # print(f"DEBUG: {ch_type} type: {type(result)}")
        assert isinstance(result, float), f"{ch_type} returned {type(result)}"
        assert result == result
