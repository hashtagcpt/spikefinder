import pytest

from spikefinder.sample import N_SAMPLES as N, make_avg, write_sample_esx   # noqa: F401  (re-exported for the tests)


def write_esx(path, **kw):
    return write_sample_esx(path, **kw)


@pytest.fixture(scope="session")
def esx_file(tmp_path_factory):
    return write_sample_esx(str(tmp_path_factory.mktemp("esx") / "13151_2025_04_09.esx"), name="13151")
