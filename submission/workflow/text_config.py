from string import Formatter

from pydantic import BaseModel, ConfigDict
from settings import configured_path
from .rules.action import content_error


class Texts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chief_question: str
    unmapped_question: str
    open_question: str
    clarification_question: str
    clarification_questions: dict[str, str]
    symptom_education: str
    symptom_assessment: str
    provisional_education: str
    understanding_question: str
    correction_education: str
    unknown_text: str
    missing_question_text: str
    invalid_action_text: str
    unknown_replies: list[str]
    education_acknowledgements: list[str]
    present_replies: list[str]
    absent_replies: list[str]
    reply_trailing_punctuation: str
    status_labels: dict[str, str]
    subject_labels: dict[str, str]
    time_labels: dict[str, str]
    unit_labels: dict[str, str]
    operator_labels: dict[str, str]
    episode_format: str
    clinical_context_format: str
    measurement_format: str
    interval_format: str
    education_format: str
    plan_format: str
    finding_format: str
    unlinked_format: str
    exam_turn_format: str
    initial_exam_format: str
    label_separator: str
    test_separator: str
    record_separator: str


class TextConfig(BaseModel):
    parser_prompt: str
    texts: Texts

    @classmethod
    def load(cls):
        prompt = configured_path("ONTOWARD_PARSER_PROMPT", "config").read_text(encoding="utf-8").strip()
        texts = Texts.model_validate_json(configured_path("ONTOWARD_TEXTS", "config").read_text(encoding="utf-8"))
        if not prompt or set(texts.status_labels) != {"present", "absent", "uncertain", "unknown"}:
            raise ValueError("Missing parser prompt or clinical status labels")
        if (set(texts.subject_labels) != {"patient", "family"} or set(texts.time_labels) != {"current", "past", "unspecified"}
                or set(texts.operator_labels) != {"eq", "lt", "le", "gt", "ge"}):
            raise ValueError("Missing clinical context or numeric labels")
        reply_groups = [set(texts.unknown_replies), set(texts.present_replies), set(texts.absent_replies)]
        if any(not value.strip() for group in reply_groups for value in group) or any(
            left & right for i, left in enumerate(reply_groups) for right in reply_groups[i + 1:]
        ):
            raise ValueError("Fixed clinical replies must be nonempty and unambiguous")
        for name, expected in {"exam_turn_format": {"text", "turn"},
                               "initial_exam_format": {"text"}, "education_format": {"text"}, "plan_format": {"text"},
                               "finding_format": {"labels", "status", "text"}, "unlinked_format": {"text", "status"},
                               "episode_format": {"number"}, "clinical_context_format": {"subject", "time", "episode"},
                               "measurement_format": {"operator", "value", "unit"},
                               "interval_format": {"lower_bound", "lower", "upper", "upper_bound"}}.items():
            parts = list(Formatter().parse(getattr(texts, name)))
            fields = {field for _, field, _, _ in parts if field is not None}
            if fields != expected:
                raise ValueError(f"Invalid text placeholders: {name}")
            if any(spec or conversion for _, _, spec, conversion in parts):
                raise ValueError(f"Text placeholders do not support format conversions: {name}")
        for name in ("chief_question", "unmapped_question", "open_question", "clarification_question",
                     "symptom_education", "provisional_education", "understanding_question", "correction_education"):
            if content_error(getattr(texts, name)):
                raise ValueError(f"Invalid prepared utterance: {name}")
        if any(content_error(text) for text in texts.clarification_questions.values()):
            raise ValueError("Invalid prepared clarification")
        return cls(parser_prompt=prompt, texts=texts)
