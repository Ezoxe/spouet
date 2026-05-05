import pytest
from unittest.mock import AsyncMock
from spouet.api.statistics import get_token_statistics
from spouet.api.deps import CurrentUser

class MockResult:
    def __init__(self, total_in, total_out, total_msg, total_latency):
        self.total_in = total_in
        self.total_out = total_out
        self.total_msg = total_msg
        self.total_latency = total_latency

class MockAsyncDb:
    def __init__(self, result):
        self._result = result
        self.execute = AsyncMock(return_value=self)

    def first(self):
        return self._result

@pytest.mark.asyncio
async def test_get_token_statistics():
    db = MockAsyncDb(MockResult(total_in=100, total_out=200, total_msg=3, total_latency=1500))
    user = AsyncMock(spec=CurrentUser)

    result = await get_token_statistics(user, db)

    assert result.total_tokens_in == 100
    assert result.total_tokens_out == 200
    assert result.total_messages == 3
    assert result.avg_tokens_per_second == 300 / 1.5

@pytest.mark.asyncio
async def test_get_token_statistics_empty():
    db = MockAsyncDb(MockResult(total_in=None, total_out=None, total_msg=0, total_latency=None))
    user = AsyncMock(spec=CurrentUser)

    result = await get_token_statistics(user, db)

    assert result.total_tokens_in == 0
    assert result.total_tokens_out == 0
    assert result.total_messages == 0
    assert result.avg_tokens_per_second is None
