import sqlite3
from app.analytics import AnonymousMetrics

def test_anonymous_counter(tmp_path):
    path = tmp_path / 'metrics.sqlite3'
    metrics = AnonymousMetrics(path)
    metrics.record_search()
    metrics.record_search()
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT SUM(searches) FROM daily_metrics').fetchone()[0] == 2
        assert [x[1] for x in db.execute('PRAGMA table_info(daily_metrics)')] == ['day', 'searches']
