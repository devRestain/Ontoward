# Workflow Rule Index

Use D17 for current policies and D08/D12/D13/D14 for preserved ontology, wire, responsibility, and packaging boundaries. Definitions live in Python. Behavioral checks below belong to Dev/tests/workflow/test_workflow.py; actual admitted RDF and independent archives use test_admitted.py. compare_traces.py remains the historical D13 behavior-preserving comparison and is not a D17 equality gate. See D17_REVIEW_ADOPTION.md for the two supplied reviews and adoption boundaries.

| ID | Rule and owner | Behavioral acceptance |
|---|---|---|
| WF-01 | Consultation preserves five sessions and handles pending input first | test_full_five_session_workflow; test_budget_keeps_pending_done_and_plans |
| WF-02 | graph.run_node retains validated copied-state and action replay boundary | test_node_validation_does_not_replay_completed_external_action |
| QP-01 | QuestionLifecycle atomically registers/discards placeholders and references | test_discard_batch_rejects_pending_and_done_without_partial_changes |
| QP-02 | InterviewPlanner distinguishes asked from resolved and bounds clarification | test_asked_history_does_not_resolve_unknown_or_empty_attribute |
| QP-03 | Core HPI precedes Open Inquiry and bounded ROS within original systems | test_focused_ros_union_limits_order_and_cross_system_retrieval; test_ros_full_flow_explicit_negative_and_unknown |
| QP-04 | Replan by evidence revision, block absent attributes, and reconsider undelivered questions | test_d17_absent_target_attributes_and_reconsideration |
| BD-01 | BudgetPolicy shares actions and protects reply/finalization/education capacity | test_d17_shared_action_pool_and_response_window; test_shared_budget_reserves_one_gateway_without_render_cost |
| BD-02 | Recheck before transmission and preserve last-turn submission | test_injected_clock_expires_collection_between_framing_and_execution; test_closed_expired_reserve_and_fiftieth_turn |
| IN-01 | InputInterpreter validates current quotes, type, references, and corrections | test_fact_grounding_and_correction_boundary; test_contextual_correction_preserves_episode_and_quote |
| IN-02 | Validate independent facts and quarantine invalid dependencies atomically | test_d17_partial_facts_and_atomic_correction_dependencies |
| IN-03 | InteractionLifecycle projects bounded original episode/source context | test_d17_context_is_bounded_and_retains_old_episode_source; test_actual_korean_context_short_answer_and_case_isolation |
| IN-04 | Bound vocabulary construction and one preserving recovery | test_parser_vocabulary_bounds_and_required_question_values; test_parser_expands_once_and_preserves_first_valid_facts |
| IN-05 | Interpret only exact prepared replies and reject unqualified composite links | test_d17_composite_guard_and_exact_duration_reply; test_strict_reply_vs_compound_free_text |
| AC-01 | Doctor validates prepared NFC text and never generates utterances | test_prepared_doctor_validates_and_delivers_without_model_calls; test_nfc_length_and_test_block |
| RT-01 | RequestExecutor preserves IDs/payloads, delays, timeouts, and once-only usage | test_transport_identity_delays_timeout_and_usage_once; test_action_retries_and_response_format_new_identity |
| CL-01 | Shared Pattern matching is reused and invalidated by corrections | test_d17_shared_pattern_cache_and_correction_invalidation |
| CL-02 | Preserve source refinement replacement, joint deltas, typed conditions, and episode boundaries | test_v5_shared_patterns_refinement_replacement_and_joint_deltas; test_v5_typed_time_bases_units_and_episode_boundaries |
| CL-03 | Match applicability and never activate unknown conditions | test_v5_applicability_is_required_and_unknown_is_not_support |
| CL-04 | Bound source-typicality absence penalties within active episodes | test_d17_bounded_typicality_absence_and_episode_isolation |
| CL-05 | Require complete current-chief explanation for final Disease eligibility | test_d17_primary_requires_current_chief_explanation; test_differential_shares_support_policy_and_excludes_primary |
| ED-01 | Preserve delivered education through parser failure and prioritize changed-diagnosis correction | test_delivered_education_survives_gateway_failure; test_new_fact_during_education_changes_remaining_delivery |
| SB-01 | Preserve fifteen SOAP strings, separate diagnosis, context, and byte limits | test_soap_exact_fields_bytes_and_doctor_requirement; test_soap_preserves_subject_time_episode_values_and_calendar_units |
| SB-02 | Bound SOAP repair and require completed DIAGNOSE | test_soap_reconstruction_local_and_server; test_submission_unknown_keeps_exact_payload |
| PK-01 | Preserve SDK bytes, package boundaries, hashes, and local-only knowledge paths | test_packaging_configured_texts_and_exclusions; test_knowledge_paths_hashes_and_missing_manifest |
| PK-02 | Keep shared knowledge patient-free and separate case state | test_shared_resources_keep_case_dialogue_separate |
