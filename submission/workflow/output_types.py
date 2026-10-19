from typing import Any, Literal

from pydantic import RootModel, StrictStr

from .state.models import Model


class MappingBatch(RootModel[list[dict[StrictStr, Any]]]):
    pass


class SourceQuote(Model):
    document_id: StrictStr
    quote: StrictStr


class PlanRow(Model):
    text: StrictStr
    basis: Literal['guideline', 'model_knowledge', 'mixed']
    references: list[SourceQuote]
    priority: Literal['safety', 'routine']


class RenderedGroup(Model):
    id: StrictStr
    utterances: list[StrictStr]


class EmpathyReply(Model):
    text: StrictStr
