import json

from ..rules.limits import LIMITS
from .models import ActionSpec, ClinicalValue, InteractionEntry


class InteractionLifecycle:
    def __init__(self, new_request_id):
        self.new_request_id = new_request_id

    def select_question(self, state, question):
        state.interaction.selected = ActionSpec(question=question, content=question.text, request_id=self.new_request_id())

    @staticmethod
    def clear_selected(state, ids=None):
        selected = state.interaction.selected
        if ids is None or (selected and selected.question.item_id in ids):
            state.interaction.selected = None

    @staticmethod
    def begin_action(state):
        action = state.interaction.selected
        state.interaction.selected = None
        state.interaction.pending = action
        return action

    @staticmethod
    def record_action_attempt(state, action):
        entry = InteractionEntry(id=action.request_id, kind=action.question.kind,
            question=action.question.model_copy(deep=True),
            request={"request_id": action.request_id, "action": action.question.kind, "content": action.content})
        state.interaction.history.append(entry)
        return entry

    @staticmethod
    def record_submission_attempt(state, request):
        entry = InteractionEntry(id=request["request_id"], kind="DIAGNOSE", request=request)
        state.interaction.history.append(entry)
        return entry

    @staticmethod
    def receive_input(state, raw):
        state.interaction.incoming = raw

    def record_delivery(self, state, action, entry, response, raw):
        entry.turn = response.turn
        entry.delivered = True
        self.receive_input(state, raw)
        if action.question.purpose == "education":
            item = state.case.get(action.question.item_id)
            if item:
                item.status = "done"
                item.value = ClinicalValue(kind="education", text=action.content, status="present")
                item.source_refs = [entry.id]
            state.interaction.explained_revision = state.interaction.diagnosis_revision
            if action.question.item_id.startswith("Education:correction:"):
                state.interaction.correction_required = False
                state.interaction.correction_count += 1

    @staticmethod
    def project_context(state, question, concepts, *, expanded=False):
        record_limit = LIMITS.expanded_context_records if expanded else LIMITS.context_records
        turn_limit = LIMITS.expanded_context_turns if expanded else LIMITS.context_turns
        byte_limit = LIMITS.expanded_context_bytes if expanded else LIMITS.context_bytes
        ranks = {entry.id: index for index, entry in enumerate(state.interaction.history)}
        candidates = []
        for field, item in state.case.entries():
            if not field.startswith(("S.", "O.")):
                continue
            current = question is not None and item.id == question.item_id
            related = bool(item.value and ((question and question.observation_id
                        and item.value.observation_id == question.observation_id
                        and item.value.episode_id == question.episode_id)
                        or (question and not question.observation_id and question.target_id in item.value.concept_ids
                            and question.subject == item.value.subject)
                        or set(item.value.concept_ids) & set(concepts)))
            recency = max((ranks.get(ref, -1) for ref in item.source_refs), default=-1)
            if current or related or expanded or recency >= len(ranks) - 2:
                candidates.append((not current, not related, -recency, item.id, field, item))
        projected = {"records": [], "dialogue": []}
        refs = []
        def append(kind, item):
            proposed = {**projected, kind: [*projected[kind], item]}
            if len(json.dumps(proposed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) <= byte_limit:
                projected[kind].append(item)
                return True
            return False
        for *_, field, item in sorted(candidates):
            if len(projected["records"]) >= record_limit:
                break
            if append("records", {"field": field, **item.model_dump()}):
                refs.extend([*item.source_refs, *item.context_refs])
        dialogue = state.interaction.dialogue()
        current_id = state.interaction.pending.request_id if state.interaction.pending else "initial"
        priority = list(dict.fromkeys([*refs, *(turn["id"] for turn in reversed(dialogue[-2:]))]))
        if expanded:
            priority.extend(turn["id"] for turn in reversed(dialogue) if turn["id"] not in priority)
        by_id = {turn["id"]: turn for turn in dialogue}
        for ident in priority:
            if len(projected["dialogue"]) >= turn_limit:
                break
            if ident in by_id and ident != current_id:
                append("dialogue", by_id[ident])
        return projected

    @staticmethod
    def record_initial(state, raw):
        state.interaction.history.append(InteractionEntry(id="initial", kind="initial", response=raw))

    @staticmethod
    def consume_input(state):
        state.interaction.pending = None
        state.interaction.incoming = None

    @staticmethod
    def request_clarification(state, question):
        state.interaction.needs_clarification = True
        state.interaction.clarification_target = question.model_copy(deep=True) if question else None

    @staticmethod
    def consume_clarification(state):
        state.interaction.needs_clarification = False
        state.interaction.clarification_target = None
