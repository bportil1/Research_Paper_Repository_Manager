"""MI-01: standalone Reference Manager processes remain mutually independent.

These tests require no host, Flask server, nested search module, or network.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from reference_manager.integrations.pah import create_runtime_adapter
from reference_manager.process_ui import configuration_from_environment
from reference_manager.web import config as web_config


class MultiInstanceContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_discoverable_adapter_factory_and_module_identity(self):
        adapter = create_runtime_adapter()
        self.assertEqual(adapter.module_id, "reference_manager")
        self.assertTrue(callable(adapter.process_launch_spec))
        self.assertIsNone(adapter.shutdown())
        self.assertFalse(adapter.launch()["launched"])

    def test_trusted_launch_spec_does_not_use_host_working_directory(self):
        adapter = create_runtime_adapter()
        with mock.patch("reference_manager.integrations.pah.find_spec", return_value=object()):
            spec = adapter.process_launch_spec(context={"project_root": self.root})
        self.assertEqual(spec["command"][1:], ["-m", "reference_manager.process_ui"])
        self.assertEqual(spec["requested_port"], 0)
        self.assertEqual(spec["ui_path"], "/")
        self.assertEqual(spec["env"]["REFERENCE_MANAGER_INITIAL_LIBRARY"], "")

    def test_explicit_library_resource_is_selected_but_not_mutated(self):
        adapter = create_runtime_adapter()
        library = self.root / "papers"
        library.mkdir()
        with mock.patch("reference_manager.integrations.pah.find_spec", return_value=object()):
            spec = adapter.process_launch_spec(context={"resources": {"reference_library": library}})
        self.assertEqual(spec["env"]["REFERENCE_MANAGER_INITIAL_LIBRARY"], str(library))
        self.assertEqual(list(library.iterdir()), [])

    def test_invalid_resource_is_rejected_without_fallback(self):
        adapter = create_runtime_adapter()
        with mock.patch("reference_manager.integrations.pah.find_spec", return_value=object()):
            with self.assertRaises((OSError, ValueError)):
                adapter.process_launch_spec(context={"resources": {"references": self.root / "missing"},
                                                     "project_root": self.root})

    def test_requires_all_host_runtime_values_and_checks_port(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        valid = {"PAH_MODULE_INSTANCE_ID": "first", "PAH_MODULE_RUNTIME_DIR": str(runtime),
                 "PAH_MODULE_PORT": "44991", "REFERENCE_MANAGER_INITIAL_LIBRARY": ""}
        self.assertEqual(configuration_from_environment(valid)["host"], "127.0.0.1")
        self.assertEqual(configuration_from_environment(valid)["port"], 44991)
        for field in ("PAH_MODULE_INSTANCE_ID", "PAH_MODULE_RUNTIME_DIR", "PAH_MODULE_PORT"):
            with self.subTest(field=field):
                with self.assertRaises(RuntimeError):
                    configuration_from_environment({**valid, field: ""})
        with self.assertRaises(RuntimeError):
            configuration_from_environment({**valid, "PAH_MODULE_PORT": "65536"})
        with self.assertRaises(RuntimeError):
            configuration_from_environment({**valid, "PAH_MODULE_INSTANCE_ID": "bad\nname"})

    def test_runtime_config_paths_are_private_and_saved_independently(self):
        lib_a = self.root / "lib-a"
        lib_b = self.root / "lib-b"
        runtime_a = self.root / "a"
        runtime_b = self.root / "b"
        for directory in (lib_a, lib_b, runtime_a, runtime_b):
            directory.mkdir()
        configs = []
        for name, runtime, lib, port in (("a", runtime_a, lib_a, 42001),
                                         ("b", runtime_b, lib_b, 42002)):
            cfg = configuration_from_environment({"PAH_MODULE_INSTANCE_ID": name,
                 "PAH_MODULE_RUNTIME_DIR": str(runtime), "PAH_MODULE_PORT": str(port),
                 "REFERENCE_MANAGER_INITIAL_LIBRARY": str(lib)})
            configs.append(cfg)
            with mock.patch.dict(os.environ, {"REFERENCE_MANAGER_CONFIG_PATH": str(cfg["config_path"])}):
                web_config.save_config({"library_root": str(lib)})
                self.assertEqual(web_config.get_library_root(), lib)
        self.assertNotEqual(configs[0]["config_path"], configs[1]["config_path"])
        with mock.patch.dict(os.environ, {"REFERENCE_MANAGER_CONFIG_PATH": str(configs[0]["config_path"])}):
            web_config.save_config({"library_root": str(lib_a / "changed")})
        self.assertEqual(json.loads(configs[1]["config_path"].read_text())["library_root"], str(lib_b))

    def test_separate_python_processes_save_separate_selected_libraries(self):
        paths = [self.root / "proc-a", self.root / "proc-b"]
        for p in paths:
            p.mkdir()
        program = ("from reference_manager.web.config import save_config,load_config; "
                   "import os,json; "
                   "save_config({'library_root':os.environ['TEST_LIBRARY']}); "
                   "print(json.dumps(load_config()))")
        children = []
        for index, path in enumerate(paths):
            env = {**os.environ, "REFERENCE_MANAGER_CONFIG_PATH": str(path / "config.json"),
                   "TEST_LIBRARY": str(path / "papers")}
            children.append(subprocess.Popen([sys.executable, "-c", program], env=env,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for index, child in enumerate(children):
            stdout, stderr = child.communicate(timeout=10)
            self.assertEqual(child.returncode, 0, stderr)
            self.assertEqual(json.loads(stdout)["library_root"], str(paths[index] / "papers"))
        self.assertNotEqual((paths[0] / "config.json").read_bytes(),
                            (paths[1] / "config.json").read_bytes())

    def test_legacy_config_path_is_unchanged_without_runtime_override(self):
        with mock.patch.dict(os.environ, {"REFERENCE_MANAGER_CONFIG_PATH": ""}):
            self.assertEqual(web_config._config_path(), web_config.CONFIG_PATH)

    def test_state_is_persisted_by_library_not_supervisor(self):
        from reference_manager import ReferenceManager
        a = self.root / "library-a"
        b = self.root / "library-b"
        a.mkdir()
        b.mkdir()
        first = ReferenceManager(a)
        second = ReferenceManager(b)
        self.assertNotEqual(first.root, second.root)
        self.assertEqual(first.list_papers(), second.list_papers())
        self.assertFalse((self.root / "config.json").exists())


if __name__ == "__main__":
    unittest.main()
