import os
from pathlib import Path


def test_checked_contract_matches_triggering_commit():
    source=os.environ.get('ARYA_SPEC_FILE')
    if source:
        assert Path(source).read_bytes()==(Path(__file__).parents[1]/'specs/client.md').read_bytes(), (
            'Client spec changed: review and update arya-test coverage and pinned spec before accepting this check')
    else:
        assert (Path(__file__).parents[1]/'specs/client.md').is_file()
