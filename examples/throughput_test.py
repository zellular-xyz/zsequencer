"""This module simulates a simple application using Zsequencer for throughput testing."""

import argparse
import json
import os
import random
import sys
import threading
import time
from typing import Any

import requests
from requests.exceptions import RequestException

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
from zsequencer.common.logger import zlogger

INITIAL_RATE: int = 5000
RATE_INCREMENT: float = 0.1
TEST_DURATION: int = 30
LATENCY: int = 3
PREVIOUS_FINALIZED_INDEX: int = 0


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser: argparse.ArgumentParser = argparse.ArgumentParser(
        description="Simulate a simple app using Zsequencer."
    )
    parser.add_argument(
        "--app_name", type=str, default="simple_app", help="Name of the application."
    )
    parser.add_argument(
        "--node_url", type=str, default="http://localhost:6003", help="URL of the node."
    )
    return parser.parse_args()


def send_transactions(
    app_name: str, node_url: str, rate: int, test_duration: int
) -> None:
    """Send transactions at a specified rate for a given duration."""
    end_time: float = time.time() + test_duration
    while time.time() < end_time:
        stime: float = time.time()
        try:
            response: requests.Response = requests.put(
                url=f"{node_url}/node/transactions",
                data=json.dumps(generate_dummy_data(app_name, rate)),
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
        except RequestException as error:
            zlogger.error(f"Error sending transactions: {error}")

        time_elapsed = time.time() - stime
        if time_elapsed > 1:
            zlogger.warning(f"slow import: {rate} txs in {time_elapsed} s")
        sleep_time: float = max(1.0 - time_elapsed, 0)
        time.sleep(sleep_time)


def measure_output_rate(
    app_name: str, node_url: str, input_rate: int, test_duration: int, latency: int
) -> float:
    """Measure output rate after a latency period."""
    global PREVIOUS_FINALIZED_INDEX
    end_time: float = time.time() + test_duration
    tx_counter: int = 0

    while time.time() < end_time:
        stime: float = time.time()
        try:
            response: requests.Response = requests.get(
                f"{node_url}/node/{app_name}/transactions/finalized/last"
            )
            response.raise_for_status()
        except RequestException as error:
            zlogger.error(f"Error checking state: {error}")

        last_finalized_tx: dict[str, Any] = response.json()
        last_finalized_index: int = last_finalized_tx["data"].get("index", 0)
        output_rate: int = last_finalized_index - PREVIOUS_FINALIZED_INDEX
        zlogger.info(f"input_rate: {input_rate} => output rate: {output_rate}")
        PREVIOUS_FINALIZED_INDEX = last_finalized_index
        tx_counter += output_rate
        time_elapsed: float = time.time() - stime
        sleep_time: float = max(1.0 - time_elapsed, 0)
        time.sleep(sleep_time)
    return tx_counter / (test_duration - latency)


def generate_dummy_data(app_name: str, transactions_num: int) -> dict[str, Any]:
    """Create a dummy data with the specified number of transactions."""
    timestamp: int = int(time.time())
    return {
        "app_name": app_name,
        "transactions": [
            json.dumps(
                {
                    "operation": "foo",
                    "serial": random.randint(1_000_000, 1_000_000_000_000),
                }
            )
            for tx_num in range(transactions_num)
        ],
        "timestamp": timestamp,
    }


def main() -> None:
    """Run throughput test with adjustable input rate."""
    args: argparse.Namespace = parse_args()

    input_rate: int = INITIAL_RATE
    while True:
        sender_thread: threading.Thread = threading.Thread(
            target=send_transactions,
            args=[args.app_name, args.node_url, input_rate, TEST_DURATION],
        )
        sender_thread.start()

        output_rate: float = measure_output_rate(
            app_name=args.app_name,
            node_url=args.node_url,
            input_rate=input_rate,
            test_duration=TEST_DURATION,
            latency=LATENCY,
        )

        if output_rate < input_rate:
            zlogger.warning(f"Maximum input rate reached: {input_rate} txs/sec")
            break

        zlogger.warning(
            f"Input rate: {input_rate} txs/sec, Output rate: {output_rate:.2f} txs/sec => increase input rate {RATE_INCREMENT * 100}%"
        )

        input_rate += int(input_rate * RATE_INCREMENT)

        sender_thread.join()


if __name__ == "__main__":
    main()
