"""Some Tests for both OPC-UA and PI historian sources, more might be added in the future
Print statements available for the tests to confirm behaviour, use -v"""
import asyncio, pytest, math
from datetime import datetime, timezone, timedelta
from pipesense.config.loader import load_config
from pipesense.sources.base import DataSource, TagReading
from pipesense.sources.pi_generator import generate_pi_export
from pipesense.sources.pi_source import PIHistorianSource
from pipesense.sources.simulate import CHANNEL_SIMULATORS


@pytest.fixture
def site():
    config = load_config("config/site_default.yaml")
    site = config.sites[0]

    # print(f"\n[FIXTURE] site loaded: id={site.id!r} name={site.name!r}")
    # print(f"[FIXTURE] channels: {[ch.id for ch in site.channels]}")
    # print(f"[FIXTURE] channel types: "
    #       f"{[(ch.id, ch.type) for ch in site.channels]}")

    return site


@pytest.fixture
def pi_export_dir(tmp_path, site):
    generate_pi_export(site, tmp_path / "pi", duration_hours=1.0, interval_s=5)
    return tmp_path / "pi"


@pytest.fixture
def pi_export_dir(tmp_path, site):
    output = tmp_path / "pi"
    # print(f"\n[FIXTURE] generating PI exports → {output}")

    paths = generate_pi_export(site, output, duration_hours=1.0, interval_s=5)
    # for ch_id, path in paths.items():
    #     print(f"[FIXTURE]   {ch_id!r} → {path.name} exists={path.exists()}")

    return output


@pytest.fixture
def pi_source(site, pi_export_dir):
    # print(f"\n[FIXTURE] PIHistorianSource created: "
    #       f"site={site.id!r} dir={pi_export_dir}")

    return PIHistorianSource(site, pi_export_dir)

    
@pytest.mark.parametrize("ch_type,lo,hi", [
    ("flow",        200.0, 380.0),
    ("pressure",    590.0, 660.0),
    ("temperature",  14.0,  24.0),
    ("level",         0.5,   9.8),
    ("vibration",     0.0,   6.0),
])
def test_simulator_in_range(ch_type, lo, hi):
    fn = CHANNEL_SIMULATORS[ch_type]
    # print(f"\n[SIM] testing {ch_type!r} over 30 samples (expected {lo}–{hi}):")

    for i in range(30):
        v = fn()
        # print(f"[SIM]   sample {i+1:02d}: {v:.4f}")

        assert lo <= v <= hi, f"{ch_type}: {v} not in [{lo}, {hi}]"
    # print(f"[SIM] {ch_type!r}: all 30 samples in range [{lo}, {hi}]")


def test_all_simulators_return_finite_float():
    # print(f"\n[SIM] testing all {len(CHANNEL_SIMULATORS)} simulators:")

    for ch_type, fn in CHANNEL_SIMULATORS.items():
        v = fn()
        # print(f"[SIM]   {ch_type!r}: {v:.4f} "
        #       f"type={type(v).__name__} finite={math.isfinite(v)}")

        assert isinstance(v, float), f"{ch_type} returned {type(v)}"
        assert math.isfinite(v), f"{ch_type} returned non-finite: {v}"


def test_tag_reading_is_good():
    r = TagReading("FT-101", 280.0, datetime.now(timezone.utc), "Good")
    # print(f"\n[READING] TagReading: tag={r.tag_id!r} value={r.value:.4f} "
    #       f"quality={r.quality!r} is_good={r.is_good}")

    assert r.is_good


def test_tag_reading_bad_factory():
    r = TagReading.bad("FT-101", "Timeout")
    # print(f"\n[READING] bad TagReading: tag={r.tag_id!r} value={r.value} "
    #       f"quality={r.quality!r} is_good={r.is_good} "
    #       f"is_nan={math.isnan(r.value)}")

    assert not r.is_good
    assert r.quality == "Timeout"
    assert math.isnan(r.value)


def test_pi_source_connects(pi_source):
    asyncio.run(pi_source.connect())
    status = pi_source.status()
    # print(f"\n[PI-LOAD] after connect: connected={status.connected} "
    #       f"n_tags={status.n_tags} last_error={status.last_error!r}")

    assert status.connected


