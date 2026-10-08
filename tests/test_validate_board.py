"""Black-box committed-blob tests; no provider calls or fabricated feed publication."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

VALIDATOR = Path(__file__).resolve().parents[1] / 'validate_board.py'


class BoardValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name)
        self.git('init', '-q', '-b', 'main')
        self.git('config', 'user.name', 'Test')
        self.git('config', 'user.email', 'test@example.invalid')
        self.old = {'meta': {'slate_date': '2026-10-07'}, 'players': [{'player': 'Old MLB'}]}
        self.write('dashboard_data.json', self.old)
        self.commit()
        self.base = self.git('rev-parse', 'HEAD').stdout.strip()

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.repo), *args], text=True,
                              capture_output=True, check=True)

    def write(self, path, data):
        (self.repo / path).write_text(json.dumps(data, sort_keys=True) + '\n')

    def commit(self):
        self.git('add', '-A')
        # Even a bypassed/absent local pre-push hook cannot bypass the validator.
        self.git('-c', 'core.hooksPath=/dev/null', 'commit', '-q', '--allow-empty', '-m', 'candidate')

    def run_validator(self):
        self.commit()
        return subprocess.run([sys.executable, str(VALIDATOR), '--repo', str(self.repo),
                               '--base', self.base, '--candidate', 'HEAD'],
                              text=True, capture_output=True)

    def nhl(self):
        return {'sport': 'NHL', 'slate_date': '2026-10-08',
                'arms': {'player_goal_scorer_first': {'cards': [{'legs': [{'player': 'Example'}]}]}}}

    def test_valid_transition_with_exact_sidecar(self):
        self.write('dashboard_data.json', self.nhl())
        self.write('nhl_daily.json', self.nhl())
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('exact sidecar bytes', result.stdout)

    def test_wrong_sport_even_with_matching_sidecar_and_bypassed_hook(self):
        bad = self.nhl() | {'sport': 'MLB'}
        self.write('dashboard_data.json', bad)
        self.write('nhl_daily.json', bad)
        result = self.run_validator()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('sport NHL', result.stderr)

    def test_wrong_date_against_previous_canonical(self):
        bad = self.nhl() | {'slate_date': '2026-10-06'}
        self.write('dashboard_data.json', bad)
        self.write('nhl_daily.json', bad)
        self.assertIn('older than previous', self.run_validator().stderr)

    def test_invalid_date(self):
        bad = self.nhl() | {'slate_date': '2026-10-99'}
        self.write('dashboard_data.json', bad)
        self.write('nhl_daily.json', bad)
        self.assertIn('invalid slate_date', self.run_validator().stderr)

    def test_empty_cards_refused(self):
        bad = self.nhl()
        bad['arms']['player_goal_scorer_first']['cards'] = []
        self.write('dashboard_data.json', bad)
        self.write('nhl_daily.json', bad)
        self.assertIn('zero-card', self.run_validator().stderr)

    def test_sidecar_byte_mismatch_even_if_same_json(self):
        self.write('dashboard_data.json', self.nhl())
        (self.repo / 'nhl_daily.json').write_text(json.dumps(self.nhl(), indent=2) + '\n')
        self.assertIn('exact bytes', self.run_validator().stderr)

    def test_zero_card_sidecar_only_preserves_canonical(self):
        empty = self.nhl()
        empty['arms']['player_goal_scorer_first']['cards'] = []
        self.write('nhl_daily.json', empty)
        result = self.run_validator()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('canonical unchanged', result.stdout)

    def test_deleted_canonical_refused(self):
        (self.repo / 'dashboard_data.json').unlink()
        self.assertIn('deleted', self.run_validator().stderr)

    def test_uncommitted_worktree_data_does_not_mask_bad_commit(self):
        bad = self.nhl() | {'sport': 'MLB'}
        self.write('dashboard_data.json', bad)
        self.write('nhl_daily.json', bad)
        self.commit()
        self.write('dashboard_data.json', self.nhl())
        self.write('nhl_daily.json', self.nhl())
        result = subprocess.run([sys.executable, str(VALIDATOR), '--repo', str(self.repo),
                                 '--base', self.base], capture_output=True, text=True)
        self.assertIn('sport NHL', result.stderr)


if __name__ == '__main__':
    unittest.main()
