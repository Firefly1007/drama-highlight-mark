"""V2 LangGraph 装配与 PostgreSQL checkpoint。"""

from __future__ import annotations

import os
from contextlib import ExitStack
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from drama_interaction.config import Settings, load_settings
from drama_interaction.context import DramaContext
from drama_interaction.llm import LLMGateway
from drama_interaction.schemas.candidate import (
    Abstention,
    Candidate,
    RevealAnchor,
    SpecialistResult,
    TriggerAnchor,
)
from drama_interaction.schemas.evidence import (
    DerivedObservation,
    EvidenceDocument,
    EvidenceProvenance,
    Observation,
    QuerySpan,
    TranscriptSegment,
)
from drama_interaction.schemas.interaction import (
    CommentMood,
    DeferredVotePayload,
    EmotionButtonName,
    EmotionButtonPayload,
    FinalInteraction,
    InstantVotePayload,
    InteractionType,
    RepeatKeylinePayload,
    SideCommentPayload,
)

from .nodes import (
    adapter_node,
    build_specialist_subgraph,
    constraints_node,
    final_check_node,
    has_evidence,
    human_gate_node,
    media_prepare_node,
    needs_human,
    pool_node,
    render_evidence_node,
    render_node,
    route_after_final,
    route_after_human,
    route_after_pool,
    semantic_node,
)
from .state import SPECIALIST_TYPES, WorkflowState

_POSTGRES_CONTEXTS = ExitStack()
_POSTGRES_CHECKPOINTERS: dict[str, Any] = {}
_CHECKPOINT_MODELS = (
    Abstention,
    Candidate,
    CommentMood,
    DeferredVotePayload,
    DramaContext,
    DerivedObservation,
    EmotionButtonName,
    EmotionButtonPayload,
    EvidenceDocument,
    EvidenceProvenance,
    FinalInteraction,
    InstantVotePayload,
    InteractionType,
    Observation,
    QuerySpan,
    RepeatKeylinePayload,
    RevealAnchor,
    SideCommentPayload,
    SpecialistResult,
    TranscriptSegment,
    TriggerAnchor,
)


class CheckpointConfigurationError(RuntimeError):
    """PostgreSQL checkpoint 无法初始化。"""


def _checkpoint_serde() -> Any:
    """仅允许 V2 状态中实际使用的 Pydantic 模型。"""
    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=_CHECKPOINT_MODELS,
    )


def _configure_langsmith(settings: Settings) -> None:
    """按配置启用可选 LangSmith 追踪。"""
    if not settings.langsmith_tracing:
        return
    os.environ["LANGSMITH_TRACING"] = "true"
    for name, value in (
        ("LANGSMITH_ENDPOINT", settings.langsmith_endpoint),
        ("LANGSMITH_API_KEY", settings.langsmith_api_key),
        ("LANGSMITH_PROJECT", settings.langsmith_project),
    ):
        if value is not None:
            os.environ[name] = value


def create_checkpointer(database_url: str) -> Any:
    """创建唯一正式的 PostgreSQL checkpointer。"""
    if not isinstance(database_url, str) or not database_url.strip():
        raise CheckpointConfigurationError("CHECKPOINT_DATABASE_URL 必填")
    if database_url in _POSTGRES_CHECKPOINTERS:
        return _POSTGRES_CHECKPOINTERS[database_url]
    try:
        from langgraph.checkpoint.postgres import PostgresSaver
        from psycopg import Connection
        from psycopg.rows import dict_row

        connection = _POSTGRES_CONTEXTS.enter_context(
            Connection.connect(
                database_url,
                autocommit=True,
                prepare_threshold=0,
                row_factory=dict_row,
            )
        )
        checkpointer = PostgresSaver(connection, serde=_checkpoint_serde())
        checkpointer.setup()
    except Exception as error:
        raise CheckpointConfigurationError(
            f"无法初始化 PostgreSQL checkpoint: {error}"
        ) from error
    _POSTGRES_CHECKPOINTERS[database_url] = checkpointer
    return checkpointer


def build_graph(
    *,
    settings: Settings,
    checkpointer: Any | None = None,
    gateway: Any | None = None,
) -> Any:
    """编译单集 V2 工作流。"""
    _configure_langsmith(settings)
    saver = (
        create_checkpointer(settings.checkpoint_database_url)
        if checkpointer is None
        else checkpointer
    )
    llm_gateway = LLMGateway(settings) if gateway is None else gateway
    workflow = StateGraph(WorkflowState)
    workflow.add_node("media_prepare", media_prepare_node)
    workflow.add_node("adapter", adapter_node)
    workflow.add_node(
        "render_evidence",
        partial(render_evidence_node, settings=settings),
    )
    for specialist_type in SPECIALIST_TYPES:
        workflow.add_node(
            f"specialist_{specialist_type}",
            build_specialist_subgraph(specialist_type, llm_gateway),
        )
    workflow.add_node("pool", pool_node)
    workflow.add_node("render", partial(render_node, settings=settings))
    workflow.add_node("constraints", partial(constraints_node, settings=settings))
    workflow.add_node(
        "semantic",
        partial(semantic_node, gateway=llm_gateway, settings=settings),
    )
    workflow.add_node("human_gate", human_gate_node)
    workflow.add_node("final_check", partial(final_check_node, settings=settings))

    workflow.add_edge(START, "media_prepare")
    workflow.add_edge("media_prepare", "adapter")
    workflow.add_conditional_edges(
        "adapter",
        has_evidence,
        {"render_evidence": "render_evidence", "final_check": "final_check"},
    )
    for specialist_type in SPECIALIST_TYPES:
        node_name = f"specialist_{specialist_type}"
        workflow.add_edge("render_evidence", node_name)
        workflow.add_edge(node_name, "pool")
    workflow.add_conditional_edges(
        "pool",
        route_after_pool,
        {"human_gate": "human_gate", "render": "render"},
    )
    workflow.add_edge("render", "constraints")
    workflow.add_edge("constraints", "semantic")
    workflow.add_conditional_edges(
        "semantic",
        needs_human,
        {"human_gate": "human_gate", "final_check": "final_check"},
    )
    workflow.add_conditional_edges(
        "human_gate",
        route_after_human,
        {
            "human_gate": "human_gate",
            "pool": "pool",
            "render": "render",
            "final_check": "final_check",
        },
    )
    workflow.add_conditional_edges(
        "final_check",
        route_after_final,
        {"human_gate": "human_gate", "end": END},
    )
    return workflow.compile(checkpointer=saver)


def create_graph() -> Any:
    """供 LangGraph 开发工具调用的图工厂。"""
    settings = load_settings()
    return build_graph(settings=settings)


__all__ = ["CheckpointConfigurationError", "build_graph", "create_checkpointer", "create_graph"]
