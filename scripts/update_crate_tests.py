#!/usr/bin/env python3
#
# Copyright (C) 2020 The Android Open Source Project
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Add or update tests to TEST_MAPPING.

This script uses Bazel to find reverse dependencies on a crate and generates a
TEST_MAPPING file. It accepts the absolute path to a crate as argument. If no
argument is provided, it assumes the crate is the current directory.

  Usage:
  $ . build/envsetup.sh
  $ lunch aosp_arm64-eng
  $ update_crate_tests.py $ANDROID_BUILD_TOP/external/rust/crates/libc

This script is automatically called by external_updater.
"""

import json
import os
import platform
import subprocess
import sys

# Some tests requires specific options. Consider fixing the upstream crate
# before updating this dictionary.
TEST_OPTIONS = {
    "ring_device_test_tests_digest_tests": [{"test-timeout": "600000"}],
    "ring_device_test_src_lib": [{"test-timeout": "100000"}],
}

# Excluded tests. These tests will be ignored by this script.
TEST_EXCLUDE = [
        "aidl_test_rust_client",
        "aidl_test_rust_service"
]

# Excluded modules.
EXCLUDE_PATHS = [
        "//external/adhd",
        "//external/crosvm",
        "//external/libchromeos-rs",
        "//external/vm_tools"
]


class UpdaterException(Exception):
    """Exception generated by this script."""


class Env(object):
    """Env captures the execution environment.

    It ensures this script is executed within an AOSP repository.

    Attributes:
      ANDROID_BUILD_TOP: A string representing the absolute path to the top
        of the repository.
    """
    def __init__(self):
        try:
            self.ANDROID_BUILD_TOP = os.environ['ANDROID_BUILD_TOP']
        except KeyError:
            raise UpdaterException('$ANDROID_BUILD_TOP is not defined; you '
                                   'must first source build/envsetup.sh and '
                                   'select a target.')


class Bazel(object):
    """Bazel wrapper.

    The wrapper is used to call bazel queryview and generate the list of
    reverse dependencies.

    Attributes:
      path: The path to the bazel executable.
    """
    def __init__(self, env):
        """Constructor.

        Note that the current directory is changed to ANDROID_BUILD_TOP.

        Args:
          env: An instance of Env.

        Raises:
          UpdaterException: an error occurred while calling soong_ui.
        """
        if platform.system() != 'Linux':
            raise UpdaterException('This script has only been tested on Linux.')
        self.path = os.path.join(env.ANDROID_BUILD_TOP, "tools", "bazel")
        soong_ui = os.path.join(env.ANDROID_BUILD_TOP, "build", "soong", "soong_ui.bash")

        # soong_ui requires to be at the root of the repository.
        os.chdir(env.ANDROID_BUILD_TOP)
        print("Generating Bazel files...")
        cmd = [soong_ui, "--make-mode", "GENERATE_BAZEL_FILES=1", "nothing"]
        try:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            raise UpdaterException('Unable to generate bazel workspace: ' + e.output)

        print("Building Bazel Queryview. This can take a couple of minutes...")
        cmd = [soong_ui, "--build-mode", "--all-modules", "--dir=.", "queryview"]
        try:
            subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        except subprocess.CalledProcessError as e:
            raise UpdaterException('Unable to update TEST_MAPPING: ' + e.output)

    def query_modules(self, path):
        """Returns all modules for a given path."""
        cmd = self.path + " query --config=queryview /" + path + ":all"
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, text=True).strip().split("\n")
        modules = set()
        for line in out:
            # speed up by excluding unused modules.
            if "windows_x86" in line:
                continue
            modules.add(line)
        return modules

    def query_rdeps(self, module):
        """Returns all reverse dependencies for a single module."""
        cmd = (self.path + " query --config=queryview \'rdeps(//..., " +
                module + ")\' --output=label_kind")
        out = (subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, text=True)
                .strip().split("\n"))
        if '' in out:
            out.remove('')
        return out

    def exclude_module(self, module):
        for path in EXCLUDE_PATHS:
            if module.startswith(path):
                return True
        return False

    def query_rdep_tests(self, modules):
        """Returns all reverse dependency tests for modules in this package."""
        rdep_tests = set()
        for module in modules:
            for rdep in self.query_rdeps(module):
                rule_type, _, mod = rdep.split(" ")
                if rule_type == "rust_test_" or rule_type == "rust_test":
                    if self.exclude_module(mod) == False:
                        rdep_tests.add(mod.split(":")[1].split("--")[0])
        return rdep_tests


class Package(object):
    """A Bazel package.

    Attributes:
      dir: The absolute path to this package.
      dir_rel: The relative path to this package.
      rdep_tests: The list of computed reverse dependencies.
    """
    def __init__(self, path, env, bazel):
        """Constructor.

        Note that the current directory is changed to the package location when
        called.

        Args:
          path: Path to the package.
          env: An instance of Env.
          bazel: An instance of Bazel.

        Raises:
          UpdaterException: the package does not appear to belong to the
            current repository.
        """
        self.dir = path
        try:
            self.dir_rel = self.dir.split(env.ANDROID_BUILD_TOP)[1]
        except IndexError:
            raise UpdaterException('The path ' + self.dir + ' is not under ' +
                            env.ANDROID_BUILD_TOP + '; You must be in the '
                            'directory of a crate or pass its absolute path '
                            'as the argument.')

        # Move to the package_directory.
        os.chdir(self.dir)
        modules = bazel.query_modules(self.dir_rel)
        self.rdep_tests = bazel.query_rdep_tests(modules)

    def get_rdep_tests(self):
        return self.rdep_tests


class TestMapping(object):
    """A TEST_MAPPING file.

    Attributes:
      package: The package associated with this TEST_MAPPING file.
    """
    def __init__(self, env, bazel, path):
        """Constructor.

        Args:
          env: An instance of Env.
          bazel: An instance of Bazel.
          path: The absolute path to the package.
        """
        self.package = Package(path, env, bazel)

    def create(self):
        """Generates the TEST_MAPPING file."""
        tests = self.package.get_rdep_tests()
        if not bool(tests):
            return
        test_mapping = self.tests_to_mapping(tests)
        self.write_test_mapping(test_mapping)

    def tests_to_mapping(self, tests):
        """Translate the test list into a dictionary."""
        test_mapping = {"presubmit": []}
        for test in tests:
            if test in TEST_EXCLUDE:
                continue
            if test in TEST_OPTIONS:
                test_mapping["presubmit"].append({"name": test, "options": TEST_OPTIONS[test]})
            else:
                test_mapping["presubmit"].append({"name": test})
        test_mapping["presubmit"] = sorted(test_mapping["presubmit"], key=lambda t: t["name"])
        return test_mapping

    def write_test_mapping(self, test_mapping):
        """Writes the TEST_MAPPING file."""
        with open("TEST_MAPPING", "w") as json_file:
            json_file.write("// Generated by update_crate_tests.py for tests that depend on this crate.\n")
            json.dump(test_mapping, json_file, indent=2, separators=(',', ': '), sort_keys=True)
            json_file.write("\n")
        print("TEST_MAPPING successfully updated for %s!" % self.package.dir_rel)


def main():
    if len(sys.argv) > 1:
        paths = sys.argv[1:]
    else:
        paths = [os.getcwd()]
    env = Env()
    bazel = Bazel(env)
    for path in paths:
        try:
            test_mapping = TestMapping(env, bazel, path)
        except UpdaterException as err:
            sys.exit("Error: " + str(err))
        test_mapping.create()

if __name__ == '__main__':
  main()