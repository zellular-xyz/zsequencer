"""This module defines Pydantic models for API responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, RootModel

from common.batch import StatefulBatch as StatefulBatchDict
from common.state import OperationalState


class SuccessResponse(BaseModel):
    """Base model for successful API responses."""

    status: str = "success"
    message: str = "Operation successful"
    data: Any = None


class StatefulBatch(BaseModel):
    """Complete information about a batch including its state and signatures."""

    app_name: str
    body: str
    chaining_hash: str
    lock_signature: str | None
    locked_nonsigners: list[str] | None
    locked_tag: int | None
    finalization_signature: str | None
    finalized_nonsigners: list[str] | None
    finalized_tag: int | None
    index: int
    state: OperationalState

    @classmethod
    def from_typed_dict(cls, data: StatefulBatchDict) -> StatefulBatch:
        return cls(**data)


# Models for Node Router


class NodePutBatchRequest(RootModel):
    """Request format for submitting a single batch to a node."""

    # Raw batch body as string
    root: str


class NodePutBulkBatchesRequest(RootModel):
    """Request format for submitting multiple batches to different applications at once."""

    # Dictionary of app_name -> list of raw batch bodies
    root: dict[str, list[str]]


class EmptyResponseData(BaseModel):
    """Empty response object used when no data is required."""

    pass


class EmptyResponse(SuccessResponse):
    """Standard success response with no additional data."""

    data: EmptyResponseData = Field(default_factory=EmptyResponseData)


class SignSyncPointRequest(BaseModel):
    """Request to sign a synchronization point for consensus."""

    app_name: str
    state: str
    index: int
    chaining_hash: str


class SignSyncPointData(BaseModel):
    """Data model for sign sync point response."""

    app_name: str
    state: str
    index: int
    chaining_hash: str
    signature: str


class SignSyncPointResponse(SuccessResponse):
    """Response containing the signature for a synchronization point."""

    data: SignSyncPointData


class DisputeRequest(BaseModel):
    """Request to dispute against the sequencer."""

    sequencer_id: str
    apps_censored_batches: dict[str, str]
    timestamp: int


class DisputeData(BaseModel):
    """Dispute confirmation response with signed proof."""

    signature: str


class DisputeResponse(SuccessResponse):
    """Response containing signed confirmation of the dispute."""

    data: DisputeData


class SwitchProof(BaseModel):
    """Cryptographic proof authorizing a sequencer switch."""

    node_id: str
    sequencer_id: str
    timestamp: int
    signature: str


class SwitchRequest(BaseModel):
    """Request to switch sequencers with supporting proofs."""

    proofs: list[SwitchProof]


class AppState(BaseModel):
    """Current consensus state information for an application."""

    last_sequenced_index: int
    last_locked_index: int
    last_finalized_index: int


class NodeStateData(BaseModel):
    """Comprehensive node status and identity information."""

    sequencer: bool
    version: str
    sequencer_id: str
    node_id: str
    pubkeyG2_X: list[int]
    pubkeyG2_Y: list[int]
    address: str
    apps: dict[str, AppState]


class NodeStateResponse(SuccessResponse):
    """Response with complete node state information."""

    data: NodeStateData


class BatchSignatureInfo(BaseModel):
    """Cryptographic proof and metadata about batch consensus status."""

    signature: str | None = None
    chaining_hash: str | None = None
    nonsigners: list[str] | None = None
    index: int | None = None
    tag: int | None = None


class GetAppLastBatchResponse(SuccessResponse):
    """Response containing the latest batch for a specific application."""

    data: StatefulBatch | None = None


class GetAppsLastBatchResponse(SuccessResponse):
    """Response with latest batches for all applications."""

    data: dict[str, StatefulBatch] | None = None


class GetBatchesData(BaseModel):
    """Batch data with latest consensus status information on the provided batches."""

    batches: list[str]
    first_chaining_hash: str
    finalized: BatchSignatureInfo | None = None
    locked: BatchSignatureInfo | None = None


class GetBatchesResponse(SuccessResponse):
    """Response containing batches and their consensus status."""

    data: GetBatchesData | None = None


# Models for Sequencer Router


class SequencerPutBatchesRequest(BaseModel):
    """Request format for batch sequencing with consensus information."""

    app_name: str
    batches: list[str]
    sequenced_index: int
    sequenced_chaining_hash: str
    locked_index: int
    locked_chaining_hash: str
    timestamp: int


class SequencerPutBatchesResponseData(BaseModel):
    """Response data containing both the node's submitted batches and batches from other nodes with their consensus state."""

    batches: list[str] = Field(default_factory=list)
    last_finalized_index: int = 0
    finalized: BatchSignatureInfo = Field(default_factory=BatchSignatureInfo)
    locked: BatchSignatureInfo = Field(default_factory=BatchSignatureInfo)


class SequencerPutBatchesResponse(SuccessResponse):
    """Response from sequencer with both submitted and other nodes' batches along with consensus information."""

    data: SequencerPutBatchesResponseData
