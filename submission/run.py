"""Expose the NOVA preparation and consultation callbacks."""

from nova_sdk import run_agent
from workflow.runtime import consult, prepare


if __name__ == "__main__":
    run_agent(prepare, consult)
