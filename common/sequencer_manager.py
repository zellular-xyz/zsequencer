import asyncio
import time

from aiohttp.client_exceptions import ClientError
from aiohttp.web import HTTPError

from common.auth import create_session
from common.db import zdb
from common.errors import IsSequencerError
from common.logger import zlogger
from config import zconfig


class SequencerManager:
    """Manages sequencer initialization, discovery, and failover operations."""

    def __init__(self):
        """Initialize the sequencer manager."""
        self.has_received_node_updates = False

    async def init_sequencer(self) -> None:
        """Initialize the sequencer id for the node."""
        network_sequencer = await self._find_network_sequencer()
        if network_sequencer:
            zconfig.update_sequencer(network_sequencer)
        else:
            zconfig.update_sequencer(zconfig.INIT_SEQUENCER_ID)
        if zconfig.is_sequencer:
            zlogger.info(
                "This node is acting as the SEQUENCER. ID: %s",
                zconfig.NODE["id"],
            )

    async def _query_node_state(self, node_id: str) -> tuple[str, str | None]:
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

    async def _find_network_sequencer(self) -> str | None:
        """Finds the network active sequencer id."""
        sequencing_nodes = zconfig.last_state.sequencing_nodes
        attesting_nodes = zconfig.last_state.attesting_nodes

        total_stake = zconfig.last_state.total_stake

        tasks = [
            self._query_node_state(node_id)
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
        if (
            100 * sequencers_stake[max_stake_id] / total_stake
            >= zconfig.THRESHOLD_PERCENT
        ) and (max_stake_id, max_stake_id) in results:
            return max_stake_id
        else:
            return None

    async def reset_sequencer(self) -> None:
        """Reset the sequencer to the network sequencer."""

        zlogger.warning("Finding the network sequencer ...")
        network_sequencer = await self._find_network_sequencer()

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
        for app_name in zdb.apps:
            zdb.reinitialize_sequenced_batches(app_name=app_name)
            zdb.apps[app_name]["nodes_state"] = {}
            zdb.reset_latency_queue(app_name)

        if zconfig.is_sequencer:
            zlogger.info(
                f"This node is acting as the SEQUENCER. ID: {zconfig.NODE['id']}"
            )
            self.has_received_node_updates = False

    @property
    def not_receiving_node_updates(self) -> bool:
        """Check if a significant portion of nodes have stopped sending updates, indicating potential sequencer failover."""
        attesting_nodes = zconfig.last_state.attesting_nodes
        disconnected_nodes_stake = 0
        current_time = time.time()
        NODE_INACTIVITY_THRESHOLD_SECONDS = 10
        for node_id in attesting_nodes:
            if node_id == zconfig.NODE["id"]:
                continue

            last_node_request_time = max(
                zdb.apps[app_name]["nodes_state"]
                .get(node_id, {})
                .get("update_timestamp", 0)
                for app_name in zdb.apps
            )
            if (
                current_time - last_node_request_time
                > NODE_INACTIVITY_THRESHOLD_SECONDS
            ):
                disconnected_nodes_stake += attesting_nodes[node_id]["stake"]

        total_stake = zconfig.last_state.total_stake
        return 100 * disconnected_nodes_stake / total_stake >= zconfig.THRESHOLD_PERCENT

    async def detect_and_reset_sequencer_on_failover(self) -> None:
        """Detect if other nodes have switched to a new sequencer and update accordingly.
        This can happen if this sequencer faces connectivity issues and misses the network's sequencer switch."""
        if self.not_receiving_node_updates:
            if self.has_received_node_updates:
                await self.reset_sequencer()
        else:
            # Mark that we've received requests to avoid false failover detection during initial startup
            self.has_received_node_updates = True


# Global instance
zsequencer_manager = SequencerManager()
