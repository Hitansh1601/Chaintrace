import pytest

from chaintrace.importer import load_transactions
from chaintrace.synthetic import SAMPLE_CSV


@pytest.fixture(scope="session")
def synthetic_df():
    return load_transactions(SAMPLE_CSV).valid
