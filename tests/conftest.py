import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# The fake discord package must win over a real discord.py install.
sys.path.insert(0, os.path.join(HERE, "fakediscord"))
sys.path.insert(1, ROOT)
os.environ["BSW_CONFIG"] = os.path.join(HERE, "test_config.toml")
os.environ["DB_BACKEND"] = "sqlite"
os.environ.pop("TURSO_DATABASE_URL", None)
