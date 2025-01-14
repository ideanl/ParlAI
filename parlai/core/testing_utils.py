#!/usr/bin/env python

# Copyright (c) Facebook, Inc. and its affiliates.
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""General utilities for helping writing ParlAI unit and integration tests."""

import sys
import os
import unittest
import contextlib
import tempfile
import shutil
import io
from typing import Tuple

# from parlai.core.logging_utils import logger # TODO: Uncomment before completion of #2044

try:
    import torch

    TORCH_AVAILABLE = True
    GPU_AVAILABLE = torch.cuda.device_count() > 0
except ImportError:
    TORCH_AVAILABLE = False
    GPU_AVAILABLE = False

try:
    import git

    git_ = git.Git()
    GIT_AVAILABLE = True
except ImportError:
    git_ = None
    GIT_AVAILABLE = False


DEBUG = False  # change this to true to print to stdout anyway


def is_this_circleci():
    """Return if we are currently running in CircleCI."""
    return bool(os.environ.get('CIRCLECI'))


def skipUnlessTorch(testfn, reason='pytorch is not installed'):
    """Decorate a test to skip if torch is not installed."""
    return unittest.skipUnless(TORCH_AVAILABLE, reason)(testfn)


def skipIfGPU(testfn, reason='Test is CPU-only'):
    """
    Decorate a test to skip if a GPU is available.

    Useful for disabling hogwild tests.
    """
    return unittest.skipIf(GPU_AVAILABLE, reason)(testfn)


def skipUnlessGPU(testfn, reason='Test requires a GPU'):
    """Decorate a test to skip if no GPU is available."""
    return unittest.skipUnless(GPU_AVAILABLE, reason)(testfn)


def skipIfCircleCI(testfn, reason='Test disabled in CircleCI'):
    """Decorate a test to skip if running on CircleCI."""
    return unittest.skipIf(is_this_circleci(), reason)(testfn)


class retry(object):
    """
    Decorator for flaky tests. Test is run up to ntries times, retrying on failure.

    On the last time, the test will simply fail.

    >>> @retry(ntries=10)
    ... def test_flaky(self):
    ...     import random
    ...     self.assertLess(0.5, random.random())
    """

    def __init__(self, ntries=3):
        self.ntries = ntries

    def __call__(self, testfn):
        """Call testfn(), possibly multiple times on failureException."""
        from functools import wraps

        @wraps(testfn)
        def _wrapper(testself, *args, **kwargs):
            for _ in range(self.ntries - 1):
                try:
                    return testfn(testself, *args, **kwargs)
                except testself.failureException:
                    pass
            # last time, actually throw any errors there may be
            return testfn(testself, *args, **kwargs)

        return _wrapper


def git_ls_files(root=None, skip_nonexisting=True):
    """List all files tracked by git."""
    filenames = git_.ls_files(root).split('\n')
    if skip_nonexisting:
        filenames = [fn for fn in filenames if os.path.exists(fn)]
    return filenames


def git_ls_dirs(root=None):
    """List all folders tracked by git."""
    dirs = set()
    for fn in git_ls_files(root):
        dirs.add(os.path.dirname(fn))
    return list(dirs)


def git_changed_files(skip_nonexisting=True):
    """
    List all the changed files in the git repository.

    :param bool skip_nonexisting:
        If true, ignore files that don't exist on disk. This is useful for
        disregarding files created in master, but don't exist in HEAD.
    """
    fork_point = git_.merge_base('origin/master', 'HEAD').strip()
    filenames = git_.diff('--name-only', fork_point).split('\n')
    if skip_nonexisting:
        filenames = [fn for fn in filenames if os.path.exists(fn)]
    return filenames


def git_commit_messages():
    """Output each commit message between here and master."""
    fork_point = git_.merge_base('origin/master', 'HEAD').strip()
    messages = git_.log(fork_point + '..HEAD')
    return messages


def is_new_task_filename(filename):
    """
    Check if a given filename counts as a new task.

    Used in tests and test triggers, and only here to avoid redundancy.
    """
    return (
        'parlai/tasks' in filename
        and 'README' not in filename
        and 'task_list.py' not in filename
    )


class TeeStringIO(io.StringIO):
    """
    StringIO which also prints to stdout.

    Used in case of DEBUG=False to make sure we get verbose output.
    """

    def __init__(self, *args):
        self.stream = sys.stdout
        super().__init__(*args)

    def write(self, data):
        """Write data to stdout and the buffer."""
        if DEBUG and self.stream:
            self.stream.write(data)
        super().write(data)

    def __str__(self):
        return self.getvalue()


@contextlib.contextmanager
def capture_output():
    """
    Suppress all logging output into a single buffer.

    Use as a context manager.

    >>> with capture_output() as output:
    ...     print('hello')
    >>> output.getvalue()
    'hello'
    """
    sio = TeeStringIO()
    with contextlib.redirect_stdout(sio), contextlib.redirect_stderr(sio):
        yield sio


# # TODO: Replace capture_output with this version before completing #2044
# # TODO: Uncomment import statement at the top
# # TODO: IDEA: Pass logger object as parameter to thi function
# @contextlib.contextmanager
# def capture_output():
#     """
#     Suppress all logging output into a single buffer.
#
#     Use as a context manager.
#
#     >>> with capture_output() as output:
#     ...     logger.info('hello')
#     >>> output.getvalue()
#     'hello'
#     """
#     sio = TeeStringIO()
#     previous_level = logger.mute()  # Stop logging to stdout
#     logger.redirect_out(sio)  # Instead log to sio (to preserve output for later)
#     yield sio
#     logger.stop_redirect_out()  # Stop redirecting [Removes handler]
#     logger.unmute(previous_level)  # From now on log to stdout


