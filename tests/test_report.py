"""Report regressions: preserve actionable failures and incomplete-run status."""
from types import SimpleNamespace

from tests.conftest import pytest_terminal_summary


def test_report_lists_every_failure_and_provenance(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('CI_COMMIT_SHA', 'server-revision')
    failures = [SimpleNamespace(when='call', nodeid=f'test_{i}', longrepr='TimeoutError') for i in range(5)]
    pytest_terminal_summary(SimpleNamespace(stats={'failed': failures}), 1)
    report = (tmp_path / 'reports/summary.md').read_text()
    assert all(f'`test_{i}`' in report for i in range(5))
    assert '5×' in report and 'server-revis' in report
    assert 'Suite commit `' in report and 'pytest exit status `1`' in report
    assert report.splitlines()[2].startswith('Run finished 20') and report.splitlines()[2].endswith(' UTC.')


def test_collection_error_cannot_report_green(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    pytest_terminal_summary(SimpleNamespace(stats={}), 2)
    report = (tmp_path / 'reports/summary.md').read_text()
    assert '❌' in report and 'Run incomplete' in report
    assert 'pytest exit status `2`' in report


def test_teardown_failure_is_visible(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    error = SimpleNamespace(when='teardown', nodeid='test_cleanup', longrepr='cleanup failed')
    pytest_terminal_summary(SimpleNamespace(stats={'error': [error]}), 1)
    report = (tmp_path / 'reports/summary.md').read_text()
    assert '`test_cleanup`' in report and 'cleanup failed' in report
