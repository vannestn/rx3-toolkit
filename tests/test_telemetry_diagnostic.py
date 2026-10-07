import importlib.util
import json
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('diagnostic',Path(__file__).parents[1]/'scripts/telemetry_diagnostic.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class DiagnosticTests(unittest.TestCase):
 def message(self):
  return dict(type='now-playing',version=1,sequence=1,decks=[dict(deck=i,loaded=i==1,onAir=True,trackId=150 if i==1 else 0,bpmX100=12287,tempoRaw=-15,playModeRaw=2,title='') for i in (1,2)])
 def test_valid_and_unknown(self):
  v=m.validate(json.dumps(self.message()).encode());self.assertIsNotNone(v)
  f=m.fields(v);self.assertEqual(f[0]['effective_bpm'],122.87);self.assertIsNone(f[0]['title']);self.assertIsNone(f[1]['effective_bpm']);self.assertIsNone(f[0]['position_ms'])
 def test_bad_decks_do_not_crash(self):
  for decks in ([None,{}],[{},{}],[], 'bad'):
   v=self.message();v['decks']=decks;self.assertIsNone(m.validate(json.dumps(v).encode()))
 def test_bad_numbers(self):
  for bad in ('bad',True,None,float('nan'),{},2**40):
   v=self.message();v['decks'][0]['bpmX100']=bad;self.assertIsNone(m.validate(json.dumps(v).encode()))
 def test_malformed(self):
  for bad in (b'\xff',b'{',b'x'*4097,b'[]',b'['*2000):self.assertIsNone(m.validate(bad))
if __name__=='__main__':unittest.main()
