import contextlib
import csv
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from ontoward_extraction.__main__ import main
from ontoward_extraction.inputs import rows
from ontoward_extraction.jobs import Jobs
from ontoward_extraction.models import canonical


class IndexProgressTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)

    def entry(self,name,role,content):
        path=self.root/name;path.write_text(content)
        return dict(path=str(path),relative_path=name,role=role,member=None)

    def test_rf2_preserves_literal_balanced_and_unbalanced_quotes(self):
        terms=['"unclosed clinical term','"Quoted clinical term"','A "literal" term']
        entry=self.entry('Snapshot.txt','rf2','id\teffectiveTime\tactive\tterm\r\n'+''.join(
            f'{index}\t20260501\t1\t{term}\r\n' for index,term in enumerate(terms,1)))
        parsed=list(rows(entry))
        self.assertEqual([row['term'] for row in parsed],terms)
        self.assertEqual([row['id'] for row in parsed],['1','2','3'])

    def test_legitimate_large_rf2_field_and_bodhi_csv_quoting(self):
        value='X'*200000
        entry=self.entry('OWLExpressionSnapshot.txt','rf2','id\teffectiveTime\tactive\towlExpression\n1\t20260501\t1\t'+value+'\n')
        self.assertEqual(next(rows(entry))['owlExpression'],value)
        text=io.StringIO();writer=csv.writer(text);writer.writerow(['snomed_id','concept_type','name'])
        writer.writerow(['123','disorder','A, "quoted" name\ncontinued'])
        entry=self.entry('nodes_condition.csv','bodhi:nodes_condition',text.getvalue())
        self.assertEqual(next(rows(entry))['name'],'A, "quoted" name\ncontinued')

    def test_malformed_width_and_csv_are_contextual_errors(self):
        entry=self.entry('broken-Snapshot.txt','rf2','id\teffectiveTime\tactive\n1\t20260501\t1\textra\n')
        with self.assertRaisesRegex(ValueError,'input_column_count_mismatch:broken-Snapshot.txt:line=2'):
            list(rows(entry))
        entry=self.entry('broken.csv','bodhi:nodes_condition','id,name\n1,"unterminated\n')
        with self.assertRaisesRegex(ValueError,'input_parse_error:broken.csv:line='):
            list(rows(entry))

    def test_status_reads_legacy_cursors_without_mutation(self):
        entries=[dict(relative_path='one.txt',member=None),dict(relative_path='two.txt',member=None)]
        jobs=Jobs(self.root/'saved',{'inputs':entries,'config':{'provider':'nova_dev'}})
        jobs.set('state','failed');jobs.set('phase','index')
        jobs.set('indexed:'+canonical(['one.txt',None]),True)
        jobs.set('cursor:'+canonical(['one.txt',None]),2000)
        jobs.set('cursor:'+canonical(['two.txt',None]),1000)
        jobs.close();before=(self.root/'saved/jobs.sqlite3').read_bytes()
        readonly=Jobs(self.root/'saved',readonly=True)
        status=readonly.status();self.assertEqual(readonly.db.total_changes,0);readonly.close()
        self.assertEqual(status['index']['files_completed'],1)
        self.assertEqual(status['index']['files_total'],2)
        self.assertEqual(status['index']['rows_committed'],3000)
        self.assertEqual(status['index']['current_file']['path'],'two.txt')
        self.assertEqual(before,(self.root/'saved/jobs.sqlite3').read_bytes())

    def test_watch_never_initializes_a_provider_and_exits_on_interrupt(self):
        output=io.StringIO()
        with patch('ontoward_extraction.build.Provider') as provider,patch('time.sleep',side_effect=KeyboardInterrupt),contextlib.redirect_stdout(output):
            self.assertEqual(main(['status','--work',str(self.root),'--watch']),0)
        provider.assert_not_called();self.assertIn('not_started',output.getvalue())

    def test_console_wrapper_saves_both_streams_and_preserves_failure_exit_code(self):
        project=self.root/'project';(project/'Extraction').mkdir(parents=True)
        script=project/'Extraction/extraction.sh'
        shutil.copyfile(Path(__file__).parents[1]/'extraction.sh',script)
        binaries=self.root/'bin';binaries.mkdir();docker=binaries/'docker'
        docker.write_text('#!/bin/sh\necho "synthetic stdout"\necho "synthetic stderr" >&2\nexit 7\n');docker.chmod(0o755)
        result=subprocess.run(['bash',str(script),'run','--provider','nova_dev','--install'],
            capture_output=True,text=True,env=dict(os.environ,PATH=str(binaries)+':'+os.environ['PATH']))
        self.assertEqual(result.returncode,7)
        saved=(project/'data/extraction/v5-enum/logs/latest.log').read_text()
        self.assertIn('synthetic stdout',saved);self.assertIn('synthetic stderr',saved)


if __name__=='__main__': unittest.main()
