"""This module defines Pydantic models for API responses."""

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
    node_id: str
    body: str
    hash: str
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
    def from_typed_dict(cls, data: StatefulBatchDict) -> "StatefulBatch":
        return cls(**data)


class EmptyResponseData(BaseModel):
    """Empty response object used when no data is required."""

    pass


class EmptyResponse(SuccessResponse):
    """Standard success response with no additional data."""

    data: EmptyResponseData = Field(default_factory=EmptyResponseData)


class BatchResponse(SuccessResponse):
    """Response model for batch operations."""

    data: dict = Field(default_factory=dict)


# Request Models

class BatchData(BaseModel):
    """Data structure for batch submission to the sequencer."""

    hash: str
    body: str
    node_id: str


class NodePutBatchRequest(RootModel):
    """Request format for submitting a single batch to a node."""

    # Raw batch body as string
    root: str


class NodePutBulkBatchesRequest(RootModel):
    """Request format for submitting multiple batches to different applications at once."""

    # Dictionary of app_name -> list of raw batch bodies
    root: dict[str, list[str]]



class SequencerPutBatchesRequest(BaseModel):
    """Request format for batch sequencing with consensus information."""

    app_name: str
    batches: list[BatchData]
    node_id: str
    signature: str
    sequenced_index: int
    sequenced_hash: str
    sequenced_chaining_hash: str
    locked_index: int
    locked_hash: str
    locked_chaining_hash: str
    timestamp: int


# Response Models


class SignSyncPointRequest(BaseModel):
    """Request to sign a synchronization point for consensus."""

    app_name: str
    state: str
    index: int
    hash: str
    chaining_hash: str


class SignSyncPointData(BaseModel):
    """Data model for sign sync point response."""

    app_name: str
    state: str
    index: int
    hash: str
    chaining_hash: str
    signature: str


class SignSyncPointResponse(SuccessResponse):
    """Response containing the signature for a synchronization point."""

    data: SignSyncPointData


class AppMissedBatch(BaseModel):
    """Model for a missed batch."""

    body: str


class DisputeRequest(BaseModel):
    """Request model for disputes."""

    sequencer_id: str
    apps_missed_batches: dict[str, dict[str, AppMissedBatch]]
    is_sequencer_down: bool
    timestamp: int


class DisputeData(BaseModel):
    """Data model for dispute resolution response."""

    node_id: str
    old_sequencer_id: str
    new_sequencer_id: str
    timestamp: int
    signature: str


class DisputeResponse(SuccessResponse):
    """Response model for dispute resolution."""

    data: DisputeData


class SwitchProof(BaseModel):
    """Model for a switch proof."""

    node_id: str
    old_sequencer_id: str
    new_sequencer_id: str
    timestamp: int
    signature: str


class SwitchRequest(BaseModel):
    """Request model for sequencer switches."""

    timestamp: int
    proofs: list[SwitchProof]


class SwitchResponse(SuccessResponse):
    """Response model for sequencer switches."""

    data: dict = Field(default_factory=dict)


class AppState(BaseModel):
    """Model for application state."""

    last_sequenced_index: int
    last_sequenced_hash: str
    last_locked_index: int
    last_locked_hash: str
    last_finalized_index: int
    last_finalized_hash: str


class NodeStateData(BaseModel):
    """Data model for node state."""

    sequencer: bool
    version: str
    sequencer_id: str
    node_id: str
    pubkeyG2_X: list[int]
    pubkeyG2_Y: list[int]
    address: str
    apps: dict[str, AppState]


class NodeStateResponse(SuccessResponse):
    """Response model for node state."""

    data: NodeStateData


class BatchSignatureInfo(BaseModel):
    """Information about batch signatures and consensus state."""

    signature: str | None = None
    hash: str | None = None
    chaining_hash: str | None = None
    nonsigners: list[str] | None = None
    index: int | None = None
    tag: int | None = None


class GetAppLastBatchResponse(SuccessResponse):
    """Response model for getting a single app's last batch."""

    data: StatefulBatch | None = None


class GetAppsLastBatchResponse(SuccessResponse):
    """Response model for getting last batches for all apps."""

    data: dict[str, StatefulBatch] | None = None


class GetBatchesData(BaseModel):
    """Data model for the get_batches endpoint."""

    batches: list[str]
    first_chaining_hash: str
    finalized: BatchSignatureInfo | None = None
    locked: BatchSignatureInfo | None = None


class GetBatchesResponse(SuccessResponse):
    """Response model for the get_batches endpoint."""

    data: GetBatchesData | None = None


# Models for Sequencer Router


class SequencerPutBatchesResponseData(BaseModel):
    """Data model for the sequencer's put_batches response."""

    batches: list[dict[str, Any]] = Field(default_factory=list)
    last_finalized_index: int = 0
    finalized: BatchSignatureInfo = Field(default_factory=BatchSignatureInfo)
    locked: BatchSignatureInfo = Field(default_factory=BatchSignatureInfo)


class SequencerPutBatchesResponse(SuccessResponse):
    """Response model for the sequencer's put_batches endpoint."""

    data: SequencerPutBatchesResponseData
