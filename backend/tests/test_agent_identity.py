"""Contratos compartidos de identidad, detalle y concurrencia de agentes."""

import pytest
from pydantic import ValidationError

from app.agents.api_agent import ApiAgent
from app.agents.architecture import ArchitectureAgent
from app.agents.database import DatabaseAgent
from app.agents.devops import DevOpsAgent
from app.agents.frontend_agent import FrontendAgent
from app.agents.logic import LogicAgent
from app.agents.stack import StackAgent
from app.config import Settings
from app.services.orchestrator import _chunk_agents


def test_specialists_use_historical_internal_names_and_reconstruction_contract():
    expected = {
        StackAgent: "hopper",
        ArchitectureAgent: "kay",
        DatabaseAgent: "liskov",
        ApiAgent: "fielding",
        FrontendAgent: "lamarr",
        LogicAgent: "knuth",
        DevOpsAgent: "conway",
    }

    for agent_type, agent_name in expected.items():
        agent = object.__new__(agent_type)
        assert agent.agent_name == agent_name
        assert "CONTRATO DE RECONSTRUCCIÓN" in agent.system_prompt
        assert "tantos diagramas Mermaid como sean necesarios" in agent.system_prompt
        assert "### Criterios de aceptación" in agent.system_prompt
        assert "### Evidencias y desconocidos" in agent.system_prompt


@pytest.mark.parametrize("field", ["llm_agent_batch_size", "llm_max_concurrency"])
def test_configuration_rejects_more_than_three_concurrent_calls(field):
    with pytest.raises(ValidationError):
        Settings(**{field: 4})


def test_agent_batches_are_hard_capped_at_three(monkeypatch):
    monkeypatch.setattr("app.services.orchestrator.settings.llm_max_concurrency", 3)
    agents = list(range(7))

    assert [len(batch) for batch in _chunk_agents(agents, 99)] == [3, 3, 1]
