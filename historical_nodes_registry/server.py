import threading
import time
import logging
from typing import Dict, Any, Optional

from fastapi import FastAPI, Depends, HTTPException

from historical_nodes_registry.registry_state_manager import RegistryStateManager
from historical_nodes_registry.schema import NodeInfo

# Constants
HTTP_400_BAD_REQUEST = 400
HTTP_500_INTERNAL_SERVER_ERROR = 500

logging.basicConfig(
    level=logging.DEBUG,  # Set the logging level
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'  # Log format
)


def create_server_app(persistence_filepath: str,
                      commitment_interval: int) -> FastAPI:
    """
    Create and return a FastAPI app instance.

    Args:
        commitment_interval (int): The commitment interval for the StateManager.

    Returns:
        FastAPI: The FastAPI application.
        :param commitment_interval:
        :param persistence_filepath:
    """
    app = FastAPI()

    # Initialize StateManager
    state_manager = RegistryStateManager(persistence_filepath,
                                         commitment_interval,
                                         logging.getLogger('historical_nodes_registry.server'))

    # Start StateManager daemon thread
    daemon_thread = threading.Thread(target=state_manager.run, daemon=True)
    daemon_thread.start()

    async def get_snapshot(
            timestamp: Optional[int] = None,
            manager: RegistryStateManager = Depends(lambda: state_manager),
    ):
        """
        Retrieve the snapshot closest to the given timestamp or the last snapshot if timestamp is None.

        Args:
            timestamp (Optional[int]): Query timestamp. If None, retrieves the last snapshot.
            manager (StateManager): Dependency injection for StateManager.

        Returns:
            dict: The snapshot data.

        Raises:
            HTTPException: If an error occurs.
        """
        try:
            timestamp, snapshot = manager.get_snapshot_by_timestamp(timestamp)
            return dict(timestamp=timestamp,
                        snapshot=snapshot)
        except Exception as e:
            raise HTTPException(status_code=HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))

    async def add_snapshot(
            nodes_info_snapshot: Dict[str, NodeInfo],
            manager: RegistryStateManager = Depends(lambda: state_manager),
    ):
        """
        Add a new snapshot to the series.

        Args:
            nodes_info_snapshot (dict): Snapshot data.
            manager (StateManager): Dependency injection for StateManager.

        Returns:
            dict: Success message with timestamp.

        Raises:
            HTTPException: If an error occurs.
        """
        try:
            timestamp = time.time()
            manager.update_temporary_snapshot(nodes_info_snapshot)
            return {"message": "Snapshot added successfully.", "timestamp": timestamp}
        except Exception as e:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e))

    async def update_node_info(
            nodes_info: NodeInfo,
            manager: RegistryStateManager = Depends(lambda: state_manager)):
        try:
            manager.update_node_info(nodes_info)
            return {"message": "NodeInfo updated successfully."}
        except Exception as e:
            raise HTTPException(status_code=HTTP_400_BAD_REQUEST, detail=str(e))

    # Registering endpoints with add_api_route
    app.add_api_route(
        "/snapshot/",
        get_snapshot,
        methods=["GET"],
        response_model=Dict[str, Any],
    )
    app.add_api_route(
        "/snapshot/",
        add_snapshot,
        methods=["POST"],
        response_model=Dict[str, Any],
    )
    app.add_api_route(
        "/nodeInfo/",
        update_node_info,
        methods=["POST"],
        response_model=Dict[str, Any],
    )

    return app
