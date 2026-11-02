#!/usr/bin/env python3
"""Publish an already committed scan while preserving concurrent repository edits."""
import os
import subprocess


def publish_checkpoint(*, cwd=None, attempts=3):
    for attempt in range(attempts):
        print(f'Synchronising before publishing ({attempt + 1}/{attempts})', flush=True)
        sync = subprocess.run(['git', 'pull', '--rebase', 'origin', 'main'], cwd=cwd)
        if sync.returncode:
            # A real content conflict requires review. Never discard either side
            # or force-push over newer data to manufacture a successful run.
            return sync.returncode
        published = subprocess.run(['git', 'push', 'origin', 'HEAD:main'], cwd=cwd)
        if published.returncode == 0:
            return 0
    return published.returncode


if __name__ == '__main__':
    if os.environ.get('GITHUB_REPOSITORY') != 'lamwanho/hk-secondary-school-crawler':
        raise SystemExit('Checkpoint publishing is restricted to the public school crawler workflow.')
    raise SystemExit(publish_checkpoint())
