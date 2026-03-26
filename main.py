"""
Backward compatibility entry point for NOAA JetStream

For installed package, use 'jetstream' command instead.
For development, run this file directly: python main.py
"""

from jetstream.cli import main

if __name__ == "__main__":
    main()
