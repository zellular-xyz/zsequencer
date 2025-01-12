"""This script sets up and runs a simple app network for testing."""
import os
import platform
import random
import shlex
import string
import subprocess
from enum import Enum

BASE_DIRECTORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


class OSType(Enum):
    MACOS = "macos"
    LINUX = "linux"
    UNKNOWN = "unknown"


def get_os_type():
    os_type = platform.system()
    if os_type == "Darwin":
        return OSType.MACOS
    elif os_type == "Linux":
        return OSType.LINUX
    else:
        return OSType.UNKNOWN


current_os = get_os_type()


def run_linux_command_on_terminal(command: str, env_variables):
    for env_variable in os.environ:
        if env_variable not in env_variables:
            env_variables[env_variable] = os.environ[env_variable]

    launch_command: list[str] = ["gnome-terminal", "--tab", "--", "bash", "-c", command]
    with subprocess.Popen(args=launch_command, env=env_variables) as process:
        process.wait()


def generate_random_string(length=5):
    characters = string.ascii_letters + string.digits  # Combine letters and digits
    random_string = ''.join(random.choices(characters, k=length))
    return random_string


def run_macos_command_on_terminal(command: str, env_variables: dict):
    """
    Opens a new Terminal window on macOS, sets environment variables, and runs a command.

    Args:
        command (str): The command to run in the Terminal.
        env_variables (dict): A dictionary of environment variables to set.
    """
    env_string = "export " + " ".join([f"{key}={shlex.quote(value)}" for key, value in env_variables.items()])
    full_command = f"{env_string} && {command}"

    cmd_temporary_file_path = os.path.join(BASE_DIRECTORY, 'old_runner', f'{generate_random_string()}.sh')

    # Write the command to a temporary bash file
    with open(cmd_temporary_file_path, 'w') as bash_file:
        bash_file.write(full_command)

    # Make the script executable
    subprocess.run(['chmod', '+x', cmd_temporary_file_path])

    # AppleScript to open Terminal and run the bash script
    apple_script = f"""
    tell application "Terminal"
        do script "{cmd_temporary_file_path}"
        activate
    end tell
    """

    # Run the AppleScript
    subprocess.run(["osascript", "-e", apple_script])


def run_command_on_terminal(command: str, env_variables):
    if current_os == OSType.LINUX:
        run_linux_command_on_terminal(command, env_variables)
    elif current_os == OSType.MACOS:
        run_macos_command_on_terminal(command, env_variables)