def test_pi_source_reads_all_channels(pi_source, site):
    async def _run():
        async with pi_source:
            tag_ids = [ch.id for ch in site.channels]
            # print(f"\n[PI-READ] read_tags request: {tag_ids}")

            readings = await pi_source.read_tags(tag_ids)
            # for r in readings:
            #     print(f"[PI-READ]   {r.tag_id!r}: {r.value:.4f} "
            #           f"[{r.quality}] is_good={r.is_good}")

            return readings

    readings = asyncio.run(_run())
    # print(f"\n[ASSERT] readings={len(readings)} expected={len(site.channels)} "
    #       f"good={sum(1 for r in readings if r.is_good)}")

    assert len(readings) == len(site.channels)
    assert all(r.is_good for r in readings)


def test_pi_source_read_tag_returns_float(pi_source, site):
    async def _run():
        async with pi_source:
            ch = site.channels[0]
            # print(f"\n[PI-READ] reading single tag: {ch.id!r} type={ch.type!r}")

            reading = await pi_source.read_tag(ch.id)
            # print(f"[PI-READ] result: value={reading.value:.4f} "
            #       f"quality={reading.quality!r} "
            #       f"ts={reading.timestamp.isoformat()}")

            return reading

    reading = asyncio.run(_run())

    # print(f"\n[ASSERT] value={reading.value} "
    #       f"is_float={isinstance(reading.value, float)} "
    #       f"is_good={reading.is_good}")

    assert isinstance(reading.value, float)
    assert reading.is_good


def test_pi_source_read_range_returns_multiple(pi_source, site):
    async def _run():
        async with pi_source:
            end = datetime.now(timezone.utc)
            start = end - timedelta(minutes=30)
            ch = site.channels[0]
            # print(f"\n[PI-RANGE] read_range: channel={ch.id!r} "
            #       f"start={start.isoformat()} end={end.isoformat()}")

            readings = await pi_source.read_range(ch.id, start, end)

            # if readings:
            #     print(f"[PI-RANGE] returned {len(readings)} readings")
            #     print(f"[PI-RANGE]   first: {readings[0].timestamp.isoformat()} "
            #           f"value={readings[0].value:.4f}")
            #     print(f"[PI-RANGE]   last:  {readings[-1].timestamp.isoformat()} "
            #           f"value={readings[-1].value:.4f}")
            # else:
            #     print(f"[PI-RANGE] WARNING: 0 readings returned — "
            #           f"check that export covers this time window")

            return readings

    readings = asyncio.run(_run())

    # print(f"\n[ASSERT] read_range count={len(readings)} (expected > 0)")

    assert len(readings) > 0


def test_pi_source_missing_channel_returns_bad(pi_source):
    async def _run():
        async with pi_source:
            # print(f"\n[PI-READ] requesting non-existent tag: 'NONEXISTENT-TAG'")

            reading = await pi_source.read_tag("NONEXISTENT-TAG")
            # print(f"[PI-READ] result: is_good={reading.is_good} "
            #       f"quality={reading.quality!r} value={reading.value}")

            return reading

    reading = asyncio.run(_run())

    # [ASSERT] Uncomment to inspect before assert.
    # print(f"\n[ASSERT] is_good={reading.is_good} (expected False)")

    assert not reading.is_good


def test_pi_source_status_type(pi_source):
    asyncio.run(pi_source.connect())
    status = pi_source.status()

    # print(f"\n[STATUS] SourceStatus: type={status.source_type!r} "
    #       f"connected={status.connected} endpoint={status.endpoint!r} "
    #       f"n_tags={status.n_tags} last_error={status.last_error!r}")

    assert status.source_type == "PI Historian"


def test_pi_source_implements_datasource(pi_source):

    # [ASSERT] To confirm the MRO (method resolution order)
    # and verify PIHistorianSource inherits from DataSource correctly.
    # Can fail this by breaking the inheritance chain
    print(f"\n[ASSERT] PIHistorianSource MRO: "
         f"{[c.__name__ for c in type(pi_source).__mro__]}")
    print(f"[ASSERT] isinstance check: {isinstance(pi_source, DataSource)}")

    assert isinstance(pi_source, DataSource)