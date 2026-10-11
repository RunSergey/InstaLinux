#!/usr/bin/env python3
import sys
from pathlib import Path

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.app import main

if __name__ == "__main__":
    sys.exit(main())
