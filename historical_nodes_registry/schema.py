from pydantic import BaseModel
from typing import Dict


class NodeInfo(BaseModel):
    id: str
    public_key_g2: str
    address: str
    socket: str
    stake: int


SnapShotType = Dict[str, NodeInfo]
