from string import Formatter

from pydantic import BaseModel, ConfigDict
from settings import configured_path, education_enabled, prompt_paths
from .rules.action import content_error


class Texts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    diagnosis_announcement: str
    diagnosis_announcement_short: str
    symptom_announcement: str
    symptom_announcement_short: str
    symptom_cause_unknown: str
    intake_questions: dict[str, str]
    history_questions: dict[str, str]
    primary_chief_question: str
    open_question: str
    clarification_question: str
    symptom_assessment: str
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
    qualified_scope_label: str
    approximate_label: str
    measurement_format: str
    interval_format: str
    range_format: str
    nrs_format: str
    category_format: str
    exam_turn_format: str
    initial_exam_format: str
    record_separator: str
    record_labels: dict[str, str]
    soap_labels: dict[str, str]


class TextConfig(BaseModel):
    prompts: dict[str, str]
    texts: Texts
    education_enabled: bool = False

    def prompt(self, *routes):
        return '\n\n'.join(self.prompts[route] for route in routes)

    @classmethod
    def load(cls):
        paths = prompt_paths(configured_path('ONTOWARD_PROMPTS', 'config'))
        modules = {path: path.read_text(encoding='utf-8').strip() for parts in paths.values() for path in parts}
        if not all(modules.values()):
            raise ValueError('Empty prompt module')
        prompts = {route: '\n\n'.join(modules[path] for path in parts) for route, parts in paths.items()}
        texts = Texts.model_validate_json(configured_path("ONTOWARD_TEXTS", "config").read_text(encoding="utf-8"))
        if set(texts.status_labels) != {"present", "absent", "uncertain", "unknown"}:
            raise ValueError("Missing clinical status labels")
        if (set(texts.subject_labels) != {"patient", "family"} or set(texts.time_labels) != {"current", "past", "unspecified"}
                or set(texts.operator_labels) != {"eq"}):
            raise ValueError("Missing clinical context or numeric labels")
        if not texts.qualified_scope_label.strip() or not texts.approximate_label.strip():
            raise ValueError("Missing qualification labels")
        if (not {"cc", "hpi", "exam", "tests", "treatment", "disposition", "follow_up", "education"} <= texts.soap_labels.keys()
                or any(not label.strip() for labels in (texts.soap_labels, texts.record_labels)
                       for label in labels.values())):
            raise ValueError("Missing SOAP category labels")
        reply_groups = [set(texts.unknown_replies), set(texts.present_replies), set(texts.absent_replies)]
        if any(not value.strip() for group in reply_groups for value in group) or any(
            left & right for i, left in enumerate(reply_groups) for right in reply_groups[i + 1:]
        ):
            raise ValueError("Fixed clinical replies must be nonempty and unambiguous")
        for name, expected in {"exam_turn_format": {"text", "turn"},
                               "diagnosis_announcement": {"diagnosis"},
                               "diagnosis_announcement_short": {"diagnosis"},
                               "symptom_announcement": {"diagnosis"},
                               "symptom_announcement_short": {"diagnosis"},
                               "initial_exam_format": {"text"},
                               "category_format": {"category", "content"},
                               "range_format": {"lower", "upper", "unit"}, "nrs_format": {"value"},
                               "episode_format": {"number"},
                               "measurement_format": {"operator", "value", "unit"},
                               "interval_format": {"lower_bound", "lower", "upper", "upper_bound"}}.items():
            parts = list(Formatter().parse(getattr(texts, name)))
            fields = {field for _, field, _, _ in parts if field is not None}
            if fields != expected:
                raise ValueError(f"Invalid text placeholders: {name}")
            if any(spec or conversion for _, _, spec, conversion in parts):
                raise ValueError(f"Text placeholders do not support format conversions: {name}")
        for name in ('primary_chief_question', 'open_question', 'clarification_question', 'symptom_cause_unknown'):
            if content_error(getattr(texts, name)):
                raise ValueError(f"Invalid prepared utterance: {name}")
        from .rules.collection import INTAKE, HISTORY
        if set(texts.intake_questions) != set(INTAKE) or set(texts.history_questions) != set(HISTORY):
            raise ValueError("Missing common collection questions")
        if any(content_error(text) for text in [*texts.intake_questions.values(), *texts.history_questions.values()]):
            raise ValueError("Invalid prepared clarification")
        return cls(prompts=prompts, texts=texts, education_enabled=education_enabled())
