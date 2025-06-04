import subprocess

from common.logger import zlogger
from tests.e2e.run import get_container_names


def show_logs_in_tmux_grid():
    container_names = get_container_names()

    if len(container_names) < 4:
        zlogger.error("Need at least 4 containers.")
        return

    container_names = container_names[:4]
    session_name = "zlogs"

    # 1. Start the session with top-left
    subprocess.run(
        [
            "tmux",
            "new-session",
            "-d",
            "-s",
            session_name,
            f"docker logs -f {container_names[0]}",
        ]
    )

    # 2. Split right (top-right)
    subprocess.run(
        [
            "tmux",
            "split-window",
            "-h",
            "-t",
            f"{session_name}:0",
            f"docker logs -f {container_names[3]}",
        ]
    )

    # 3. Split bottom-left (from pane 0)
    subprocess.run(["tmux", "select-pane", "-t", f"{session_name}:0.0"])
    subprocess.run(
        [
            "tmux",
            "split-window",
            "-v",
            "-t",
            f"{session_name}:0.0",
            f"docker logs -f {container_names[1]}",
        ]
    )

    # 4. Split bottom-right (from pane 1)
    subprocess.run(["tmux", "select-pane", "-t", f"{session_name}:0.1"])
    subprocess.run(
        [
            "tmux",
            "split-window",
            "-v",
            "-t",
            f"{session_name}:0.1",
            f"docker logs -f {container_names[2]}",
        ]
    )

    # 5. Even out the layout
    subprocess.run(["tmux", "select-layout", "-t", session_name, "tiled"])

    # 6. Attach to the session
    subprocess.run(["tmux", "attach-session", "-t", session_name])


if __name__ == "__main__":
    show_logs_in_tmux_grid()