@contextlib.contextmanager
def tempdir():
    """
    Create a temporary directory.

    Use as a context manager so the directory is automatically cleaned up.

    >>> with tempdir() as tmpdir:
    ...    print(tmpdir)  # prints a folder like /tmp/randomname
    """
    d = tempfile.mkdtemp()
    yield d
    shutil.rmtree(d)


def train_model(opt):
    """
    Run through a TrainLoop.

    If model_file is not in opt, then this helper will create a temporary
    directory to store the model, dict, etc.

    :return: (stdout, valid_results, test_results)
    :rtype: (str, dict, dict)
    """
    import parlai.scripts.train_model as tms

    with capture_output() as output:
        with tempdir() as tmpdir:
            if 'model_file' not in opt:
                opt['model_file'] = os.path.join(tmpdir, 'model')
            if 'dict_file' not in opt:
                opt['dict_file'] = os.path.join(tmpdir, 'model.dict')
            parser = tms.setup_args()
            # needed at the very least to set the overrides.
            parser.set_params(**opt)
            parser.set_params(log_every_n_secs=10)
            popt = parser.parse_args(print_args=False)
            # in some rare cases, like for instance if the model class also
            # overrides its default params, the params override will not
            # be taken into account.
            for k, v in opt.items():
                popt[k] = v
            tl = tms.TrainLoop(popt)
            valid, test = tl.train()

    return (output.getvalue(), valid, test)


def eval_model(opt, skip_valid=False, skip_test=False):
    """
    Run through an evaluation loop.

    :param opt:
        Any non-default options you wish to set.
    :param bool skip_valid:
        If true skips the valid evaluation, and the second return value will be None.
    :param bool skip_test:
        If true skips the test evaluation, and the third return value will be None.

    :return: (stdout, valid_results, test_results)
    :rtype: (str, dict, dict)

    If model_file is not in opt, then this helper will create a temporary directory
    to store the model files, and clean up afterwards. You can keep the directory
    by disabling autocleanup
    """
    import parlai.scripts.eval_model as ems

    parser = ems.setup_args()
    parser.set_params(**opt)
    parser.set_params(log_every_n_secs=10)
    popt = parser.parse_args(print_args=False)

    if popt.get('model_file') and not popt.get('dict_file'):
        popt['dict_file'] = popt['model_file'] + '.dict'

    with capture_output() as output:
        popt['datatype'] = 'valid'
        valid = None if skip_valid else ems.eval_model(popt)
        popt['datatype'] = 'test'
        test = None if skip_test else ems.eval_model(popt)

    return (output.getvalue(), valid, test)


def display_data(opt):
    """
    Run through a display data run.

    :return: (stdout_train, stdout_valid, stdout_test)
    :rtype: (str, str, str)
    """
    import parlai.scripts.display_data as dd

    parser = dd.setup_args()
    parser.set_params(**opt)
    popt = parser.parse_args(print_args=False)

    with capture_output() as train_output:
        popt['datatype'] = 'train:stream'
        dd.display_data(popt)
    with capture_output() as valid_output:
        popt['datatype'] = 'valid:stream'
        dd.display_data(popt)
    with capture_output() as test_output:
        popt['datatype'] = 'test:stream'
        dd.display_data(popt)

    return (train_output.getvalue(), valid_output.getvalue(), test_output.getvalue())


def display_model(opt) -> Tuple[str, str]:
    """
    Run display_model.py.

    :return: (stdout_valid, stdout_test)
    """
    import parlai.scripts.display_model as dm

    parser = dm.setup_args()
    parser.set_params(**opt)
    popt = parser.parse_args(print_args=False)
    with capture_output() as train_output:
        # evalmode so that we don't hit train_step
        popt['datatype'] = 'train:evalmode:stream'
        dm.display_model(popt)
    with capture_output() as valid_output:
        popt['datatype'] = 'valid:stream'
        dm.display_model(popt)
    with capture_output() as test_output:
        popt['datatype'] = 'test:stream'
        dm.display_model(popt)
    return (train_output.getvalue(), valid_output.getvalue(), test_output.getvalue())


def download_unittest_models():
    """Download the unittest pretrained models."""
    from parlai.core.params import ParlaiParser
    from parlai.core.build_data import download_models

    opt = ParlaiParser().parse_args(print_args=False)
    model_filenames = [
        'seq2seq.tar.gz',
        'transformer_ranker.tar.gz',
        'transformer_generator2.tar.gz',
    ]
    with capture_output():
        download_models(opt, model_filenames, 'unittest', version='v2.0')
