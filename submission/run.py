"""NOVA submission entrypoint; clinical execution remains unimplemented."""

from nova_sdk import run_agent
from agents.runtime import consult, prepare


if __name__ == "__main__":
    run_agent(prepare, consult)
