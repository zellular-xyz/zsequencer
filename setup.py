from setuptools import find_packages, setup

setup(
    name="zsequencer",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "Flask",
        "web3",
        "python-dotenv",
    ],
)
