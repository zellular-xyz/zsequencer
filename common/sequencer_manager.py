import asyncio

from aiohttp.client_exceptions import ClientError
from aiohttp.web import HTTPError

from common.auth import create_session
from common.errors import IsSequencerError
from common.logger import zlogger
from config import zconfig


async def init_sequencer() -> None:
    """Initialize the sequencer id for the node."""
    network_sequencer = await _find_network_sequencer()
    if network_sequencer:
        zconfig.update_sequencer(network_sequencer)
    else:
        zconfig.update_sequencer(zconfig.INIT_SEQUENCER_ID)
    if zconfig.is_sequencer:
        zlogger.info(
            "This node is acting as the SEQUENCER. ID: %s",
            zconfig.NODE["id"],
        )


async def _query_node_state(node_id: str) -> tuple[str, str | None]:
    """Query a single node's state and return (node_id, sequencer_id)."""
    url = f"{zconfig.NODES[node_id]['socket']}/node/state"
    try:
        async with create_session() as session:
            async with session.get(url, raise_for_status=False) as response:
                data = await response.json()
                if (
                    data["status"] == "error"
                    and data["error"]["code"] == IsSequencerError.__name__
                ):
                    # Node is not responding to /node/state because it's sequencer
                    return node_id, node_id

                if data["status"] == "error":
                    zlogger.warning(
                        f"Unexpected response while querying state from {node_id}: {data}"
                    )
                    return node_id, None

                sequencer_id = data["data"]["sequencer_id"]
                return node_id, sequencer_id

    except (ClientError, HTTPError, asyncio.TimeoutError) as e:
        zlogger.warning(f"Unable to get state from {node_id}: {e}")
        return node_id, None


async def _find_network_sequencer() -> str | None:
    """Finds the network active sequencer id."""
    sequencing_nodes = zconfig.last_state.sequencing_nodes
    attesting_nodes = zconfig.last_state.attesting_nodes

    total_stake = zconfig.last_state.total_stake

    tasks = [
        _query_node_state(node_id)
        for node_id in attesting_nodes
        if node_id != zconfig.NODE["id"]
    ]

    results = await asyncio.gather(*tasks)

    sequencers_stake = dict.fromkeys(sequencing_nodes, 0)
    for result in results:
        node_id, sequencer_id = result
        if sequencer_id and sequencer_id in sequencing_nodes:
            sequencers_stake[sequencer_id] += attesting_nodes[node_id]["stake"]

    max_stake_id = max(sequencers_stake, key=lambda k: sequencers_stake[k])
    sequencers_stake[max_stake_id] += zconfig.NODE["stake"]
    if 100 * sequencers_stake[max_stake_id] / total_stake >= zconfig.THRESHOLD_PERCENT:
        return max_stake_id
    else:
        return None


async def reset_sequencer(db_instance) -> None:
    """Reset the sequencer to the network sequencer."""
    zlogger.warning("Finding the network sequencer ...")
    network_sequencer = await _find_network_sequencer()

    if not network_sequencer:
        zlogger.warning("Network sequencer not found, skipping reset.")
        return

    if zconfig.SEQUENCER["id"] == network_sequencer:
        zlogger.warning(
            "Network sequencer is the same as the current sequencer, skipping reset."
        )
        return

    zconfig.update_sequencer(network_sequencer)
    zlogger.warning(f"Sequencer reset to {network_sequencer}")
    for app_name in db_instance.apps:
        db_instance.reinitialize_sequenced_batches(app_name=app_name)
    if zconfig.is_sequencer:
        zlogger.info(f"This node is acting as the SEQUENCER. ID: {zconfig.NODE['id']}")
        db_instance.has_received_nodes_put_batches = False
