"""Focused prompt-data and grounding checks; no external model calls."""
import copy
import json
import unittest

import fixtures as f
from workflow.education import references
from workflow.education import _EducationWork, parse_plan
from education_fixtures import education_response
from workflow.model_context import messages, message_metrics
from workflow.prompt_data import prompt_text, recover_quote
from workflow.wire import table_payload


class PromptDataTests(unittest.TestCase):
    def test_only_injected_data_changes_and_json_output_instruction_survives(self):
        payload = dict(task='clinical_rank', facts=[dict(value='Reports "no pain", not “severe” pain.')],
                       measurement=dict(kind='quantity', value=0, unit='mg'), flag=False)
        original = copy.deepcopy(payload)
        prompt = 'Return {"result":"text with \\"quotes\\""}.'
        request = messages(prompt, payload)
        wire = json.loads(request[1]['content'])
        self.assertEqual(request[0]['content'], prompt)
        self.assertEqual(wire['facts'][0]['value'], 'Reports no pain, not severe pain.')
        self.assertNotIn('\\"', request[1]['content'])
        self.assertEqual(payload, original)
        self.assertEqual((wire['measurement']['value'], wire['flag']), (0, False))
        self.assertEqual(message_metrics('clinical', request)['counts']['facts'], 1)

    def test_table_rows_keep_identity_and_units_while_removing_prose_quotes(self):
        from protocol import decode_context
        records = [dict(id=f'quoted"id{i}', value='Says "no".', unit='"') for i in range(30)]
        payload = table_payload(dict(task='input_context', records=records), ('records',))
        self.assertIn('table', payload['records'])
        wire = decode_context(messages('Read data.', payload)[1]['content'])
        self.assertEqual(wire['records'][0], dict(id='quoted"id0', value='Says no.', unit='"'))

    def test_numeric_marks_and_word_apostrophes_keep_their_meaning(self):
        self.assertEqual(prompt_text('Height 5\'10"; don\'t use “urgent” as a diagnosis.'),
                         'Height 5′10″; don\'t use urgent as a diagnosis.')
        self.assertEqual(prompt_text('Reported "5" and \'6\'.'), 'Reported 5 and 6.')
        self.assertEqual(prompt_text("Patient in their 60's."), "Patient in their 60's.")

    def test_citations_recover_exact_utf8_offsets_and_reject_projection_collisions(self):
        text = '한글: Use "urgent" care.'
        refs = references([dict(document_id='doc', quote='Use urgent care.')], {'doc': [(17, text)]})
        start = 17 + len('한글: '.encode())
        self.assertEqual((refs[0]['start_byte'], refs[0]['end_byte']),
                         (start, start + len('Use "urgent" care.'.encode())))
        for source in ('Use "urgent" care. Use urgent care.', 'Different advice.'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                references([dict(document_id='doc', quote='Use urgent care.')], {'doc': [(0, source)]})

    def test_context_quotes_recover_original_spans_and_segment_grounding(self):
        c = f.consultation()
        text = '통증은 "가끔" 있어요.'
        payload = dict(records=[], question=None, input_segments={'opening': text})
        raw = dict(statements=[dict(quote='통증은 가끔 있어요.', role='unknown')])
        context, errors = c.ear._read_context(raw, payload, text)
        self.assertFalse(errors)
        self.assertEqual(context.statements[0].quote, text)
        self.assertEqual(context.statements[0].input_segment, 'opening')
        with self.assertRaises(ValueError):
            recover_quote('a "b" a b', 'a b')

    def test_demographics_recover_current_input_without_weakening_grounding(self):
        c = f.consultation()
        text = '나이는 "30세"입니다.'
        raw = dict(statements=[], patient_context=[dict(key='age', value='30 years', quote='나이는 30세입니다.')])
        context, errors = c.ear._read_context(raw, dict(records=[], question=None), text)
        self.assertFalse(errors)
        self.assertEqual(context.patient_context[0].quote, text)

    def test_repair_echo_without_quotes_cannot_duplicate_an_accepted_sentence(self):
        progress = _EducationWork()
        raw = education_response(dict(task='education', fields=['tests', 'treatment']))
        raw['P']['tests'][0]['text'] = 'Discuss "further evaluation" when indicated.'
        parse_plan(raw, {}, progress, fields=('tests', 'treatment'))
        raw['P']['tests'][0]['text'] = 'Discuss further evaluation when indicated.'
        accepted, errors = parse_plan(raw, {}, progress, fields=('tests', 'treatment'))
        self.assertEqual((accepted, errors), ([], []))
        self.assertEqual(len(progress.sentences), 2)
        self.assertIn('"further evaluation"', progress.sentences[0].text)


if __name__ == '__main__':
    unittest.main()
