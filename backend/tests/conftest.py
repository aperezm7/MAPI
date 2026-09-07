import pytest

from app.cache import reset_cache_for_tests
from app.config import get_settings


@pytest.fixture(autouse=True)
def _isolate_settings_and_cache():
    get_settings.cache_clear()
    reset_cache_for_tests()
    yield
    reset_cache_for_tests()
    get_settings.cache_clear()
