"""Exclusive, cancellable hardware tests with persisted, inspectable results."""
import time
from datetime import datetime, timezone
from uuid import uuid4


def run_test(controller, request, cancel):
    link = controller.serial
    test_id = uuid4().hex
    result = {'test_id': test_id, 'component': request.component, 'state': 'RUNNING',
              'code': 'CONNECTING', 'message': 'Starting hardware test', 'measurements': {},
              'parameters': request.model_dump(),
              'started_at': datetime.now(timezone.utc).isoformat()}
    def publish():
        with controller.guard:
            controller.diagnostic = dict(result)
    publish()
    # Take the IO lock when reserving: an in-flight regular poll must finish first.
    with link.io_lock:
        link.testing.set()
    try:
        if cancel.is_set():
            result.update(state='CANCELLED', code='CANCELLED', message='Test cancelled')
            return
        response = link.request('TEST_START', test_id=test_id, **request.model_dump())
        deadline = time.monotonic() + request.duration_s + 5
        while True:
            if cancel.is_set() or controller.locked:
                result.update(state='CANCELLED', code='CANCELLED', message='Test stopped by operator or S1')
                break
            sample = response.get('test')
            if response['status'] != 'DIAGNOSTIC' or not sample or sample['test_id'] != test_id or sample.get('component') != request.component:
                raise ValueError('Hardware test session lost; restart the test')
            result.update(sample)
            publish()
            if result['state'] != 'RUNNING':
                break
            if time.monotonic() > deadline:
                raise TimeoutError('Hardware test timed out')
            if cancel.wait(.2):
                continue
            response = link.request('TEST_STATUS', test_id=test_id)
    except (OSError, ValueError) as exc:
        result.update(state='FAIL', code='SERIAL_ERROR', message=str(exc)[:200])
    finally:
        try:
            link.request('TEST_CANCEL', test_id=test_id)
        except (OSError, ValueError):
            pass  # ESP32 heartbeat watchdog independently stops abandoned tests.
        link.testing.clear()
        if cancel.is_set() or controller.locked:
            result.update(state='CANCELLED', code='CANCELLED', message='Test stopped by operator or S1')
        result['finished_at'] = datetime.now(timezone.utc).isoformat()
        controller.db.event(request.component, 'MANUAL_TEST', result)
        publish()
