# v5.0 전체 원천 배치 검토

- 빌드: `b4954e33d5c04f4d76949149d9bf6affec1d2ab8c4b34fa99085003933d346aa`
- 후보 집합 SHA-256: `b03983497c4ed8246ff16d61de6bb8f9f4cb4bdd34c5c9b3694e2b2910c74151`
- Association 후보: 9,400
- Registry 항목: 1,701

이 파일과 review-batch.json은 승인 요청 자료다. approved=false이며 자동 승인하지 않는다.

검토 대상은 식별자와 임상 역할, 변형의 모든 조건, 관계 그룹, 두 방향 likelihood와 충돌, 모델 정규화 후보다.
보류된 연결 소견·단위·역할·진찰 방법은 실행 자산에 포함하지 않는다.

## 원천별 처리

| 입력 | 행 수 |
|---|---:|
| LICENSE | 1 |
| der2_Refset_123451000267106SimpleRefsetSnapshot_KR1000267_20260615.txt | 150 |
| der2_Refset_123471000267104SimpleRefsetSnapshot_KR1000267_20260615.txt | 112 |
| der2_Refset_123481000267101SimpleRefsetSnapshot_KR1000267_20260615.txt | 131 |
| der2_Refset_123491000267103SimpleRefsetSnapshot_KR1000267_20260615.txt | 209 |
| der2_Refset_123501000267108SimpleRefsetSnapshot_KR1000267_20260615.txt | 16,532 |
| der2_Refset_123511000267106SimpleRefsetSnapshot_KR1000267_20260615.txt | 164 |
| der2_Refset_123531000267103SimpleRefsetSnapshot_KR1000267_20260615.txt | 71 |
| der2_Refset_123541000267105SimpleRefsetSnapshot_KR1000267_20260615.txt | 75 |
| der2_Refset_123551000267107SimpleRefsetSnapshot_KR1000267_20260615.txt | 338 |
| der2_Refset_123561000267109SimpleRefsetSnapshot_KR1000267_20260615.txt | 122 |
| der2_Refset_123571000267100SimpleRefsetSnapshot_KR1000267_20260615.txt | 117 |
| der2_Refset_123581000267102SimpleRefsetSnapshot_KR1000267_20260615.txt | 119 |
| der2_Refset_123591000267104SimpleRefsetSnapshot_KR1000267_20260615.txt | 159 |
| der2_Refset_123601000267109SimpleRefsetSnapshot_KR1000267_20260615.txt | 201 |
| der2_Refset_123631000267104SimpleRefsetSnapshot_KR1000267_20260615.txt | 132 |
| der2_Refset_123641000267106SimpleRefsetSnapshot_KR1000267_20260615.txt | 145 |
| der2_Refset_123651000267108SimpleRefsetSnapshot_KR1000267_20260615.txt | 90 |
| der2_Refset_123661000267105SimpleRefsetSnapshot_KR1000267_20260615.txt | 215 |
| der2_Refset_123671000267101SimpleRefsetSnapshot_KR1000267_20260615.txt | 143 |
| der2_Refset_123681000267103SimpleRefsetSnapshot_KR1000267_20260615.txt | 370 |
| der2_Refset_123691000267100SimpleRefsetSnapshot_KR1000267_20260615.txt | 59 |
| der2_Refset_123701000267100SimpleRefsetSnapshot_KR1000267_20260615.txt | 101 |
| der2_Refset_133321000267105SimpleRefsetSnapshot_KR1000267_20260615.txt | 159 |
| der2_Refset_133331000267108SimpleRefsetSnapshot_KR1000267_20260615.txt | 170 |
| der2_Refset_133341000267101SimpleRefsetSnapshot_KR1000267_20260615.txt | 272 |
| der2_Refset_143331000267109SimpleRefsetSnapshot_KR1000267_20260615.txt | 62 |
| der2_Refset_163351000267107SimpleRefsetSnapshot_KR1000267_20260615.txt | 257 |
| der2_Refset_163361000267109SimpleRefsetSnapshot_KR1000267_20260615.txt | 151 |
| der2_Refset_163371000267100SimpleRefsetSnapshot_KR1000267_20260615.txt | 86 |
| der2_Refset_163381000267102SimpleRefsetSnapshot_KR1000267_20260615.txt | 63 |
| der2_Refset_245351000267103SimpleRefsetSnapshot_KR1000267_20260615.txt | 4 |
| der2_Refset_245361000267101SimpleRefsetSnapshot_KR1000267_20260615.txt | 6 |
| der2_Refset_245371000267105SimpleRefsetSnapshot_KR1000267_20260615.txt | 5 |
| der2_Refset_245381000267108SimpleRefsetSnapshot_KR1000267_20260615.txt | 5 |
| der2_Refset_245391000267106SimpleRefsetSnapshot_KR1000267_20260615.txt | 4 |
| der2_Refset_245401000267108SimpleRefsetSnapshot_KR1000267_20260615.txt | 6 |
| der2_Refset_245411000267106SimpleRefsetSnapshot_KR1000267_20260615.txt | 10 |
| der2_Refset_245421000267101SimpleRefsetSnapshot_KR1000267_20260615.txt | 11 |
| der2_Refset_245431000267103SimpleRefsetSnapshot_KR1000267_20260615.txt | 4 |
| der2_Refset_245441000267105SimpleRefsetSnapshot_KR1000267_20260615.txt | 8 |
| der2_Refset_245451000267107SimpleRefsetSnapshot_KR1000267_20260615.txt | 3 |
| der2_Refset_245461000267109SimpleRefsetSnapshot_KR1000267_20260615.txt | 6 |
| der2_Refset_245471000267100SimpleRefsetSnapshot_KR1000267_20260615.txt | 6 |
| der2_Refset_245481000267102SimpleRefsetSnapshot_KR1000267_20260615.txt | 8 |
| der2_Refset_336541000267106SimpleRefsetSnapshot_KR1000267_20260615.txt | 72 |
| der2_Refset_336561000267105SimpleRefsetSnapshot_KR1000267_20260615.txt | 52 |
| der2_Refset_336571000267101SimpleRefsetSnapshot_KR1000267_20260615.txt | 15 |
| der2_Refset_336581000267103SimpleRefsetSnapshot_KR1000267_20260615.txt | 11 |
| der2_Refset_336861000267107SimpleRefsetSnapshot_KR1000267_20260615.txt | 14 |
| der2_Refset_337021000267109SimpleRefsetSnapshot_KR1000267_20260615.txt | 4 |
| der2_Refset_337031000267107SimpleRefsetSnapshot_KR1000267_20260615.txt | 18 |
| der2_Refset_366811000267103SimpleRefsetSnapshot_KR1000267_20260615.txt | 4 |
| der2_Refset_376561000267108SimpleRefsetSnapshot_KR1000267_20260615.txt | 49 |
| der2_Refset_376581000267101SimpleRefsetSnapshot_KR1000267_20260615.txt | 41 |
| der2_Refset_387131000267102SimpleRefsetSnapshot_KR1000267_20260615.txt | 167 |
| der2_Refset_SimpleSnapshot_INT_20260501.txt | 22,570 |
| der2_cRefset_AssociationSnapshot_INT_20260501.txt | 225,522 |
| der2_cRefset_AssociationSnapshot_KR1000267_20260615.txt | 25 |
| der2_cRefset_AttributeValueSnapshot_INT_20260501.txt | 739,505 |
| der2_cRefset_AttributeValueSnapshot_KR1000267_20260615.txt | 2,005 |
| der2_cRefset_LanguageSnapshot-en_INT_20260501.txt | 3,337,412 |
| der2_cRefset_LanguageSnapshot-en_KR1000267_20260615.txt | 5,261 |
| der2_cRefset_LanguageSnapshot-ko_KR1000267_20260615.txt | 57,591 |
| der2_cRefset_MRCMModuleScopeSnapshot_INT_20260501.txt | 3 |
| der2_cciRefset_RefsetDescriptorSnapshot_INT_20260501.txt | 207 |
| der2_cciRefset_RefsetDescriptorSnapshot_KR1000267_20260615.txt | 61 |
| der2_ciRefset_DescriptionTypeSnapshot_INT_20260501.txt | 3 |
| der2_ciRefset_DescriptionTypeSnapshot_KR1000267_20260615.txt | 0 |
| der2_cissccRefset_MRCMAttributeDomainSnapshot_INT_20260501.txt | 175 |
| der2_iisssccRefset_ExtendedMapSnapshot_INT_20260501.txt | 216,605 |
| der2_sRefset_SimpleMapSnapshot_INT_20260501.txt | 559,164 |
| der2_scsRefset_ComponentAnnotationStringValueSnapshot_INT_20260501.txt | 5,630 |
| der2_scsRefset_ComponentAnnotationStringValueSnapshot_KR1000267_20260615.txt | 0 |
| der2_ssRefset_ModuleDependencySnapshot_INT_20260501.txt | 3 |
| der2_ssRefset_ModuleDependencySnapshot_KR1000267_20260615.txt | 2 |
| der2_ssccRefset_MRCMAttributeRangeSnapshot_INT_20260501.txt | 153 |
| der2_sscsRefset_MemberAnnotationStringValueSnapshot_INT_20260501.txt | 0 |
| der2_sscsRefset_MemberAnnotationStringValueSnapshot_KR1000267_20260615.txt | 0 |
| der2_sssssssRefset_MRCMDomainSnapshot_INT_20260501.txt | 23 |
| edges_has_prerequisite.csv | 53 |
| edges_is_influenced_by.csv | 1,020 |
| edges_present_in.csv | 10,352 |
| edges_related_to.csv | 221 |
| edges_treated_by.csv | 1,558 |
| nodes_condition.csv | 779 |
| nodes_speciality.csv | 39 |
| nodes_symptom.csv | 4,037 |
| original_readme.md | 1 |
| release_package_information.json | 1 |
| sct2_Concept_Snapshot_INT_20260501.txt | 531,997 |
| sct2_Concept_Snapshot_KR1000267_20260615.txt | 2,007 |
| sct2_Description_Snapshot-en_INT_20260501.txt | 1,704,584 |
| sct2_Description_Snapshot-en_KR1000267_20260615.txt | 5,258 |
| sct2_Description_Snapshot-ko_KR1000267_20260615.txt | 57,555 |
| sct2_Identifier_Snapshot_INT_20260501.txt | 0 |
| sct2_Identifier_Snapshot_KR1000267_20260615.txt | 0 |
| sct2_RelationshipConcreteValues_Snapshot_INT_20260501.txt | 37,481 |
| sct2_RelationshipConcreteValues_Snapshot_KR1000267_20260615.txt | 3 |
| sct2_Relationship_Snapshot_INT_20260501.txt | 3,564,963 |
| sct2_Relationship_Snapshot_KR1000267_20260615.txt | 10,684 |
| sct2_StatedRelationship_Snapshot_INT_20260501.txt | 1,024,719 |
| sct2_StatedRelationship_Snapshot_KR1000267_20260615.txt | 0 |
| sct2_TextDefinition_Snapshot-en_INT_20260501.txt | 19,044 |
| sct2_TextDefinition_Snapshot-en_KR1000267_20260615.txt | 3 |
| sct2_TextDefinition_Snapshot-ko_KR1000267_20260615.txt | 35 |
| sct2_sRefset_OWLExpressionSnapshot_INT_20260501.txt | 414,249 |
| sct2_sRefset_OWLExpressionSnapshot_KR1000267_20260615.txt | 2,011 |

## 증상 변형 처리

| 결과 | 수 |
|---|---:|
| accepted_preview | 2,698 |
| characteristic_meaning_unresolved | 502 |
| exam_method_not_reviewed | 8 |
| frequency_window_unresolved | 14 |
| laterality_location_scope_unresolved | 8 |
| linked_finding_deferred | 36 |
| severity_conditions_or_units_unresolved | 41 |
| target_identifier_unverified | 72 |
| target_role_unresolved | 648 |
| temporal_expression_unresolved | 10 |

상세 원천 행·정규화·판단은 ontology.sqlite3의 source_rows, normalizations, dispositions, source_assertions에서 확인한다.
sources.json은 실행 후보의 원천 주장을, registry.json은 매핑과 명칭을, target-roles.json은 전체 발견 역할을 담는다.
disease-target-coverage.csv는 질환과 Target별 연관 수를 제공한다. source_assertions와 normalizations에서 선택 평가·정규화 규칙·예외를 대조한다.
승인 시 approved_associations와 approved_registry에 실제 승인한 항목을 지정하고 required_rules를 검토한다.
임상 문진·진찰 요청·치료·교육 문구 작성과 실제 진단 성능 검증은 이 배치에 포함하지 않는다.
