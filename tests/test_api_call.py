"""api.call passes an op's own `name` argument through (ledger M65)."""
import pytest

from ismail import api


def test_call_takes_an_op_whose_argument_is_called_name(monkeypatch):
    got = {}
    monkeypatch.setitem(api.OPS, '_probe', lambda **kw: got.update(kw) or 'ok')
    assert api.call('_probe', name='cello', project='p') == 'ok'
    assert got == {'name': 'cello', 'project': 'p'}
    with pytest.raises(api.OpError, match='unknown op'):
        api.call('_nope')
