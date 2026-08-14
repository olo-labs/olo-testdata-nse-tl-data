from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from export_citus_to_parquet import env_value, pg_connection_string


class DatabaseEnvironmentTests(unittest.TestCase):
    def test_configured_host_is_the_fallback_when_override_is_absent(self) -> None:
        database = {"host": "127.0.0.1", "host_env": "OLO_CITUS_HOST"}
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(env_value(database, "host"), "127.0.0.1")

    def test_environment_host_overrides_configured_fallback(self) -> None:
        database = {"host": "127.0.0.1", "host_env": "OLO_CITUS_HOST"}
        with patch.dict(os.environ, {"OLO_CITUS_HOST": "postgres"}, clear=True):
            self.assertEqual(env_value(database, "host"), "postgres")

    def test_remote_connection_can_be_fully_environment_driven(self) -> None:
        database = {
            "host": "127.0.0.1", "host_env": "OLO_CITUS_HOST",
            "port": "5432", "port_env": "OLO_CITUS_PORT",
            "name": "local", "name_env": "OLO_CITUS_DATABASE",
            "user": "local", "user_env": "OLO_CITUS_USER",
            "password": "local", "password_env": "OLO_CITUS_PASSWORD",
            "sslmode": "disable", "sslmode_env": "OLO_CITUS_SSLMODE",
        }
        remote = {
            "OLO_CITUS_HOST": "remote.example",
            "OLO_CITUS_PORT": "6543",
            "OLO_CITUS_DATABASE": "remote_db",
            "OLO_CITUS_USER": "reader",
            "OLO_CITUS_PASSWORD": "secret",
            "OLO_CITUS_SSLMODE": "verify-full",
        }
        with patch.dict(os.environ, remote, clear=True):
            dsn = pg_connection_string(database)
        for expected in ("remote.example", "6543", "remote_db", "reader", "secret", "verify-full"):
            self.assertIn(expected, dsn)


if __name__ == "__main__":
    unittest.main()
