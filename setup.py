"""
Setup configuration for NOAA JetStream
"""
from setuptools import setup, find_packages
from pathlib import Path

# Read the README file
this_directory = Path(__file__).parent
long_description = (this_directory / "README.md").read_text(encoding='utf-8')

# Read requirements
requirements = []
with open('requirements.txt', 'r', encoding='utf-8') as f:
    requirements = [line.strip() for line in f if line.strip() and not line.startswith('#')]

setup(
    name="noaa-jetstream",
    version="0.1.10",
    author="Michael Akridge",
    author_email="",
    description="JetStream: Cloud Data Manager - A comprehensive tool for managing local-to-cloud uploads",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/MichaelAkridge-NOAA/jetstream",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Science/Research",
        "Topic :: Scientific/Engineering",
        "Topic :: Internet :: WWW/HTTP :: HTTP Servers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.9",
    install_requires=requirements,
    extras_require={
        "dev": [
            "pytest>=7.0.0",
            "pytest-asyncio>=0.21.0",
            "black>=23.0.0",
            "flake8>=6.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "jetstream=jetstream.cli:main",
            "jetstream-server=jetstream.cli:main",
            "jetstream-create-shortcuts=jetstream.shortcuts:main_create",
            "jetstream-remove-shortcuts=jetstream.shortcuts:main_remove",
        ],
    },
    include_package_data=True,
    package_data={
        "jetstream": [
            "static/*.html",
            "static/*.ico",
            "static/*.png",
            "static/css/*.css",
            "static/js/*.js",
        ],
    },
)
