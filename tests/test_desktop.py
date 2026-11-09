import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock
spec=importlib.util.spec_from_file_location('taxile_pc',Path(__file__).parents[1]/'desktop/taxile_pc.py')
module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
class ClientTests(unittest.TestCase):
 def test_reject_foreign_url_parts(self):
  for address in ('http://user:pass@host','http://host/path','ftp://host','http://host/?x=1'):
   with self.assertRaises(ValueError): module.Client(address,'secret')
 def test_read_uses_fresh_csrf(self):
  c=module.Client('192.168.4.1','secret'); c.session=Mock()
  c.session.get.return_value.json.return_value={'version':'0.4.0','csrf':'fresh'}
  c.session.post.return_value.status_code=200
  c.session.post.return_value.json.return_value={'ok':True,'codes':['P0301']}
  self.assertEqual(c.diagnostic()['codes'],['P0301'])
  self.assertEqual(c.session.post.call_args.kwargs['headers']['X-Taxile-CSRF'],'fresh')
  self.assertEqual(c.session.post.call_args.kwargs['data'],'')
 def test_clear_requires_explicit_payload(self):
  c=module.Client('host','secret'); c.status=Mock(return_value={'csrf':'x'}); c.session=Mock()
  c.session.post.return_value.status_code=200; c.session.post.return_value.json.return_value={'ok':True}
  c.diagnostic(True); self.assertEqual(c.session.post.call_args.kwargs['data'],'CLEAR')
 def test_failure_is_not_empty_success(self):
  c=module.Client('host','secret'); c.status=Mock(return_value={'csrf':'x'}); c.session=Mock()
  c.session.post.return_value.status_code=502; c.session.post.return_value.text='No valid ECU acknowledgement'
  with self.assertRaises(ValueError): c.diagnostic()
 def test_wrong_firmware(self):
  c=module.Client('host','secret'); c.session=Mock()
  c.session.get.return_value.json.return_value={'version':'0.2.0'}
  with self.assertRaises(ValueError): c.status()
if __name__=='__main__': unittest.main()
