from dataclasses import dataclass

from knowledge.graph import ClinicalKnowledge

from .config import TextConfig
from .gateway import InputGateway
from .interface import InterfaceAgent


@dataclass
class Resources:
    knowledge: ClinicalKnowledge
    config: TextConfig
    gateway: InputGateway
    interface: InterfaceAgent
