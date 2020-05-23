# -*- coding: utf-8 -*-
#
# Copyright Kevin Deldycke <kevin@deldycke.com> and contributors.
# All Rights Reserved.
#
# This program is Free Software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place - Suite 330, Boston, MA  02111-1307, USA.

# pylint: disable=redefined-outer-name

import os

import pytest
import simplejson as json

from .conftest import MANAGER_IDS, destructive, run_cmd, unless_macos
from .test_cli import CLISubCommandTests, CLITableTests


@pytest.fixture
def subcmd():
    return 'outdated'


# Default location of Homebrew Cask formulas on macOS. This is supposed to be a
# shallow copy of the following Git repository:
# https://github.com/Homebrew/homebrew-cask
CASK_PATH = '/usr/local/Homebrew/Library/Taps/homebrew/homebrew-cask/Casks/'


@pytest.fixture
def install_cask():

    packages = set()

    def git_checkout(package_id, commit):
        code, _, _ = run_cmd(
            'git', '-C', CASK_PATH, 'checkout', commit,
            "{}.rb".format(package_id))
        assert code == 0

    def _install_cask(package_id, commit):
        packages.add(package_id)
        # Deepen homebrew repository copy so we can dig into the past.
        # Arbitrary set oldest reference to 2018-01-01, which gives us enough
        # to dig into the past.
        code, _, _ = run_cmd(
            'git', '-C', CASK_PATH, 'fetch', '--shallow-since=2018-01-01')
        assert code == 0
        # Fetch locally the old version of the Cask's formula.
        git_checkout(package_id, commit)
        # Install the cask but bypass its local cache auto-update: we want to
        # force brew to rely on our formula from the past.
        os.environ['HOMEBREW_NO_AUTO_UPDATE'] = '1'
        code, output, error = run_cmd('brew', 'cask', 'reinstall', package_id)
        # Reset our temporary environment variable.
        del os.environ['HOMEBREW_NO_AUTO_UPDATE']
        # Restore old formula to its most recent version.
        git_checkout(package_id, 'HEAD')
        # Check the cask has been properly installed.
        assert code == 0
        if error:
            assert "is already installed" not in error
        assert "{} was successfully installed!".format(package_id) in output
        return output

    yield _install_cask

    # Remove all installed packages.
    for package_id in packages:
        run_cmd('brew', 'cask', 'uninstall', '--force', package_id)


class TestOutdated(CLISubCommandTests, CLITableTests):

    @pytest.mark.parametrize('mid', MANAGER_IDS)
    def test_single_manager(self, invoke, mid, subcmd):
        result = invoke('--manager', mid, subcmd)
        assert result.exit_code == 0
        self.check_manager_selection(result, {mid})

    def test_json_parsing(self, invoke, subcmd):
        result = invoke('--output-format', 'json', subcmd)
        assert result.exit_code == 0
        data = json.loads(result.stdout)

        assert data
        assert isinstance(data, dict)
        assert set(data).issubset(MANAGER_IDS)

        for manager_id, info in data.items():
            assert isinstance(manager_id, str)
            assert isinstance(info, dict)

            assert isinstance(info['id'], str)
            assert isinstance(info['name'], str)

            keys = {'errors', 'id', 'name', 'packages'}
            if 'upgrade_all_cli' in info:
                assert isinstance(info['upgrade_all_cli'], str)
                keys.add('upgrade_all_cli')
            assert set(info) == keys

            assert isinstance(info['errors'], list)
            if info['errors']:
                assert set(map(type, info['errors'])) == {str}

            assert info['id'] == manager_id

            assert isinstance(info['packages'], list)
            for pkg in info['packages']:
                assert isinstance(pkg, dict)

                assert set(pkg) == {
                    'id', 'installed_version', 'latest_version', 'name',
                    'upgrade_cli'}

                assert isinstance(pkg['id'], str)
                assert isinstance(pkg['installed_version'], str)
                assert isinstance(pkg['latest_version'], str)
                assert isinstance(pkg['name'], str)
                assert isinstance(pkg['upgrade_cli'], str)

    def test_cli_format_plain(self, invoke, subcmd):
        result = invoke(
            '--output-format', 'json', subcmd, '--cli-format', 'plain')
        for outdated in json.loads(result.stdout).values():
            for infos in outdated['packages']:
                assert isinstance(infos['upgrade_cli'], str)

    def test_cli_format_fragments(self, invoke, subcmd):
        result = invoke(
            '--output-format', 'json', subcmd, '--cli-format', 'fragments')
        for outdated in json.loads(result.stdout).values():
            for infos in outdated['packages']:
                assert isinstance(infos['upgrade_cli'], list)
                assert set(map(type, infos['upgrade_cli'])) == {str}

    def test_cli_format_bitbar(self, invoke, subcmd):
        result = invoke(
            '--output-format', 'json', subcmd, '--cli-format', 'bitbar')
        for outdated in json.loads(result.stdout).values():
            for infos in outdated['packages']:
                assert isinstance(infos['upgrade_cli'], str)
                assert 'param1=' in infos['upgrade_cli']

    @destructive
    @unless_macos
    def test_autoupdate_unicode_name(self, invoke, subcmd, install_cask):
        """ See #16. """
        # Install an old version of a package with a unicode name.
        # Old Cask formula for ubersicht 1.4.60.
        output = install_cask(
            'ubersicht', 'bb72da6c085c017f6bccebbfee5e3bc4837f3165')
        assert 'Uebersicht-1.4.60.app.zip' in output
        assert 'Übersicht.app' in output
        assert 'Übersicht.app' not in output

        # Ubersicht is not reported as outdated because is tagged as
        # auto-update.
        result = invoke('--manager', 'cask', subcmd)
        assert result.exit_code == 0
        assert "ubersicht" not in result.stdout
        assert "Übersicht" not in result.stdout

        # Try with explicit option.
        result = invoke('--ignore-auto-updates', '--manager', 'cask', subcmd)
        assert result.exit_code == 0
        assert "ubersicht" not in result.stdout
        assert "Übersicht" not in result.stdout

        # Look for reported available upgrade.
        # TODO: replace with invoke, but the later somehow cache results.
        code, output, error = run_cmd(
            'mpm', '--include-auto-updates', '--manager', 'cask', subcmd)
        assert code == 0
        assert not error
        assert "ubersicht" in output
        # Outdated subcommand does not fetch the unicode name by default.
        assert "Übersicht" not in output

    @destructive
    @unless_macos
    def test_multiple_names(self, invoke, subcmd, install_cask):
        """ See #26. """
        # Install an old version of a package with multiple names.
        # Old Cask formula for xld 2018.10.19.
        output = install_cask(
            'xld', '89536da7075aa3ac9683a67189fddbed4a7d818c')
        assert 'xld-20181019.dmg' in output
        assert 'XLD.app' in output

        # Look for reported available upgrade.
        # TODO: replace with invoke, but the later somehow cache results.
        code, output, error = run_cmd(
            'mpm', '--include-auto-updates', '--manager', 'cask', subcmd)
        assert code == 0
        assert "xld" in output
        # Outdated subcommand does not fetch the unicode name by default.
        assert "X Lossless Decoder" not in output
