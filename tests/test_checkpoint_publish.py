"""Publish a completed scan without losing edits made while it was running."""
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class CheckpointPublishTests(unittest.TestCase):
    def test_content_conflict_stops_without_push(self):
        spec = importlib.util.spec_from_file_location('checkpoint_publish', ROOT / 'scripts/publish-checkpoint.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        artifacts = ROOT / 'tests/artifacts'
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts) as folder:
            root = Path(folder)
            def git(*args, cwd=root):
                result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout
            remote = root / 'remote.git'
            git('init', '--bare', '--initial-branch=main', str(remote))
            owner, worker = root / 'owner', root / 'worker'
            git('clone', str(remote), str(owner))
            git('config', 'user.name', 'test', cwd=owner)
            git('config', 'user.email', 'test@example.invalid', cwd=owner)
            (owner / 'monitor.json').write_text('original\n')
            git('add', '.', cwd=owner)
            git('commit', '-m', 'initial', cwd=owner)
            git('push', 'origin', 'main', cwd=owner)
            git('clone', str(remote), str(worker))
            git('config', 'user.name', 'test', cwd=worker)
            git('config', 'user.email', 'test@example.invalid', cwd=worker)
            (worker / 'monitor.json').write_text('scan\n')
            git('add', '.', cwd=worker)
            git('commit', '-m', 'scan', cwd=worker)
            (owner / 'monitor.json').write_text('owner correction\n')
            git('add', '.', cwd=owner)
            git('commit', '-m', 'correction', cwd=owner)
            git('push', 'origin', 'main', cwd=owner)
            published_head = git('rev-parse', 'HEAD', cwd=owner)
            self.assertNotEqual(module.publish_checkpoint(cwd=worker), 0)
            self.assertEqual(git('rev-parse', 'main', cwd=remote), published_head)
            self.assertEqual(git('show', 'main:monitor.json', cwd=remote), 'owner correction\n')
            self.assertEqual((worker / 'monitor.json').read_text().count('<<<<<<<'), 1)

    def test_retries_rebase_when_remote_moves_again(self):
        spec = importlib.util.spec_from_file_location('checkpoint_publish', ROOT / 'scripts/publish-checkpoint.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        results = [subprocess.CompletedProcess([], code) for code in (0, 1, 0, 0)]
        with patch.object(module.subprocess, 'run', side_effect=results) as run:
            self.assertEqual(module.publish_checkpoint(), 0)
        self.assertEqual([call.args[0] for call in run.call_args_list], [
            ['git', 'pull', '--rebase', 'origin', 'main'],
            ['git', 'push', 'origin', 'HEAD:main'],
            ['git', 'pull', '--rebase', 'origin', 'main'],
            ['git', 'push', 'origin', 'HEAD:main'],
        ])

    def test_scan_commit_rebases_over_concurrent_school_correction(self):
        spec = importlib.util.spec_from_file_location('checkpoint_publish', ROOT / 'scripts/publish-checkpoint.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        artifacts = ROOT / 'tests/artifacts'
        artifacts.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=artifacts) as folder:
            root = Path(folder)
            def git(*args, cwd=root):
                result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                return result.stdout
            remote = root / 'remote.git'
            git('init', '--bare', '--initial-branch=main', str(remote))
            owner, worker = root / 'owner', root / 'worker'
            git('clone', str(remote), str(owner))
            for repo in (owner,):
                git('config', 'user.name', 'test', cwd=repo)
                git('config', 'user.email', 'test@example.invalid', cwd=repo)
            (owner / 'school.json').write_text('original')
            git('add', '.', cwd=owner);git('commit', '-m', 'initial', cwd=owner);git('push', 'origin', 'main', cwd=owner)
            git('clone', str(remote), str(worker))
            git('config', 'user.name', 'test', cwd=worker);git('config', 'user.email', 'test@example.invalid', cwd=worker)
            (worker / 'monitor.json').write_text('completed scan')
            git('add', '.', cwd=worker);git('commit', '-m', 'scan', cwd=worker)
            (owner / 'school.json').write_text('owner correction')
            git('add', '.', cwd=owner);git('commit', '-m', 'correction', cwd=owner);git('push', 'origin', 'main', cwd=owner)
            self.assertEqual(module.publish_checkpoint(cwd=worker), 0)
            git('pull', '--ff-only', cwd=owner)
            self.assertEqual((owner / 'school.json').read_text(), 'owner correction')
            self.assertEqual((owner / 'monitor.json').read_text(), 'completed scan')
