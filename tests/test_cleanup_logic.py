from datetime import datetime, timezone, timedelta

from scripts.cleanup import should_delete


def test_release_older_than_cutoff_deleted():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    published = (now - timedelta(days=15)).isoformat()
    assert should_delete(published, retention_days=14, now=now) is True


def test_release_within_cutoff_kept():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    published = (now - timedelta(days=10)).isoformat()
    assert should_delete(published, retention_days=14, now=now) is False


def test_release_exactly_at_cutoff_kept():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    published = (now - timedelta(days=14)).isoformat()
    assert should_delete(published, retention_days=14, now=now) is False
