"""Run with the standard library: python -m unittest discover -s tests -p test_ut_dashboard_adapter.py."""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1] / 'scripts/serve_ut_dashboard.py'
spec = importlib.util.spec_from_file_location('ut_dashboard', MODULE)
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class LogContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.session = self.root/'20261109-120000-000'
        self.session.mkdir()
        self.events = []
        self.event('REFERENCE_START', 'ReferenceCheck', 0)

    def event(self, kind, stage, second):
        self.events.append({'utc': f'2026-11-09T12:00:{second:02d}Z','kind': kind,
                                'stage': stage,'pipeId': 'BF1-Q005','status': 'test','workPermissionStatus': 'not_assessed'})
        (self.session/'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in self.events))

    def result(self, identity='request1', **changes):
        r = {'requestId': identity,'pipeId': 'BF1-Q005','sample': 0,'synthetic': True,
                 'sourceSha256': adapter.SOURCE_SHA,'workPermissionStatus': 'not_assessed',
                 'source': 'UT/examples/ascan.npz','model': 'frozen pitting MLP ensemble D',
                 'pitScore': .7,'threshold': .5,'pitAlarm': True,'wallValid': True,'mainWallMm': 5.1,
                 'wave': [.1]*4096}
        r.update(changes)
        f=self.session/(identity+'.json');f.write_text(json.dumps(r))
        stamp=adapter.utc_seconds('2026-11-09T12:00:10.1Z');os.utime(f,(stamp,stamp))
        return f

    def snapshot(self):
        return adapter.snapshot(self.root, {'BF1-Q005','BF1-G004'})

    def complete(self):
        for second,(kind,stage) in enumerate([('WALK','Walking'),('SURFACE_PREPARATION','SurfacePreparation'),('COUPLANT','Couplant'),('CONTACT','Contact'),('ANALYSE','Analysing')],1):
            self.event(kind,stage,second)
        self.event('RESULT','Complete',10);self.result()

    def test_result_without_worker_procedure_is_not_current(self):
        self.event('RESULT','Complete',10);self.result()
        row=self.snapshot()['pipes']['BF1-Q005']
        self.assertIsNone(row['result'])
        self.assertEqual(row['resultStatus'],'procedure_incomplete')

    def test_out_of_order_worker_steps_rejected(self):
        self.complete()
        self.events[1],self.events[2]=self.events[2],self.events[1]
        self.event('RESULT','Complete',11)
        self.assertIsNone(self.snapshot()['pipes']['BF1-Q005']['result'])

    def test_missing_logs_never_fabricate_result(self):
        self.assertEqual(adapter.snapshot(self.root/'missing',{'BF1-Q005'})['pipes'],{})

    def test_complete_result_requires_matching_pipe_and_source(self):
        self.complete();row=self.snapshot()['pipes']['BF1-Q005']
        self.assertEqual(row['result']['requestId'],'request1')
        self.assertEqual(len(row['result']['wave']),4096)
        self.assertNotIn('BF1-G004',self.snapshot()['pipes'])

    def test_new_run_clears_current_wave_and_labels_previous(self):
        self.complete();self.event('REFERENCE_START','ReferenceCheck',20)
        row=self.snapshot()['pipes']['BF1-Q005']
        self.assertIsNone(row['result']);self.assertIsNotNone(row['previous'])

    def test_cancelled_analysis_does_not_accept_late_file(self):
        self.event('ANALYSE','Analysing',8);self.event('CANCEL','Interrupted',9);self.result()
        self.assertIsNone(self.snapshot()['pipes']['BF1-Q005']['result'])

    def test_wrong_pipe_or_forged_source_or_nonfinite_wave_rejected(self):
        self.complete()
        for update in [{'pipeId': 'BF1-G004'},{'sourceSha256': '0'*64},{'wave': [float('nan')]*4096},{'pitAlarm': False},{'wallValid': True,'mainWallMm': -1}]:
            self.result(**update)
            self.assertIsNone(self.snapshot()['pipes']['BF1-Q005']['result'])

    def test_partial_json_is_pending_then_recovers(self):
        self.complete();f=self.session/'request1.json';f.write_text('{')
        self.assertIsNone(self.snapshot()['pipes']['BF1-Q005']['result'])
        self.result();self.assertIsNotNone(self.snapshot()['pipes']['BF1-Q005']['result'])

    def test_ambiguous_legacy_results_are_not_guessed(self):
        self.complete();self.result('request2')
        self.assertIsNone(self.snapshot()['pipes']['BF1-Q005']['result'])

    def test_stale_file_is_not_current(self):
        self.complete();f=self.session/'request1.json';os.utime(f,(0,0))
        self.assertIsNone(self.snapshot()['pipes']['BF1-Q005']['result'])

    def test_unknown_pipe_is_ignored(self):
        self.complete();self.assertEqual(adapter.snapshot(self.root,{'OTHER'})['pipes'],{})


if __name__ == '__main__':unittest.main()
