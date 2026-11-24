"""Decorator that adds the server time to endpoint responses."""
import inspect
from app.timing import measured


def test_measured_adds_time_and_keeps_signature():
    @measured()
    def handler(limit: int = 5):
        return {'limit': limit}
    result = handler(limit=3)
    assert result['limit'] == 3 and result['tookMs'] >= 0
    assert list(inspect.signature(handler).parameters) == ['limit'] and handler.__name__ == 'handler'


def test_non_dict_results_are_returned_untouched():
    @measured('elapsed')
    def handler():
        return ['a']
    assert handler() == ['a']
