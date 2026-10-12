from dataclasses import dataclass

from knowledge.graph import ClinicalKnowledge

from .gateway import InputGateway
from .interface import InterfaceAgent


@dataclass
class Resources:
    knowledge: ClinicalKnowledge
    gateway: InputGateway
    interface: InterfaceAgent
