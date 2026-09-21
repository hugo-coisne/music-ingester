"""Release lifecycle tests with real files/SQLite and a substituted Docker boundary."""

import contextlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from deploy import controller, manage


DEPLOY = Path(__file__).resolve().parent.parent / "deploy"
IMAGE_A = "ghcr.io/hugo-coisne/music-ingester@sha256:" + "a" * 64
IMAGE_B = "ghcr.io/hugo-coisne/music-ingester@sha256:" + "b" * 64


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root, self.library = self.base / "deployment", self.base / "music with spaces"
        self.root.mkdir()
        self.library.mkdir()
        self.settings = dict(root=str(self.root), library=str(self.library), uid=1000,
                             gid=1000, playlist_id="PLtest", download_timeout=900)
        for function, value in (("getuid", 1000), ("getgid", 1000), ("getgroups", [1000])):
            mock = patch.object(controller.os, function, return_value=value)
            mock.start()
            self.addCleanup(mock.stop)
        self.output = contextlib.redirect_stdout(io.StringIO())
        self.output.__enter__()
        self.addCleanup(self.output.__exit__, None, None, None)
        self.original_umask = os.umask(0o027)
        self.addCleanup(os.umask, self.original_umask)
        docker = patch.object(controller, "execute", side_effect=self.docker)
        self.execute = docker.start()
        self.addCleanup(docker.stop)

    @staticmethod
    def docker(args, **kwargs):
        output = "1\n" if args[:3] == ["docker", "image", "inspect"] else ""
        return subprocess.CompletedProcess(args, 0, output)

    def request(self, image=IMAGE_A, **settings):
        return dict(action="deploy", settings=self.settings | settings, image=image,
                    compose=json.loads((DEPLOY / "compose.json").read_text()),
                    controller=(DEPLOY / "controller.py").read_text())

    def deploy(self, image=IMAGE_A, **settings):
        controller.handle(self.request(image, **settings))
        return controller.active_release(self.root)

    def test_deploy_rollback_restores_config_and_preserves_new_data(self):
        first = self.deploy()
        database = self.root / "state" / "ingest.db"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE imports (video_id TEXT)")
            db.execute("INSERT INTO imports VALUES ('before')")
        second = self.deploy(IMAGE_B, playlist_id="PLchanged", download_timeout=600)
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO imports VALUES ('after')")
        audio = self.library / "new.m4a"
        audio.write_bytes(b"retained music")
        controller.handle(dict(action="rollback", settings=self.settings))
        restored = controller.active_release(self.root)
        info = controller.manifest(restored)
        self.assertEqual(info["image"], IMAGE_A)
        self.assertEqual(info["settings"]["playlist_id"], "PLtest")
        self.assertEqual(info["previous"], second.name)
        self.assertEqual(info["rollback_of"], first.name)
        self.assertEqual((restored / "music-ingest.toml").read_bytes(),
                         (first / "music-ingest.toml").read_bytes())
        with sqlite3.connect(database) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM imports").fetchone()[0], 2)
        with sqlite3.connect(self.root / "backups" / second.name / "ingest.db") as db:
            self.assertEqual(db.execute("SELECT video_id FROM imports").fetchall(), [("before",)])
        self.assertEqual(audio.read_bytes(), b"retained music")
        spec = json.loads((restored / "compose.json").read_text())
        config_mount = spec["services"]["music-ingest"]["volumes"][-1]
        self.assertEqual(config_mount["source"], str(restored / "music-ingest.toml"))
        self.assertTrue(config_mount["read_only"])

    def test_failed_health_check_never_switches_active_release(self):
        first = self.deploy()
        with patch.object(controller, "check_candidate", side_effect=RuntimeError("unhealthy")):
            with self.assertRaisesRegex(RuntimeError, "unhealthy"):
                self.deploy(IMAGE_B)
        self.assertEqual(controller.active_release(self.root), first)
        candidates = [p for p in (self.root / "releases").iterdir() if p != first]
        self.assertEqual(len(candidates), 1)
        with self.assertRaisesRegex(ValueError, "not validated"):
            controller.handle(dict(action="rollback", settings=self.settings, release=candidates[0].name))

    def test_failed_first_deploy_leaves_no_active_release(self):
        with patch.object(controller, "check_candidate", side_effect=RuntimeError("pull failed")):
            with self.assertRaises(RuntimeError):
                self.deploy()
        self.assertIsNone(controller.active_release(self.root))

    def test_failed_rollback_keeps_current_release(self):
        self.deploy()
        second = self.deploy(IMAGE_B)
        with patch.object(controller, "check_candidate", side_effect=RuntimeError("missing image")):
            with self.assertRaises(RuntimeError):
                controller.handle(dict(action="rollback", settings=self.settings))
        self.assertEqual(controller.active_release(self.root), second)

    def test_single_release_cannot_rollback(self):
        first = self.deploy()
        with self.assertRaisesRegex(ValueError, "no previous"):
            controller.handle(dict(action="rollback", settings=self.settings))
        self.assertEqual(controller.active_release(self.root), first)

    def test_storage_changes_require_explicit_migration(self):
        first = self.deploy()
        different = self.base / "other-music"
        different.mkdir()
        with self.assertRaisesRegex(ValueError, "cannot change"):
            self.deploy(IMAGE_B, library=str(different))
        self.assertEqual(controller.active_release(self.root), first)

    def test_lock_blocks_deployment_before_any_docker_command(self):
        with controller.exclusive(self.root / "operation.lock"):
            with self.assertRaisesRegex(RuntimeError, "another operation"):
                self.deploy()
        self.execute.assert_not_called()

    def test_unmanaged_import_lock_blocks_deployment(self):
        (self.root / "state").mkdir()
        with controller.exclusive(self.root / "state" / "ingest.db.lock"):
            with self.assertRaisesRegex(RuntimeError, "another operation"):
                self.deploy()
        self.assertIsNone(controller.active_release(self.root))

    def test_orphan_container_blocks_deployment(self):
        self.execute.side_effect = lambda args, **kwargs: subprocess.CompletedProcess(args, 0, "orphan\n")
        with self.assertRaisesRegex(RuntimeError, "still exists"):
            self.deploy()
        self.assertIsNone(controller.active_release(self.root))

    def test_incompatible_state_format_never_activates(self):
        self.execute.side_effect = lambda args, **kwargs: subprocess.CompletedProcess(
            args, 0, "2\n" if args[:3] == ["docker", "image", "inspect"] else "",
        )
        with self.assertRaisesRegex(ValueError, "state format"):
            self.deploy()
        self.assertIsNone(controller.active_release(self.root))

    def test_cached_digest_allows_rollback_without_registry(self):
        self.deploy()
        self.deploy(IMAGE_B)
        self.execute.reset_mock()
        controller.handle(dict(action="rollback", settings=self.settings))
        self.assertFalse(any(call.args[0][:2] == ["docker", "pull"]
                             for call in self.execute.call_args_list))

    def test_uncached_digest_is_pulled_before_validation(self):
        inspected = False

        def docker(args, **kwargs):
            nonlocal inspected
            if args[:3] == ["docker", "image", "inspect"] and not inspected:
                inspected = True
                raise subprocess.CalledProcessError(1, args)
            return self.docker(args, **kwargs)

        self.execute.side_effect = docker
        self.deploy()
        self.assertTrue(any(call.args[0] == ["docker", "pull", IMAGE_A]
                            for call in self.execute.call_args_list))

    def test_run_uses_active_playlist_and_pinned_image_without_pull(self):
        active = self.deploy(playlist_id="PLactive")
        self.execute.reset_mock()
        controller.handle(dict(action="run", settings=self.settings))
        invocation = self.execute.call_args.args[0]
        self.assertEqual(invocation[-2:], ["music-ingest", "PLactive"])
        self.assertIn(str(active / "compose.json"), invocation)
        self.assertEqual(invocation[invocation.index("--pull") + 1], "never")

    def test_unsafe_or_mutable_configuration_is_rejected(self):
        for overrides in ({"uid": 0}, {"gid": 0}, {"root": "/"}, {"library": str(self.root)},
                          {"playlist_id": "REPLACE_WITH_PLAYLIST_ID"}, {"download_timeout": float("nan")}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                controller.validate_settings(self.settings | overrides)
        with self.assertRaisesRegex(ValueError, "digest"):
            self.deploy("ghcr.io/hugo-coisne/music-ingester:latest")

    def test_missing_library_is_never_created(self):
        missing = self.base / "typo"
        with self.assertRaisesRegex(ValueError, "already exist"):
            self.deploy(library=str(missing))
        self.assertFalse(missing.exists())


class WorkstationTests(unittest.TestCase):
    def test_ssh_verifies_host_and_disables_forwarding(self):
        command = manage.ssh_command(dict(host="user@server"))
        self.assertIn("StrictHostKeyChecking=yes", command)
        self.assertIn("BatchMode=yes", command)
        self.assertIn("ForwardAgent=no", command)
        self.assertIn("ClearAllForwardings=yes", command)
        with self.assertRaises(ValueError):
            manage.ssh_command(dict(host="-oProxyCommand=untrusted"))

    def test_dry_run_does_not_connect_to_server(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "target.toml"
            text = (DEPLOY / "production.example.toml").read_text()
            target.write_text(text.replace("REPLACE_WITH_PLAYLIST_ID", "PLtest"))
            with patch.object(manage.subprocess, "run") as run, contextlib.redirect_stdout(io.StringIO()):
                result = manage.main(["--target", str(target), "--dry-run", "deploy", "--image", IMAGE_A])
            self.assertEqual(result, 0)
            run.assert_not_called()
