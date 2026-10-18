# Workflow Rule Ownership

D44 replaces duplicated state and transport histories while preserving D38 scoring, D40 budgets, D42 clinical pins, and D43 initial interpretation. Tests below exercise behavior in the project offline dev image; synthetic and saved-response fixtures do not establish model or clinical quality.

| Rule | Runtime owner | Maintained verification |
|---|---|---|
| Three resident owners and disposable current work | state/models.py, graph.py | test_lifecycle.py |
| Question registration leaves facts unchanged; completion removes queue objects | state/questions.py | test_question_registration_and_cancellation_never_write_patient_state; test_answer_replaces_question_and_deduplicates_same_delivery |
| Current-session queues and chief invalidation | interview_planner.py | test_session_caps_and_no_future_session_queue; test_chief_change_invalidates_old_question_binding |
| Always-called context, exact binding, selective mapping | input_interpreter.py, rules/normalization.py | test_binding.py |
| Preserve C03 care notes without empty-candidate calls | rules/input.py | test_prior_care_denial_and_observation_are_notes_without_mapping_calls; replay_c03.py |
| Scope, correction, numeric, acquisition, and family boundaries | rules/input.py, state/models.py | NumericAndScopeTests; test_home_report_cannot_create_exam_and_actual_exam_can; test_explicit_correction_preserves_channel_scope_and_audit |
| Scoped value names and independent facts | knowledge/graph.py | test_attribute_scoped_value_names_never_cross_attributes; test_multiple_targets_scopes_and_attribute_values_stay_independent |
| Actual and hypothetical kernel equality | clinical_reasoner.py, state/evidence.py | test_reasoning.py; compare_algorithms.py |
| Refinement, episode, prerequisites, and open-world values | clinical_reasoner.py | test_refinement_replaces_parent_and_duplicate_facts_do_not_inflate; test_conditional_pattern_requires_true_prerequisite; test_categorical_any_all_open_world_truth_tables |
| Joint utility without premature support | rules/selection.py | test_joint_two_and_three_step_question_value_without_premature_support |
| Single actual cache and local simulations | clinical_reasoner.py, rules/selection.py | test_one_reasoner_shared_and_only_latest_snapshot_retained; test_question_simulations_are_local_and_do_not_change_patient_or_actual_cache |
| Shared usage and protected budgets | rules/budget.py, state/usage.py | test_budget_evaluation_is_pure_and_preserves_open_inquiry; test_empathy_reserves_three_calls_and_separate_action_accounting |
| Fixed diagnosis, English plan, Korean groups, transcript-only replies | education.py, doctor.py | test_delivery.py |
| Current-call ModelResult and bounded retries | io/model_client.py, io/request_executor.py | test_transport.py |
| Current SOAP, one repair, completed receipt | submission_writer.py | test_submission_payload_is_local_until_confirmed; test_soap_repair_has_one_local_payload_and_new_request_id; test_server_soap_repair_and_unconfirmed_submission_boundaries |
| Observation cannot affect or replay execution | audit.py; Test/observe.py | test_cold_cache_and_audit_parity; Test/test_observer.py |
| Admitted assets, Korean, Context and acquired EXAM through SOAP | runtime.py | test_admitted.py |
| Independent artifact and unchanged original SDK | Dev/packaging/package_submission.py; Test harness | D44 extracted archive and local HTTP evidence in data/provenance/state-lifecycle-d44-2026-10-18.json |

Use root compose.yaml plus Dev/tests/workflow/compose.offline.yaml for maintained Python checks. Keep tests outside the submission artifact. Preserve frozen prior tests and receipts as historical evidence rather than adding runtime compatibility layers.
