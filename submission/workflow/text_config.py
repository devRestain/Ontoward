from string import Formatter

from pydantic import BaseModel, ConfigDict
from settings import configured_path


class Texts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    chief_question: str
    unmapped_question: str
    open_question: str
    ros_question: str
    clarification_question: str
    symptom_education: str
    symptom_assessment: str
    unknown_text: str
    missing_question_text: str
    invalid_action_text: str
    unknown_replies: list[str]
    education_acknowledgements: list[str]
    present_replies: list[str]
    absent_replies: list[str]
    reply_trailing_punctuation: str
    status_labels: dict[str, str]
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
    doctor_prompt: str
    texts: Texts

    @classmethod
    def load(cls):
        prompt = configured_path("ONTOWARD_PARSER_PROMPT", "config").read_text(encoding="utf-8").strip()
        doctor = configured_path("ONTOWARD_DOCTOR_PROMPT", "config").read_text(encoding="utf-8").strip()
        texts = Texts.model_validate_json(configured_path("ONTOWARD_TEXTS", "config").read_text(encoding="utf-8"))
        if not prompt or not doctor or set(texts.status_labels) != {"present", "absent", "uncertain", "unknown"}:
            raise ValueError("Missing parser prompt or clinical status labels")
        reply_groups = [set(texts.unknown_replies), set(texts.present_replies), set(texts.absent_replies)]
        if any(not value.strip() for group in reply_groups for value in group) or any(
            left & right for i, left in enumerate(reply_groups) for right in reply_groups[i + 1:]
        ):
            raise ValueError("Fixed clinical replies must be nonempty and unambiguous")
        for name, expected in {"ros_question": {"symptom"}, "exam_turn_format": {"text", "turn"},
                               "initial_exam_format": {"text"}, "education_format": {"text"}, "plan_format": {"text"},
                               "finding_format": {"labels", "status", "text"}, "unlinked_format": {"text", "status"}}.items():
            parts = list(Formatter().parse(getattr(texts, name)))
            fields = {field for _, field, _, _ in parts if field is not None}
            if fields != expected:
                raise ValueError(f"Invalid text placeholders: {name}")
            if any(spec or conversion for _, _, spec, conversion in parts):
                raise ValueError(f"Text placeholders do not support format conversions: {name}")
        return cls(parser_prompt=prompt, doctor_prompt=doctor, texts=texts)
