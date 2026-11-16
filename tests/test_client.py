"""Local negative controls: prove the harness rejects corrupt wire behavior."""
import pytest
from arya_test.client import Client
from arya_test.audio import Opus


def test_validator_rejects_wrong_order_and_missing_ids():
    c=Client('ws://invalid','unused')
    with pytest.raises(AssertionError):
        c._validate({'type':'speaking'},0)
    c._validate({'type':'speaking','turn_id':'a'},0)
    with pytest.raises(AssertionError,match='interleaved'):
        c._validate({'type':'speaking','turn_id':'b'},0)


def test_validator_rejects_false_completion_and_liveness_after_done():
    c=Client('ws://invalid','unused')
    with pytest.raises(AssertionError):
        c._validate({'type':'turn_done','turn_id':'a'},0)
    c._validate({'type':'turn_done','turn_id':'a','next_action':'listen'},0)
    with pytest.raises(AssertionError,match='terminal'):
        c._validate({'type':'thinking','turn_id':'a','tool_calls':0,'reasoning_tokens':None},0)


def test_validator_rejects_unsolicited_transcripts():
    c=Client('ws://invalid','unused')
    with pytest.raises(AssertionError,match='unsolicited'):
        c._validate({'type':'transcript','turn_id':'a','role':'user','text':'hello'},0)


def test_codec_accepts_20ms_and_rejects_corruption():
    enc,dec=Opus(16000,True),Opus(16000)
    try:
        assert len(dec.decode(enc.encode(bytes(640))))==640
        with pytest.raises(AssertionError):
            dec.decode(b'')
    finally:
        enc.close()
        dec.close()


def test_validator_rejects_reply_without_closing_cursor():
    c=Client('ws://invalid','unused',transcripts=True)
    c.events.append({'type':'transcript','role':'assistant','turn_id':'a','text':'Hello'})
    with pytest.raises(AssertionError,match='closing transcript'):
        c._validate({'type':'turn_done','turn_id':'a','next_action':'standby'},0)
