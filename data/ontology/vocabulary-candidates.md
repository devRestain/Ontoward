# 온톨로지 영어 어휘 검토 목록

이 문서는 [D08·D09](../../DECISION_STATE.md#D08)에 따라 의료인 사용자가 2026-10-12 승인한 일곱 객체의 영어 자연어 어휘 목록이다. 승인된 510개 항목과 함께 제공된 검토 메타데이터를 후속 작업의 기준으로 사용한다. 설명은 한국어로 작성하고 용어는 영어로 유지한다. [승인 기록](vocabulary-approval.json)은 승인 당시 파일의 SHA-256과 항목 수를 보존하며, 현재 작업 상태는 [데이터 상태](../PROJECT_STATE.md)가 소유한다. 개념 ID·동의어 연결·대상별 세부 속성 적용과 RDF 수용은 다음 준비 계약에서 정한다.

| Object | 후보 개수 | 구성 |
|---|---:|---|
| Disease | 100 | 기존 후보의 명칭과 순서 유지 |
| Symptom | 100 | 구체적인 통증 증상 19개와 나머지 81개 유지 |
| ExamFinding | 60 | 주요 계통의 신체진찰·침상 평가 소견 |
| AttributeValue | 100 | 기존 영어 명칭 77개와 추가 후보 23개 |
| ContextFactor | 60 | 기존 contextType 10개에 걸친 병력·노출·배경 정보 |
| Test | 40 | 기본 검사 계획 대상 |
| ExamMethod | 50 | 기존 영어 명칭 24개와 추가 후보 26개 |

총 510개 승인된 자연어 항목이며 RDF에 수용된 개념 수를 의미하지 않는다. 이번 승인은 어휘 작업 기준의 확정이다. 새 Turtle 노드·관계·검사 요청문·Pydantic 추출 스키마 생성과 모델 호출·파일럿 실행은 후속 과제로 유지한다.

증상 검색은 AbdominalPain·ChestPain·Headache·Dysuria처럼 일반적인 임상 주호소에서 시작한다. 세부 위치는 평면 Location 값으로 유지하고 원문·확인한 속성·해석 불확실성·서로 다른 에피소드를 구분한다. 부위나 상황을 모르는 통증은 확인할 때까지 미해결 원문으로 남긴다.

| Source expression | Symptom concept | 확인한 속성 처리 |
|---|---|---|
| Abdominal pain | AbdominalPain | 세부 Location은 확인한 경우에 기록 |
| Chest pain | ChestPain | 세부 Location은 확인한 경우에 기록 |
| Headache | Headache | 세부 Location은 확인한 경우에 기록 |
| Low back pain | BackPain | Location=LowerBack |
| Right lower quadrant pain | AbdominalPain | Location=RightLowerQuadrant; Abdomen은 자동 추가하지 않음 |
| Dysuria | Dysuria | 배뇨 상황의 원문과 추가 확인한 속성 보존 |
| Unspecified pain | Unresolved | 특정 개념을 강제하지 않고 부위·상황 확인 |

Symptom 목록의 첫 19개 통증 개념은 기존 기초 Turtle에 속성 13개와 함께 준비되어 있다. 목록에는 새 통증 개념의 BodySystem 값이 지정되어 있지 않으므로 해당 분류는 후속 어휘 수용 계약에서 정한다. 이번 승인 기록으로 기초 Turtle은 변경하지 않는다. Migraine·Tension-type headache·Cluster headache는 Disease 항목으로 유지한다.

질환은 후속 문헌 추출에서 각각 근거가 있는 여러 증상 Target의 대안 Pattern을 가질 수 있다. 대안 Pattern의 동시 일치를 요구하지 않으며, 문헌에 근거한 질환 표현과 환자 원문의 정정을 구분한다. 진단 후보에 맞춰 관찰을 바꾸거나 관계를 만들지 않는다.

## Disease — 100 terms

| No. | Disease | No. | Disease |
|---:|---|---:|---|
| 1 | Acute appendicitis | 51 | Migraine |
| 2 | Acute cholecystitis | 52 | Tension-type headache |
| 3 | Acute cholangitis | 53 | Cluster headache |
| 4 | Acute pancreatitis | 54 | Ischemic stroke |
| 5 | Acute gastroenteritis | 55 | Intracerebral hemorrhage |
| 6 | Acute gastritis | 56 | Subarachnoid hemorrhage |
| 7 | Peptic ulcer disease | 57 | Meningitis |
| 8 | Gastroesophageal reflux disease | 58 | Epilepsy |
| 9 | Irritable bowel syndrome | 59 | Benign paroxysmal positional vertigo |
| 10 | Ulcerative colitis | 60 | Vestibular neuritis |
| 11 | Crohn disease | 61 | Ménière disease |
| 12 | Acute diverticulitis | 62 | Bell palsy |
| 13 | Bowel obstruction | 63 | Acute cystitis |
| 14 | Functional constipation | 64 | Acute pyelonephritis |
| 15 | Hemorrhoids | 65 | Urolithiasis |
| 16 | Anal fissure | 66 | Acute bacterial prostatitis |
| 17 | Colorectal cancer | 67 | Benign prostatic hyperplasia |
| 18 | Gastric cancer | 68 | Acute kidney injury |
| 19 | Liver cirrhosis | 69 | Chronic kidney disease |
| 20 | Acute viral hepatitis | 70 | Acute glomerulonephritis |
| 21 | Hypertension | 71 | Type 1 diabetes mellitus |
| 22 | Acute myocardial infarction | 72 | Type 2 diabetes mellitus |
| 23 | Stable angina | 73 | Diabetic ketoacidosis |
| 24 | Unstable angina | 74 | Hyperthyroidism |
| 25 | Heart failure | 75 | Hypothyroidism |
| 26 | Atrial fibrillation | 76 | Subacute thyroiditis |
| 27 | Paroxysmal supraventricular tachycardia | 77 | Adrenal insufficiency |
| 28 | Pericarditis | 78 | Iron deficiency anemia |
| 29 | Myocarditis | 79 | Vitamin B12 deficiency anemia |
| 30 | Aortic dissection | 80 | Gout |
| 31 | Pulmonary embolism | 81 | Rheumatoid arthritis |
| 32 | Deep vein thrombosis | 82 | Osteoarthritis |
| 33 | Peripheral artery disease | 83 | Lumbar disc herniation |
| 34 | Orthostatic hypotension | 84 | Spinal stenosis |
| 35 | Vasovagal syncope | 85 | Rotator cuff tear |
| 36 | Asthma | 86 | Cellulitis |
| 37 | Chronic obstructive pulmonary disease | 87 | Herpes zoster |
| 38 | Pneumonia | 88 | Atopic dermatitis |
| 39 | Acute bronchitis | 89 | Contact dermatitis |
| 40 | Bronchiectasis | 90 | Urticaria |
| 41 | Pneumothorax | 91 | Anaphylaxis |
| 42 | Lung cancer | 92 | Pelvic inflammatory disease |
| 43 | Acute upper respiratory tract infection | 93 | Ectopic pregnancy |
| 44 | Influenza | 94 | Ovarian cyst |
| 45 | COVID-19 | 95 | Endometriosis |
| 46 | Acute tonsillopharyngitis | 96 | Major depressive disorder |
| 47 | Acute sinusitis | 97 | Generalized anxiety disorder |
| 48 | Allergic rhinitis | 98 | Panic disorder |
| 49 | Pulmonary tuberculosis | 99 | Adjustment disorder |
| 50 | Obstructive sleep apnea | 100 | Insomnia disorder |

## Symptom — 100 terms

| No. | Symptom | No. | Symptom |
|---:|---|---:|---|
| 1 | Abdominal pain | 51 | Weakness |
| 2 | Chest pain | 52 | Paresthesia |
| 3 | Headache | 53 | Numbness |
| 4 | Back pain | 54 | Tremor |
| 5 | Neck pain | 55 | Seizures |
| 6 | Sore throat | 56 | Memory impairment |
| 7 | Toothache | 57 | Difficulty concentrating |
| 8 | Ear pain | 58 | Slurred speech |
| 9 | Eye pain | 59 | Blurred vision |
| 10 | Joint pain | 60 | Diplopia |
| 11 | Muscle pain | 61 | Photophobia |
| 12 | Limb pain | 62 | Vision loss |
| 13 | Pelvic pain | 63 | Tinnitus |
| 14 | Flank pain | 64 | Hearing loss |
| 15 | Anal pain | 65 | Loss of smell |
| 16 | Dysuria | 66 | Loss of taste |
| 17 | Odynophagia | 67 | Polyuria |
| 18 | Dyspareunia | 68 | Oliguria |
| 19 | Dysmenorrhea | 69 | Urinary frequency |
| 20 | Nausea | 70 | Nocturia |
| 21 | Vomiting | 71 | Urinary urgency |
| 22 | Diarrhea | 72 | Urinary hesitancy |
| 23 | Constipation | 73 | Weak urinary stream |
| 24 | Hematemesis | 74 | Sensation of incomplete bladder emptying |
| 25 | Hematochezia | 75 | Urinary incontinence |
| 26 | Melena | 76 | Hematuria |
| 27 | Fecal incontinence | 77 | Urethral discharge |
| 28 | Tenesmus | 78 | Fever |
| 29 | Abdominal bloating | 79 | Chills |
| 30 | Early satiety | 80 | Fatigue |
| 31 | Loss of appetite | 81 | Malaise |
| 32 | Increased appetite | 82 | Weight gain |
| 33 | Dysphagia | 83 | Weight loss |
| 34 | Regurgitation | 84 | Excessive thirst |
| 35 | Cough | 85 | Excessive sweating |
| 36 | Sputum production | 86 | Night sweats |
| 37 | Hemoptysis | 87 | Pruritus |
| 38 | Dyspnea | 88 | Rash |
| 39 | Wheezing | 89 | Easy bruising |
| 40 | Nasal congestion | 90 | Swelling |
| 41 | Rhinorrhea | 91 | Vaginal bleeding |
| 42 | Sneezing | 92 | Vaginal discharge |
| 43 | Epistaxis | 93 | Menstrual irregularity |
| 44 | Hoarseness | 94 | Amenorrhea |
| 45 | Palpitations | 95 | Anxiety |
| 46 | Syncope | 96 | Depressed mood |
| 47 | Presyncope | 97 | Insomnia |
| 48 | Dizziness | 98 | Excessive daytime sleepiness |
| 49 | Vertigo | 99 | Irritability |
| 50 | Imbalance | 100 | Anhedonia |

## ExamFinding — 60 terms

실제 신체진찰이나 침상 평가에서 얻을 수 있는 소견 후보다. 환자가 호소한 Wheezing과 청진으로 확인한 Wheezes처럼, 비슷한 표현도 획득 경로에 따라 Symptom과 ExamFinding을 구분한다. Pallor·Conjunctival pallor처럼 일반 소견과 특정 부위 소견은 독립 개념으로 유지할지 속성으로 분해할지 사용자 검토에서 정한다.

| No. | ExamFinding | No. | ExamFinding |
|---:|---|---:|---|
| 1 | Pallor | 31 | Stridor |
| 2 | Cyanosis | 32 | Decreased breath sounds |
| 3 | Jaundice | 33 | Dullness to percussion |
| 4 | Diaphoresis | 34 | Asymmetric chest expansion |
| 5 | Dry oral mucosa | 35 | Abdominal distension |
| 6 | Elevated body temperature | 36 | Abdominal tenderness |
| 7 | Tachycardia | 37 | Abdominal guarding |
| 8 | Bradycardia | 38 | Rebound tenderness |
| 9 | Tachypnea | 39 | Murphy sign |
| 10 | Hypotension | 40 | Costovertebral angle tenderness |
| 11 | Orthostatic blood pressure drop | 41 | Hepatomegaly |
| 12 | Reduced oxygen saturation | 42 | Splenomegaly |
| 13 | Conjunctival pallor | 43 | Hyperactive bowel sounds |
| 14 | Scleral icterus | 44 | Decreased bowel sounds |
| 15 | Conjunctival injection | 45 | Neck stiffness |
| 16 | Anisocoria | 46 | Muscle weakness |
| 17 | Reduced pupillary light response | 47 | Reduced sensation |
| 18 | Nystagmus | 48 | Hyperreflexia |
| 19 | Pharyngeal erythema | 49 | Hyporeflexia |
| 20 | Tonsillar exudate | 50 | Extensor plantar response |
| 21 | Cervical lymphadenopathy | 51 | Positive straight leg raise |
| 22 | Thyroid enlargement | 52 | Romberg sign |
| 23 | Jugular venous distension | 53 | Limb dysmetria |
| 24 | Irregular pulse | 54 | Abnormal gait |
| 25 | Reduced peripheral pulses | 55 | Restricted joint range of motion |
| 26 | Delayed capillary refill | 56 | Joint effusion |
| 27 | Cardiac murmur | 57 | Pitting edema |
| 28 | Pericardial friction rub | 58 | Petechiae |
| 29 | Crackles | 59 | Purpura |
| 30 | Wheezes | 60 | Skin erythema |

체온·맥박·혈압·산소포화도 등의 실제 수치와 단위는 환자 상태에 보존한다. 이번 목록은 수치 임계값이나 자동 범주 변환 기준을 정하지 않는다.

## AttributeValue — 100 terms

1–77번은 현재 기초 어휘의 영어 명칭을 그대로 유지하고 78–100번은 추가 후보로 둔다. 기존 Location 값 45개는 유지하며 위치 계층을 추가하지 않는다. 아래 속성 표는 적용 범위에 대한 검토 제안이며 확정된 canHaveValue 관계가 아니다.

| 후보 번호 | 적용할 FindingAttribute |
|---|---|
| 1–45 | Location, Radiation |
| 46–49 | Laterality |
| 50–57, 78–88 | Quality |
| 58–59 | Onset |
| 60–63, 89–91 | Course |
| 64–67, 92–95 | Timing |
| 68–70 | Severity |
| 71–77, 96–100 | Trigger, AggravatingFactor, RelievingFactor |

발생·악화·완화 요인의 공통 후보군을 각 속성에 모두 연결하지 않는다. 실제 의미에 맞는 연결을 사용자 검토 후 확정한다. Quality도 대상 증상·소견에 따라 적용 범위를 구분한다. Productive는 기침에, Purulent는 객담·분비물 등의 표현에 적용할 후보이며 통증 전체에 일괄 적용하지 않는다.

| No. | AttributeValue | No. | AttributeValue |
|---:|---|---:|---|
| 1 | Head | 51 | Squeezing |
| 2 | Forehead | 52 | Burning |
| 3 | Temple | 53 | Stabbing |
| 4 | Occiput | 54 | Dull |
| 5 | Face | 55 | Aching |
| 6 | Eye | 56 | Cramping |
| 7 | Ear | 57 | Throbbing |
| 8 | Nose | 58 | Sudden |
| 9 | Mouth | 59 | Gradual |
| 10 | Throat | 60 | Continuous |
| 11 | Neck | 61 | Intermittent |
| 12 | Chest | 62 | Progressive |
| 13 | Sternal region | 63 | Improving |
| 14 | Lateral chest | 64 | Morning |
| 15 | Abdomen | 65 | Daytime |
| 16 | Epigastrium | 66 | Evening |
| 17 | Periumbilical region | 67 | Nighttime |
| 18 | Right upper quadrant | 68 | Mild |
| 19 | Left upper quadrant | 69 | Moderate |
| 20 | Right lower quadrant | 70 | Severe |
| 21 | Left lower quadrant | 71 | Exertion |
| 22 | Suprapubic region | 72 | Meals |
| 23 | Flank | 73 | Breathing |
| 24 | Back | 74 | Coughing |
| 25 | Upper back | 75 | Movement |
| 26 | Lower back | 76 | Position change |
| 27 | Pelvis | 77 | Rest |
| 28 | Groin | 78 | Sharp |
| 29 | Perineum | 79 | Tearing |
| 30 | Shoulder | 80 | Shooting |
| 31 | Upper arm | 81 | Electric shock-like |
| 32 | Elbow | 82 | Colicky |
| 33 | Forearm | 83 | Watery |
| 34 | Wrist | 84 | Mucoid |
| 35 | Hand | 85 | Purulent |
| 36 | Finger | 86 | Bloody |
| 37 | Hip | 87 | Dry |
| 38 | Thigh | 88 | Productive |
| 39 | Knee | 89 | Recurrent |
| 40 | Lower leg | 90 | Stable |
| 41 | Calf | 91 | Fluctuating |
| 42 | Ankle | 92 | Upon waking |
| 43 | Foot | 93 | After meals |
| 44 | Toe | 94 | Before meals |
| 45 | Whole body | 95 | During sleep |
| 46 | Left | 96 | Deep inspiration |
| 47 | Right | 97 | Swallowing |
| 48 | Bilateral | 98 | Defecation |
| 49 | Midline | 99 | Sexual intercourse |
| 50 | Pressure-like | 100 | Menstruation |

EpisodeDuration과 Frequency에는 임의의 구간이나 수치 범주를 추가하지 않는다. 정확한 지속 시간과 빈도는 기존 결정대로 환자 상태에서 관리한다.

## ContextFactor — 60 terms

이미 검색된 질환 후보를 해석하는 데 사용할 병력·노출·배경 정보 후보다. 병력의 대상이 환자인지 가족인지, 현재인지 과거인지와 실제 약물·노출 내용은 환자 상태에서 별도로 보존한다. 아래 표는 기존 contextType 10개에 대한 분류 제안이며 개별 노드의 확정 분류가 아니다.

| 후보 번호 | contextType |
|---|---|
| 1–10 | past_medical_history |
| 11–15 | surgical_history |
| 16–24 | medication_history |
| 25–27 | allergy_history |
| 28–32 | family_history |
| 33–43 | social_history |
| 44–47 | occupational_history |
| 48–52 | psychosocial_history |
| 53–54 | screening_history |
| 55–60 | demographic |

| No. | ContextFactor | No. | ContextFactor |
|---:|---|---:|---|
| 1 | History of hypertension | 31 | Family history of asthma |
| 2 | History of diabetes mellitus | 32 | Family history of autoimmune disease |
| 3 | History of coronary artery disease | 33 | Current tobacco use |
| 4 | History of heart failure | 34 | Previous tobacco use |
| 5 | History of atrial fibrillation | 35 | Heavy alcohol use |
| 6 | History of venous thromboembolism | 36 | Injection drug use |
| 7 | History of asthma | 37 | Recent travel |
| 8 | History of chronic obstructive pulmonary disease | 38 | Sick contact |
| 9 | History of chronic kidney disease | 39 | Tuberculosis exposure |
| 10 | Immunosuppression | 40 | Prolonged immobilization |
| 11 | Previous abdominal surgery | 41 | Unprotected sexual intercourse |
| 12 | Previous pelvic surgery | 42 | Recent animal exposure |
| 13 | Previous urinary tract procedure | 43 | Recent ingestion of potentially contaminated food |
| 14 | Previous joint surgery | 44 | Asbestos exposure |
| 15 | Recent surgery | 45 | Silica exposure |
| 16 | NSAID use | 46 | Repetitive manual work |
| 17 | Anticoagulant use | 47 | Occupational chemical exposure |
| 18 | Antiplatelet use | 48 | Recent major stressor |
| 19 | Systemic corticosteroid use | 49 | Bereavement |
| 20 | Immunosuppressant use | 50 | Financial stress |
| 21 | Diuretic use | 51 | Social isolation |
| 22 | Oral contraceptive use | 52 | Sleep deprivation |
| 23 | Recent antibiotic use | 53 | Overdue colorectal cancer screening |
| 24 | Opioid use | 54 | Previous abnormal cervical screening result |
| 25 | Drug allergy | 55 | Older age |
| 26 | Food allergy | 56 | Pregnancy |
| 27 | Latex allergy | 57 | Postpartum status |
| 28 | Family history of premature cardiovascular disease | 58 | Postmenopausal status |
| 29 | Family history of diabetes mellitus | 59 | Female sex |
| 30 | Family history of colorectal cancer | 60 | Male sex |

Recent·Older·Heavy·Overdue의 시간·연령·양·기준은 이번 목록에서 자동 판정 규칙으로 정의하지 않는다. 실제 정보를 보존한 뒤 문헌 적용 조건과 사용자 검토에 따라 해석한다. 확인되지 않은 맥락은 음성이나 질환 배제 근거로 사용하지 않으며, 맥락만으로 질환 후보를 생성하지 않는다.

## Test — 40 terms

기본 검사실·미생물·영상·기능 검사 계획 대상이다. 현재 계약대로 SOAP P.tests에 사용하며 이 목록으로 TEST 실행이나 검사 결과 기반 진단 추론을 추가하지 않는다.

| No. | Test | No. | Test |
|---:|---|---:|---|
| 1 | Complete blood count | 21 | Urinalysis |
| 2 | C-reactive protein | 22 | Urine culture |
| 3 | Erythrocyte sedimentation rate | 23 | Urine pregnancy test |
| 4 | Serum electrolytes | 24 | Blood culture |
| 5 | Blood glucose | 25 | Stool culture |
| 6 | Hemoglobin A1c | 26 | Stool occult blood test |
| 7 | Serum creatinine | 27 | Sputum culture |
| 8 | Blood urea nitrogen | 28 | Respiratory pathogen PCR panel |
| 9 | Liver function panel | 29 | Electrocardiography |
| 10 | Serum bilirubin | 30 | Chest radiography |
| 11 | Serum lipase | 31 | Abdominal ultrasonography |
| 12 | Cardiac troponin | 32 | Pelvic ultrasonography |
| 13 | B-type natriuretic peptide | 33 | Echocardiography |
| 14 | D-dimer | 34 | Abdominal and pelvic CT |
| 15 | Thyroid-stimulating hormone | 35 | Brain CT |
| 16 | Free thyroxine | 36 | Brain MRI |
| 17 | Serum cortisol | 37 | CT pulmonary angiography |
| 18 | Serum ferritin | 38 | Upper gastrointestinal endoscopy |
| 19 | Vitamin B12 level | 39 | Colonoscopy |
| 20 | Coagulation profile | 40 | Spirometry |

검사 이름만 준비하며 질환별 검사 계획 관계는 후속 문헌 추출과 검토에서 정한다. 검사 이상 결과를 ExamFinding에 섞지 않는다.

## ExamMethod — 50 terms

1–24번은 현재 기초 어휘의 영어 명칭을 그대로 유지하고 25–50번은 추가 후보로 둔다. 시진·촉진·타진·청진, 기본 신경학적 진찰과 활력징후·침상 평가를 포함한다. Straight leg raise test·Romberg test는 신체진찰 방법 후보이며 앞의 Test 객체와 구분한다.

활력징후 측정과 Pulse oximetry는 침상 평가 방법 후보로 검토한다. 실제 EXAM 요청으로 사용할 수 있는지는 후속 SDK 검증에서 확인하며 목록 존재로 서버 지원을 주장하지 않는다.

| No. | ExamMethod | No. | ExamMethod |
|---:|---|---:|---|
| 1 | Conjunctival inspection | 26 | Blood pressure measurement |
| 2 | Oral inspection | 27 | Orthostatic blood pressure measurement |
| 3 | Pharyngeal inspection | 28 | Pulse rate measurement |
| 4 | Skin inspection | 29 | Respiratory rate measurement |
| 5 | Pupillary light reflex assessment | 30 | Pulse oximetry |
| 6 | Cervical lymph node palpation | 31 | Jugular venous pressure assessment |
| 7 | Thyroid palpation | 32 | Dorsalis pedis pulse palpation |
| 8 | Heart auscultation | 33 | Capillary refill assessment |
| 9 | Lung auscultation | 34 | Carotid auscultation |
| 10 | Abdominal inspection | 35 | Chest percussion |
| 11 | Abdominal auscultation | 36 | Chest expansion assessment |
| 12 | Abdominal percussion | 37 | Abdominal palpation |
| 13 | Epigastric palpation | 38 | Rebound tenderness assessment |
| 14 | Right upper quadrant palpation | 39 | Murphy sign assessment |
| 15 | Left upper quadrant palpation | 40 | Joint effusion assessment |
| 16 | Right lower quadrant palpation | 41 | Muscle strength testing |
| 17 | Left lower quadrant palpation | 42 | Light touch sensation assessment |
| 18 | Right costovertebral angle percussion | 43 | Achilles tendon reflex assessment |
| 19 | Left costovertebral angle percussion | 44 | Plantar response assessment |
| 20 | Radial pulse palpation | 45 | Straight leg raise test |
| 21 | Pretibial pitting assessment | 46 | Romberg test |
| 22 | Knee range of motion assessment | 47 | Finger-to-nose test |
| 23 | Patellar reflex assessment | 48 | Nystagmus assessment |
| 24 | Gait observation | 49 | Neck stiffness assessment |
| 25 | Body temperature measurement | 50 | Otoscopy |

검증 후 채택할 ExamMethod에는 기존 계약에 따라 구체적인 한국어 단일 진찰 요청문을 준비한다. 이번에는 새 examRequestText나 detectedBy 관계를 생성하지 않는다.

## 사용자 검토와 후속 과제

사용자는 2026-10-12 일곱 객체의 영어 어휘 목록을 승인하고 이를 기반으로 후속 작업을 진행하도록 선택했다. 어휘 승인 대기는 종료한다. 다음 과제는 승인된 목록에 기반한 Pydantic 추출 스키마와 준비·검증 계약의 구체화이며, gpt-6-luna·medium 추출 파일럿은 그 계약을 정한 뒤 별도 범위에서 진행한다. 기존 의료 어휘 데이터베이스를 통한 확장은 현재 가능성 검토와 방향 제안 단계이며, 추가 용어·외부 코드·출처별 관계는 이번 승인에 포함된 항목으로 간주하지 않는다.

