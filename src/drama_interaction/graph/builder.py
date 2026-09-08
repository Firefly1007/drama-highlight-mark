"""V2 LangGraph 装配与 PostgreSQL checkpoint。"""

from __future__ import annotations

import os
from contextlib import ExitStack
from functools import partial
from typing import Any

from langgraph.graph import END, START, StateGraph

from drama_interaction.config import Settings, load_settings
from drama_interaction.context import DramaContext
from drama_interaction.evidence.service import EvidenceAuditRecord
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
    assemble_evidence_node,
    constraints_node,
    dispatch_slice_batch_node,
    dispatch_slice_subgraphs,
    extract_mix_node,
    final_check_node,
    human_gate_node,
    media_prepare_node,
    merge_slice_batch_node,
    merge_slice_result_node,
    needs_human,
    observe_audio_node,
    observe_ocr_node,
    observe_vlm_node,
    persist_evidence_node,
    pool_node,
    prepare_background_node,
    prepare_frames_node,
    prepare_slice_audio_node,
    render_evidence_node,
    render_node,
    route_after_final,
    route_after_human,
    route_after_merge_slice_batch,
    route_after_pool,
    semantic_node,
    separate_audio_node,
    specialist_node,
    transcribe_audio_node,
)
from .state import SPECIALIST_TYPES, SliceOutput, SliceState, WorkflowState

_POSTGRES_CONTEXTS = ExitStack()
_POSTGRES_CHECKPOINTERS: dict[str, Any] = {}
_CHECKPOINT_MODELS = (
    Abstention,
    Candidate,
    CommentMood,
    DeferredVotePayload,
    DramaContext,
    DerivedObservation,
    EvidenceAuditRecord,
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


def build_slice_graph(*, settings: Settings) -> Any:
    """编译仅处理一个固定时间跨度的观察子图。"""
    workflow = StateGraph(SliceState, output_schema=SliceOutput)
    workflow.add_node("prepare_frames", prepare_frames_node)
    workflow.add_node("prepare_slice_audio", prepare_slice_audio_node)
    workflow.add_node("observe_ocr", partial(observe_ocr_node, settings=settings))
    workflow.add_node("observe_vlm", partial(observe_vlm_node, settings=settings))
    workflow.add_node("observe_audio", partial(observe_audio_node, settings=settings))
    workflow.add_node("merge_slice_result", merge_slice_result_node)
    workflow.add_edge(START, "prepare_frames")
    workflow.add_edge(START, "prepare_slice_audio")
    workflow.add_edge("prepare_frames", "observe_ocr")
    workflow.add_edge("prepare_frames", "observe_vlm")
    workflow.add_edge("prepare_slice_audio", "observe_audio")
    workflow.add_edge(
        ["observe_ocr", "observe_vlm", "observe_audio"], "merge_slice_result"
    )
    workflow.add_edge("merge_slice_result", END)
    return workflow.compile()


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
    slice_graph = build_slice_graph(settings=settings)
    workflow = StateGraph(WorkflowState)
    workflow.add_node("media_prepare", media_prepare_node)
    workflow.add_node("extract_mix", extract_mix_node)
    workflow.add_node(
        "separate_audio",
        partial(separate_audio_node, settings=settings),
    )
    workflow.add_node(
        "transcribe_audio",
        partial(transcribe_audio_node, settings=settings),
    )
    workflow.add_node("prepare_background", prepare_background_node)
    workflow.add_node("dispatch_slice_batch", dispatch_slice_batch_node)
    workflow.add_node("slice", slice_graph)
    workflow.add_node("merge_slice_batch", merge_slice_batch_node)
    workflow.add_node("assemble_evidence", assemble_evidence_node)
    workflow.add_node("persist_evidence", persist_evidence_node)
    workflow.add_node("render_evidence", render_evidence_node)
    for specialist_type in SPECIALIST_TYPES:
        workflow.add_node(
            f"specialist_{specialist_type}",
            partial(
                specialist_node,
                specialist_type=specialist_type,
                gateway=llm_gateway,
            ),
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
    workflow.add_edge(START, "extract_mix")
    workflow.add_edge(["media_prepare", "extract_mix"], "separate_audio")
    workflow.add_edge("separate_audio", "transcribe_audio")
    workflow.add_edge("separate_audio", "prepare_background")
    workflow.add_edge(
        ["transcribe_audio", "prepare_background"], "dispatch_slice_batch"
    )
    workflow.add_conditional_edges("dispatch_slice_batch", dispatch_slice_subgraphs)
    workflow.add_edge("slice", "merge_slice_batch")
    workflow.add_conditional_edges("merge_slice_batch", route_after_merge_slice_batch)
    workflow.add_edge("assemble_evidence", "persist_evidence")
    workflow.add_edge("persist_evidence", "render_evidence")
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


__all__ = [
    "CheckpointConfigurationError",
    "build_graph",
    "build_slice_graph",
    "create_checkpointer",
    "create_graph",
]
