"""Script the reviewed public opening's expected Context meaning, not model quality."""

OPENING = (
    '이름은 최윤정이고, 나는 서른두 살 여자이다. 최근 석 달 동안 살이 많이 빠져서 병원에 오게 되었다. '
    '원래 몸무게는 오십육 키로그람 정도였는데, 최근 석 달 사이에 칠 키로그람 정도 빠져서 지금은 사십구 키로그람 정도이다. '
    '평소에는 몸무게 변화가 거의 없었는데, 이번에는 다이어트나 운동을 한 것도 아닌데 저절로 살이 빠져서 걱정이 되었다. '
    '키는 백육십사 센티미터이다.'
)
VITAL_SIGNS = '혈압 : 138/72 mmHg\n맥박 : 102 회/분\n호흡 : 19 회/분\n체온 : 36.9°C'


def quantity(value, unit, *, approximate=False):
    return dict(kind='quantity', value=value, unit=unit, approximate=approximate)


def opening_context():
    def row(quote, **values):
        return dict(quote=quote, role='clinical', assertion='present', time_context='current',
                    input_segment='opening', **values)
    rows = [
        row('최근 석 달 동안 살이 많이 빠져서 병원에 오게 되었다.', target_terms=['Weight loss'],
            primary_concern=True, record_category='presentation'),
        row('최근 석 달 동안', focus='attribute', attribute_terms=['Duration since onset'], anchor=0,
            measurement=quantity(3, 'month'), record_category='onset', note_value='Elapsed time since weight loss began'),
        row('원래 몸무게는 오십육 키로그람 정도였는데', target_terms=['body weight'],
            measurement=quantity(56, 'kg', approximate=True), record_category='measurement', note_value='Baseline body weight'),
        row('칠 키로그람 정도 빠져서', focus='attribute', attribute_terms=['Absolute weight change (kg)'], anchor=0,
            measurement=quantity(7, 'kg', approximate=True), record_category='measurement', note_value='Amount of weight loss'),
        row('지금은 사십구 키로그람 정도이다.', target_terms=['body weight'],
            measurement=quantity(49, 'kg', approximate=True), record_category='measurement', note_value='Current body weight'),
        row('평소에는 몸무게 변화가 거의 없었는데', target_terms=['stable body weight'],
            record_category='course', note_value='Usually had little to no weight change before this episode'),
        row('이번에는 다이어트나 운동을 한 것도 아닌데 저절로 살이 빠져서', focus='attribute',
            attribute_terms=['Intentionality of weight change'], value_terms=['Unintentional'], anchor=0,
            note_value='Weight loss not attributed to dieting or exercise'),
        row('키는 백육십사 센티미터이다.', target_terms=['height'], measurement=quantity(164, 'cm'),
            record_category='measurement', note_value='Reported height'),
    ]
    rows[2]['time_context'] = rows[5]['time_context'] = 'past'
    for quote, meaning, value, unit in (
        ('138', 'Systolic blood pressure', 138, 'mmHg'), ('72', 'Diastolic blood pressure', 72, 'mmHg'),
        ('102', 'Pulse rate', 102, '회/분'), ('19', 'Respiratory rate', 19, '회/분'),
        ('36.9°C', 'Body temperature', 36.9, '°C'),
    ):
        rows.append(dict(quote=quote, role='clinical', assertion='present', time_context='current',
            input_segment='vital_signs', target_terms=[meaning], note_value=meaning,
            record_category='objective_observation', measurement=quantity(value, unit)))
    return dict(statements=rows, patient_context=[
        dict(key='age', value='32 years', quote='서른두 살', measurement=quantity(32, 'year')),
        dict(key='sex', value='female', quote='여자'),
    ])
