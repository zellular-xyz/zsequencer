import asyncio
import aiohttp
import multiprocessing
import random
import string

# Configuration
URL = "http://0.0.0.0:7001/put_batch"
NUM_REQUESTS = 1_000  # Total requests
CONCURRENT_REQUESTS = 10  # Concurrent requests per process
NUM_PROCESSES = multiprocessing.cpu_count()  # Use all available CPU cores


def generate_random_string(length=7):
    """Generate a random alphanumeric string of given length."""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


async def send_request(session, batch):
    """Send an async HTTP POST request with batch data."""
    data = {"batch": batch}
    try:
        async with session.post(URL, data=data) as response:
            return response.status
    except aiohttp.ClientError as e:
        print(f"Request failed: {e}")
        return None


async def run_load_test(requests_per_process):
    """Run the load test using asyncio with a given number of requests."""
    async with aiohttp.ClientSession() as session:
        tasks = [send_request(session, generate_random_string()) for _ in range(requests_per_process)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        success_count = sum(1 for r in responses if r == 200)
        print(
            f"Process {multiprocessing.current_process().name}: {success_count}/{requests_per_process} successful requests.")


def start_process(requests_per_process):
    """Start an independent process to run the async load test."""
    asyncio.run(run_load_test(requests_per_process))


def main():
    """Distribute requests across multiple processes."""
    requests_per_process = NUM_REQUESTS // NUM_PROCESSES
    processes = [multiprocessing.Process(target=start_process, args=(requests_per_process,)) for _ in
                 range(NUM_PROCESSES)]

    for p in processes:
        p.start()

    for p in processes:
        p.join()


if __name__ == "__main__":
    main()
