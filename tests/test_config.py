import json
import unittest

from nyc311_factory.config import config_from_dict
from nyc311_factory.exceptions import ConfigError
from tests.helpers import BASE_CONFIG


def mutated(**changes):
    data = json.loads(json.dumps(BASE_CONFIG))
    for dotted, value in changes.items():
        target = data
        *parents, leaf = dotted.split("__")
        for p in parents:
            target = target[p]
        target[leaf] = value
    return data


class ConfigTests(unittest.TestCase):
    def test_valid_config_loads(self):
        self.assertEqual(config_from_dict(mutated(paths__raw="data/raw")).batch_size, 100)

    def test_invalid_values_raise_config_error(self):
        bad = [
            mutated(window__start="2024-13-01"), mutated(window__start="2025-01-01"),
            mutated(batch_size=0), mutated(batch_size=60000), mutated(max_retries=-1),
            mutated(quarantine_max_ratio=1.5), mutated(source__kind="ftp"), mutated(source__method="PUT"),
            mutated(paths__raw="/abs/path"),
        ]
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ConfigError):
                config_from_dict(data)


if __name__ == "__main__":
    unittest.main()
