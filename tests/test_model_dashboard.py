import base64
import json
import threading
from functools import partial
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer

import pytest

from maek.model_dashboard import Handler


class Models:
    def analyse(self, kind, raw):
        assert raw == b'photo'
        return {'regions': [], 'analysis_summary': '미검출'}


@pytest.fixture
def api(tmp_path):
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, models=Models(), dashboard=tmp_path))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def post(port, payload, origin=None):
    connection = HTTPConnection('127.0.0.1', port)
    headers = {'Content-Type': 'application/json'}
    if origin:
        headers['Origin'] = origin
    connection.request('POST', '/api/photo-inference', json.dumps(payload), headers)
    response = connection.getresponse()
    result = response.status, json.loads(response.read())
    connection.close()
    return result


def test_photo_identity_survives_inference(api):
    status, value = post(api, {'kind': 'rgb', 'pipeId': 'P-1', 'requestId': 'capture-2', 'fileBase64': base64.b64encode(b'photo').decode()})
    assert status == 200
    assert (value['pipeId'], value['requestId'], value['kind']) == ('P-1', 'capture-2', 'rgb')
    assert value['evidence']['requestId'] == 'capture-2'
    assert len(value['evidence']['sha256']) == 64


def test_bad_input_and_cross_origin_are_rejected(api):
    assert post(api, {})[0] == 400
    assert post(api, {}, origin='https://unrelated.example')[0] == 400
    assert post(api, {'kind': 'other', 'pipeId': 'P', 'requestId': 'r'})[0] == 400
