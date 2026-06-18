from app.services.security.store import SecurityStore


def test_daemon_writes_marker_worker_consumes_it(tmp_path):
    daemon_side = SecurityStore(tmp_path)
    daemon_side.request_scan()                 # what POST /scan does
    worker_side = SecurityStore(tmp_path)      # separate process, same dir
    assert worker_side.consume_request() is True
    assert worker_side.consume_request() is False
