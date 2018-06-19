# Copyright (C) 2016-2018 H. Turgut Uyar <uyar@itu.edu.tr>
#
# Calico is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Calico is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Calico.  If not, see <http://www.gnu.org/licenses/>.

"""The module that contains the base classes for Calico."""

import logging
import os
import shutil
from collections import OrderedDict
from enum import Enum

import pexpect


MAX_LEN = 40
SUPPORTS_JAIL = shutil.which("fakechroot") is not None

_logger = logging.getLogger(__name__)


class ActionType(Enum):
    """Type of an action."""

    EXPECT = ("e", "expect")
    SEND = ("s", "send")


class Action:
    """An action in a test script."""

    def __init__(self, type_, data, *, timeout=None):
        """Initialize this action.

        :sig: (ActionType, str, Optional[int]) -> None
        :param type_: Expect or send.
        :param data: Data to expect or send.
        :param timeout: Timeout duration, in seconds.
        """
        self.type_ = type_  # sig: ActionType
        """Type of this action, expect or send."""

        self.data = data if data != "_EOF_" else pexpect.EOF  # sig: str
        """Data description of this action, what to expect or send."""

        self.timeout = timeout  # sig: Optional[int]
        """Timeout duration of this action."""

    def __iter__(self):
        """Get components of this action as a sequence."""
        yield self.type_.value[0]
        yield self.data if self.data != pexpect.EOF else "_EOF_"
        yield self.timeout


class TestCase:
    """A case in a test suite."""

    def __init__(
        self,
        name,
        *,
        command,
        timeout=None,
        returns=None,
        points=None,
        blocker=False,
        visible=True,
    ):
        """Initialize this test case.

        :sig:
            (
                str,
                str,
                Optional[int],
                Optional[int],
                Optional[Union[int, float]],
                Optional[bool],
                Optional[bool]
            ) -> None
        :param name: Name of the case.
        :param command: Command to run.
        :param timeout: Timeout duration, in seconds.
        :param returns: Expected return value.
        :param points: Contribution to overall points.
        :param blocker: Whether failure blocks subsequent cases.
        :param visible: Whether the test will be visible during the run.
        """
        self.name = name  # sig: str
        """Name of this test case."""

        self.command = command  # sig: str
        """Command to run in this test case."""

        self.script = []  # sig: List[Action]
        """Sequence of actions to run in this test case."""

        self.timeout = timeout  # sig: Optional[int]
        """Timeout duration of this test case, in seconds."""

        self.returns = returns  # sig: Optional[int]
        """Expected return value of this test case."""

        self.points = points  # sig: Optional[Union[int, float]]
        """How much this test case contributes to the total points."""

        self.blocker = blocker  # sig: bool
        """Whether failure in this case will block subsequent cases or not."""

        self.visible = visible  # sig: bool
        """Whether this test will be visible during the run or not."""

    def add_action(self, action):
        """Append an action to the script of this test case.

        :sig: (Action) -> None
        :param action: Action to append to the script.
        """
        self.script.append(action)

    def run(self, *, jailed=False):
        """Run this test and produce a report.

        :sig: (Optional[bool]) -> Mapping[str, Union[str, List[str]]]
        :param jailed: Whether to jail the command to the current directory.
        :return: Result report of the test.
        """
        report = {"errors": []}

        jail_prefix = f"fakechroot chroot {os.getcwd()} " if jailed else ""
        command = f"{jail_prefix}{self.command}"
        _logger.debug("running command: %s", command)

        exit_status, errors = self.run_script(command)
        report["errors"].extend(errors)

        if (self.returns is not None) and (exit_status != self.returns):
            report["errors"].append("Incorrect exit status.")

        return report

    def run_script(self, command):
        """Run the command of this test case and check whether it follows the script.

        :sig: (str) -> Tuple[int, List[str]]
        :return: Exit status and errors.
        """
        process = pexpect.spawn(command)
        process.setecho(False)
        errors = []
        for action in self.script:
            if action.type_ == ActionType.EXPECT:
                try:
                    _logger.debug(
                        "  expecting%s: %s",
                        " (%ss)" % action.timeout if action.timeout is not None else "",
                        action.data,
                    )
                    process.expect(action.data, timeout=action.timeout)
                    received = "_EOF_" if ".EOF" in repr(process.after) else process.after
                    _logger.debug("  received: %s", received)
                except pexpect.EOF:
                    received = "_EOF_" if ".EOF" in repr(process.before) else process.before
                    _logger.debug("  received: %s", received)
                    process.close(force=True)
                    _logger.debug("FAILED: Expected output not received.")
                    errors.append("Expected output not received.")
                    break
                except pexpect.TIMEOUT:
                    received = "_EOF_" if ".EOF" in repr(process.before) else process.before
                    _logger.debug("  received: %s", received)
                    process.close(force=True)
                    _logger.debug("FAILED: Timeout exceeded.")
                    errors.append("Timeout exceeded.")
                    break
            elif action == ActionType.SEND:
                _logger.debug("  sending: %s", action.data)
                process.sendline(action.data)
        else:
            process.close(force=True)
        return process.exitstatus, errors


class Calico(OrderedDict):
    """A suite containing a collection of ordered test cases."""

    def __init__(self):
        """Initialize this test suite from a given specification.

        :sig: () -> None
        """
        super().__init__()

        self.points = 0  # sig: Union[int, float]
        """Total points in this test suite."""

    def add_case(self, case):
        """Add a test case to this suite.

        :sig: (TestCase) -> None
        :param case: Test case to add.
        """
        super().__setitem__(case.name, case)
        self.points += case.points if case.points is not None else 0

    def run(self, *, quiet=False):
        """Run this test suite.

        :sig: (Optional[bool]) -> Mapping[str, Any]
        :param quiet: Whether to suppress progress messages.
        :return: A report containing the results.
        """
        report = OrderedDict()
        earned_points = 0

        os.environ["TERM"] = "dumb"  # disable color output in terminal

        for test_name, test in self.items():
            _logger.debug("starting test %s", test_name)
            if (not quiet) and test.visible:
                dots = "." * (MAX_LEN - len(test_name) + 1)
                print(f"{test_name} {dots}", end=" ")

            jailed = SUPPORTS_JAIL and test_name.startswith("case_")
            report[test_name] = test.run(jailed=jailed)
            passed = len(report[test_name]["errors"]) == 0

            if test.points is None:
                if (not quiet) and test.visible:
                    print("PASSED" if passed else "FAILED")
            else:
                report[test_name]["points"] = test.points if passed else 0
                earned_points += report[test_name]["points"]
                if (not quiet) and test.visible:
                    scored = report[test_name]["points"]
                    print(f"{scored} / {test.points}")

            if test.blocker and (not passed):
                break

        report["points"] = earned_points
        return report