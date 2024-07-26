"""
Setup configuration for the zsequencer package.
"""

from setuptools import find_packages, setup

setup(
    name="zsequencer",
    version="0.1.0",
    description="A package for managing the ZSequencer.",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    author="Siftal",
    author_email="m.khanmohamadzadeh@gmail.com",
    url="",
    packages=find_packages(),
    install_requires=[
        "Flask>=1.1.2",
        "web3>=5.17.0",
        "python-dotenv>=0.15.0",
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "zsequencer=zsequencer.cli:main",
        ],
    },
    include_package_data=True,
    zip_safe=False,
)
