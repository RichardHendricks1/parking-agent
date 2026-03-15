import json

from mini_nanobot.agent import MiniAgent
from mini_nanobot.session import SessionStore
from mini_nanobot.tools import Tool, ToolRegistry


class _DummyTool(Tool):
    name = "dummy_tool"
    description = "dummy"
    parameters = {
        "type": "object",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
    }

    def run(self, **kwargs):
        return json.dumps({"echo": kwargs.get("value")})


class _DummyPlanningTool(Tool):
    name = "analyze_planning_log"
    description = "planning"
    parameters = {
        "type": "object",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
    }

    def run(self, **kwargs):
        return json.dumps(
            {
                "planning": kwargs.get("value"),
                "module_diagnosis": {
                    "primary_module": "planning",
                    "confidence_0_to_1": 0.88,
                    "reason": "Primary suspect is planning.",
                },
            }
        )


class _FakeProvider:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = 0

    def chat(self, messages, tools, *, max_tokens, temperature):
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return self.responses[idx]


class _PromptAwareProvider:
    def __init__(self):
        self.calls = 0

    def chat(self, messages, tools, *, max_tokens, temperature):
        self.calls += 1
        if self.calls == 1:
            return _tool_call_response(tool_name="analyze_planning_log")
        if self.calls == 2:
            return _assistant_response("first conclusion")
        assert "module_diagnosis" in messages[-1]["content"]
        assert "primary_module、confidence_0_to_1 和 reason" in messages[-1]["content"]
        return _assistant_response("refined with module diagnosis")


def _tool_call_response(tool_name: str = "dummy_tool"):
    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": tool_name,
                                "arguments": "{\"value\": 1}",
                            },
                        }
                    ],
                }
            }
        ]
    }


def _assistant_response(content: str):
    return {"choices": [{"message": {"role": "assistant", "content": content}}]}


def _build_agent(tmp_path, provider, rounds: int, planning_tool: bool = False):
    tools = ToolRegistry()
    if planning_tool:
        tools.register(_DummyPlanningTool())
    else:
        tools.register(_DummyTool())
    session = SessionStore(tmp_path, "cli:test")
    return MiniAgent(
        provider=provider,
        tools=tools,
        session=session,
        max_iterations=8,
        post_tool_analysis_rounds=rounds,
    )


def test_agent_runs_two_post_tool_rounds_when_configured(tmp_path):
    provider = _FakeProvider(
        [
            _tool_call_response(tool_name="analyze_planning_log"),
            _assistant_response("first conclusion"),
            _assistant_response("refined conclusion"),
        ]
    )
    agent = _build_agent(tmp_path, provider, rounds=2, planning_tool=True)

    out = agent.chat_once("analyze")

    assert out == "refined conclusion"
    assert provider.calls == 3


def test_agent_stops_after_single_post_tool_round_when_configured(tmp_path):
    provider = _FakeProvider(
        [
            _tool_call_response(tool_name="analyze_planning_log"),
            _assistant_response("only conclusion"),
            _assistant_response("should not be used"),
        ]
    )
    agent = _build_agent(tmp_path, provider, rounds=1, planning_tool=True)

    out = agent.chat_once("analyze")

    assert out == "only conclusion"
    assert provider.calls == 2


def test_agent_does_not_run_extra_rounds_for_non_target_tool(tmp_path):
    provider = _FakeProvider(
        [
            _tool_call_response(tool_name="dummy_tool"),
            _assistant_response("plain conclusion"),
            _assistant_response("should not be used"),
        ]
    )
    agent = _build_agent(tmp_path, provider, rounds=3, planning_tool=False)

    out = agent.chat_once("analyze")

    assert out == "plain conclusion"
    assert provider.calls == 2


def test_agent_refinement_prompt_mentions_module_diagnosis_fields(tmp_path):
    provider = _PromptAwareProvider()
    agent = _build_agent(tmp_path, provider, rounds=2, planning_tool=True)

    out = agent.chat_once("analyze")

    assert out == "refined with module diagnosis"
    assert provider.calls == 3
