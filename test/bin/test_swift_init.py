# Copyright (c) 2010 OpenStack, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import unittest

import os
import sys
import signal
from shutil import rmtree
from contextlib import contextmanager
from tempfile import mkdtemp
from collections import defaultdict
from threading import Thread
from time import sleep

from test import bin  # for reloading...
from test.bin import swift_init  # for testing...

DUMMY_SIG = 1


@contextmanager
def temptree(files, contents=''):
    # generate enough contents to fill the files
    c = len(files)
    contents = (list(contents) + [''] * c)[:c]
    tempdir = mkdtemp()
    for path, content in zip(files, contents):
        if os.path.isabs(path):
            path = '.' + path
        new_path = os.path.join(tempdir, path)
        subdir = os.path.dirname(new_path)
        if not os.path.exists(subdir):
            os.makedirs(subdir)
        with open(new_path, 'w') as f:
            f.write(str(content))
    try:
        yield tempdir
    finally:
        rmtree(tempdir)


class MockOs():

    def __init__(self, pids):
        self.running_pids = pids
        self.pid_sigs = defaultdict(list)
        self.closed_fds = []
        self.child_pid = 9999  # fork defaults to test parent process path
        self.execlp_called = False

    def kill(self, pid, sig):
        if pid not in self.running_pids:
            raise OSError(3, 'No such process')
        self.pid_sigs[pid].append(sig)

    def __getattr__(self, name):
        # I only over-ride portions of the os module
        try:
            return object.__getattr__(self, name)
        except AttributeError:
            return getattr(os, name)


def pop_stream(f):
    """read everything out of file from the top and clear it out
    """
    f.flush()
    f.seek(0)
    output = f.read()
    f.seek(0)
    f.truncate()
    #print >> sys.stderr, output
    return output


class TestSwiftInitModule(unittest.TestCase):

    def test_servers(self):
        main_plus_rest = set(swift_init.MAIN_SERVERS + swift_init.REST_SERVERS)
        self.assertEquals(set(swift_init.ALL_SERVERS), main_plus_rest)
        # make sure there's no server listed in both
        self.assertEquals(len(main_plus_rest), len(swift_init.MAIN_SERVERS) +
                          len(swift_init.REST_SERVERS))

    def test_setup_env(self):
        # TODO: tests
        pass

    def test_search_tree(self):
        # file match & ext miss
        with temptree(['asdf.conf', 'blarg.conf', 'asdf.cfg']) as t:
            asdf = swift_init.search_tree(t, 'a*', '.conf')
            self.assertEquals(len(asdf), 1)
            self.assertEquals(asdf[0],
                              os.path.join(t, 'asdf.conf'))

        # multi-file match & glob miss & sort
        with temptree(['application.bin', 'apple.bin', 'apropos.bin']) as t:
            app_bins = swift_init.search_tree(t, 'app*', 'bin')
            self.assertEquals(len(app_bins), 2)
            self.assertEquals(app_bins[0],
                              os.path.join(t, 'apple.bin'))
            self.assertEquals(app_bins[1],
                              os.path.join(t, 'application.bin'))

        # test file in folder & ext miss & glob miss
        files = (
            'sub/file1.ini',
            'sub/file2.conf',
            'sub.bin',
            'bus.ini',
            'bus/file3.ini',
        )
        with temptree(files) as t:
            sub_ini = swift_init.search_tree(t, 'sub*', '.ini')
            self.assertEquals(len(sub_ini), 1)
            self.assertEquals(sub_ini[0],
                              os.path.join(t, 'sub/file1.ini'))

        # test multi-file in folder & sub-folder & ext miss & glob miss
        files = (
            'folder_file.txt',
            'folder/1.txt',
            'folder/sub/2.txt',
            'folder2/3.txt',
            'Folder3/4.txt'
            'folder.rc',
        )
        with temptree(files) as t:
            folder_texts = swift_init.search_tree(t, 'folder*', '.txt')
            self.assertEquals(len(folder_texts), 4)
            f1 = os.path.join(t, 'folder_file.txt')
            f2 = os.path.join(t, 'folder/1.txt')
            f3 = os.path.join(t, 'folder/sub/2.txt')
            f4 = os.path.join(t, 'folder2/3.txt')
            for f in [f1, f2, f3, f4]:
                self.assert_(f in folder_texts)

    def test_write_file(self):
        with temptree([]) as t:
            file_name = os.path.join(t, 'test')
            swift_init.write_file(file_name, 'test')
            with open(file_name, 'r') as f:
                contents = f.read()
            self.assertEquals(contents, 'test')
            # and also subdirs
            file_name = os.path.join(t, 'subdir/test2')
            swift_init.write_file(file_name, 'test2')
            with open(file_name, 'r') as f:
                contents = f.read()
            self.assertEquals(contents, 'test2')
            # but can't over-write files
            file_name = os.path.join(t, 'subdir/test2/test3')
            self.assertRaises(IOError, swift_init.write_file, file_name,
                              'test3')

    def test_remove_file(self):
        with temptree([]) as t:
            file_name = os.path.join(t, 'blah.pid')
            # assert no raise
            self.assertEquals(os.path.exists(file_name), False)
            self.assertEquals(swift_init.remove_file(file_name), None)
            with open(file_name, 'w') as f:
                f.write('1')
            self.assert_(os.path.exists(file_name))
            self.assertEquals(swift_init.remove_file(file_name), None)
            self.assertFalse(os.path.exists(file_name))

    def test_command_wrapper(self):
        @swift_init.command
        def myfunc(arg1):
            """test doc
            """
            return arg1

        self.assertEquals(myfunc.__doc__.strip(), 'test doc')
        self.assertEquals(myfunc(1), 1)
        self.assertEquals(myfunc(0), 0)
        self.assertEquals(myfunc(True), 1)
        self.assertEquals(myfunc(False), 0)
        self.assert_(hasattr(myfunc, 'publicly_accessible'))
        self.assert_(myfunc.publicly_accessible)

    def test_exc(self):
        self.assert_(issubclass(swift_init.UnknownCommand, Exception))


class TestSwiftServerClass(unittest.TestCase):

    def tearDown(self):
        reload(bin)

    def join_swift_dir(self, path):
        return os.path.join(swift_init.SWIFT_DIR, path)

    def join_run_dir(self, path):
        return os.path.join(swift_init.RUN_DIR, path)

    def test_server_init(self):
        server = swift_init.SwiftServer('proxy')
        self.assertEquals(server.server, 'proxy-server')
        self.assertEquals(server.type, 'proxy')
        self.assertEquals(server.cmd, 'swift-proxy-server')
        server = swift_init.SwiftServer('object-replicator')
        self.assertEquals(server.server, 'object-replicator')
        self.assertEquals(server.type, 'object')
        self.assertEquals(server.cmd, 'swift-object-replicator')

    def test_get_pid_file_name(self):
        server = swift_init.SwiftServer('proxy')
        ini_file = self.join_swift_dir('proxy-server.conf')
        pid_file = self.join_run_dir('proxy-server.pid')
        self.assertEquals(pid_file, server.get_pid_file_name(ini_file))
        server = swift_init.SwiftServer('object-replicator')
        ini_file = self.join_swift_dir('object-server/1.conf')
        pid_file = self.join_run_dir('object-replicator/1.pid')
        self.assertEquals(pid_file, server.get_pid_file_name(ini_file))
        server = swift_init.SwiftServer('container-auditor')
        ini_file = self.join_swift_dir(
            'container-server/1/container-auditor.conf')
        pid_file = self.join_run_dir(
            'container-auditor/1/container-auditor.pid')
        self.assertEquals(pid_file, server.get_pid_file_name(ini_file))

    def test_get_ini_file_name(self):
        server = swift_init.SwiftServer('proxy')
        ini_file = self.join_swift_dir('proxy-server.conf')
        pid_file = self.join_run_dir('proxy-server.pid')
        self.assertEquals(ini_file, server.get_ini_file_name(pid_file))
        server = swift_init.SwiftServer('object-replicator')
        ini_file = self.join_swift_dir('object-server/1.conf')
        pid_file = self.join_run_dir('object-replicator/1.pid')
        self.assertEquals(ini_file, server.get_ini_file_name(pid_file))
        server = swift_init.SwiftServer('container-auditor')
        ini_file = self.join_swift_dir(
            'container-server/1/container-auditor.conf')
        pid_file = self.join_run_dir(
            'container-auditor/1/container-auditor.pid')
        self.assertEquals(ini_file, server.get_ini_file_name(pid_file))

    def test_ini_files(self):
        # test get single ini file
        ini_files = (
            'proxy-server.conf',
            'proxy-server.ini',
            'auth-server.conf',
        )
        with temptree(ini_files) as t:
            swift_init.SWIFT_DIR = t
            server = swift_init.SwiftServer('proxy')
            ini_files = server.ini_files()
            self.assertEquals(len(ini_files), 1)
            ini_file = ini_files[0]
            proxy_conf = self.join_swift_dir('proxy-server.conf')
            self.assertEquals(ini_file, proxy_conf)

        # test multi server conf files & grouping of server-type config
        ini_files = (
            'object-server1.conf',
            'object-server/2.conf',
            'object-server/object3.conf',
            'object-server/conf/server4.conf',
            'object-server.txt',
            'proxy-server.conf',
        )
        with temptree(ini_files) as t:
            swift_init.SWIFT_DIR = t
            server = swift_init.SwiftServer('object-replicator')
            ini_files = server.ini_files()
            self.assertEquals(len(ini_files), 4)
            c1 = self.join_swift_dir('object-server1.conf')
            c2 = self.join_swift_dir('object-server/2.conf')
            c3 = self.join_swift_dir('object-server/object3.conf')
            c4 = self.join_swift_dir('object-server/conf/server4.conf')
            for c in [c1, c2, c3, c4]:
                self.assert_(c in ini_files)
            # test configs returned sorted
            sorted_confs = sorted([c1, c2, c3, c4])
            self.assertEquals(ini_files, sorted_confs)

        # test get single numbered conf
        ini_files = (
            'account-server/1.conf',
            'account-server/2.conf',
            'account-server/3.conf',
            'account-server/4.conf',
        )
        with temptree(ini_files) as t:
            swift_init.SWIFT_DIR = t
            server = swift_init.SwiftServer('account')
            ini_files = server.ini_files(number=2)
            self.assertEquals(len(ini_files), 1)
            ini_file = ini_files[0]
            self.assertEquals(ini_file,
                              self.join_swift_dir('account-server/2.conf'))
            # test missing config number
            ini_files = server.ini_files(number=5)
            self.assertFalse(ini_files)

        # test verbose & quiet
        ini_files = (
            'auth-server.ini',
            'container-server/1.conf',
        )
        with temptree(ini_files) as t:
            swift_init.SWIFT_DIR = t
            old_stdout = sys.stdout
            try:
                with open(os.path.join(t, 'output'), 'w+') as f:
                    sys.stdout = f
                    server = swift_init.SwiftServer('auth')
                    # check warn "unable to locate"
                    ini_files = server.ini_files()
                    self.assertFalse(ini_files)
                    self.assert_('unable to locate' in pop_stream(f).lower())
                    # check quiet will silence warning
                    ini_files = server.ini_files(verbose=True, quiet=True)
                    self.assertEquals(pop_stream(f), '')
                    # check found config no warning
                    server = swift_init.SwiftServer('container-auditor')
                    ini_files = server.ini_files()
                    self.assertEquals(pop_stream(f), '')
                    # check missing config number warn "unable to locate"
                    ini_files = server.ini_files(number=2)
                    self.assert_('unable to locate' in pop_stream(f).lower())
                    # check verbose lists configs
                    ini_files = server.ini_files(number=2, verbose=True)
                    c1 = self.join_swift_dir('container-server/1.conf')
                    self.assert_(c1 in pop_stream(f))
            finally:
                sys.stdout = old_stdout

    def test_iter_pid_files(self):
        """
        SwiftServer.iter_pid_files is kinda boring, test the
        SwiftServer.pid_files stuff here as well
        """
        pid_files = (
            ('proxy-server.pid', 1),
            ('auth-server.pid', 'blah'),
            ('object-replicator/1.pid', 11),
            ('object-replicator/2.pid', 12),
        )
        files, contents = zip(*pid_files)
        with temptree(files, contents) as t:
            swift_init.RUN_DIR = t
            server = swift_init.SwiftServer('proxy')
            # test get one file
            iter = server.iter_pid_files()
            pid_file, pid = iter.next()
            self.assertEquals(pid_file, self.join_run_dir('proxy-server.pid'))
            self.assertEquals(pid, 1)
            # ... and only one file
            self.assertRaises(StopIteration, iter.next)
            # test invalid value in pid file
            server = swift_init.SwiftServer('auth')
            self.assertRaises(ValueError, server.iter_pid_files().next)
            # test object-server doesn't steal pids from object-replicator
            server = swift_init.SwiftServer('object')
            self.assertRaises(StopIteration, server.iter_pid_files().next)
            # test multi-pid iter
            server = swift_init.SwiftServer('object-replicator')
            real_map = {
                11: self.join_run_dir('object-replicator/1.pid'),
                12: self.join_run_dir('object-replicator/2.pid'),
            }
            pid_map = {}
            for pid_file, pid in server.iter_pid_files():
                pid_map[pid] = pid_file
            self.assertEquals(pid_map, real_map)

        # test get pid_files by number
        ini_files = (
            'object-server/1.conf',
            'object-server/2.conf',
            'object-server/3.conf',
            'object-server/4.conf',
        )

        pid_files = (
            ('object-server/1.pid', 1),
            ('object-server/2.pid', 2),
            ('object-server/5.pid', 5),
        )

        with temptree(ini_files) as swift_dir:
            swift_init.SWIFT_DIR = swift_dir
            files, pids = zip(*pid_files)
            with temptree(files, pids) as t:
                swift_init.RUN_DIR = t
                server = swift_init.SwiftServer('object')
                # test get all pid files
                real_map = {
                    1: self.join_run_dir('object-server/1.pid'),
                    2: self.join_run_dir('object-server/2.pid'),
                    5: self.join_run_dir('object-server/5.pid'),
                }
                pid_map = {}
                for pid_file, pid in server.iter_pid_files():
                    pid_map[pid] = pid_file
                self.assertEquals(pid_map, real_map)
                # test get pid with matching conf
                pids = list(server.iter_pid_files(number=2))
                self.assertEquals(len(pids), 1)
                pid_file, pid = pids[0]
                self.assertEquals(pid, 2)
                pid_two = self.join_run_dir('object-server/2.pid')
                self.assertEquals(pid_file, pid_two)
                # try to iter on a pid number with a matching conf but no pid
                pids = list(server.iter_pid_files(number=3))
                self.assertFalse(pids)
                # test get pids w/o matching conf
                pids = list(server.iter_pid_files(number=5))
                self.assertFalse(pids)

    def test_signal_pids(self):
        pid_files = (
            ('proxy-server.pid', 1),
            ('auth-server.pid', 2),
        )
        files, pids = zip(*pid_files)
        with temptree(files, pids) as t:
            swift_init.RUN_DIR = t
            # mock os with both pids running
            swift_init.os = MockOs([1, 2])
            server = swift_init.SwiftServer('proxy')
            pids = server.signal_pids(DUMMY_SIG)
            self.assertEquals(len(pids), 1)
            self.assert_(1 in pids)
            self.assertEquals(swift_init.os.pid_sigs[1], [DUMMY_SIG])
            # make sure other process not signaled
            self.assertFalse(2 in pids)
            self.assertFalse(2 in swift_init.os.pid_sigs)
            # capture stdio
            old_stdout = sys.stdout
            try:
                with open(os.path.join(t, 'output'), 'w+') as f:
                    sys.stdout = f
                    #test print details
                    pids = server.signal_pids(DUMMY_SIG)
                    output = pop_stream(f)
                    self.assert_('pid: %s' % 1 in output)
                    self.assert_('signal: %s' % DUMMY_SIG in output)
                    # test no details on signal.SIG_DFL
                    pids = server.signal_pids(signal.SIG_DFL)
                    self.assertEquals(pop_stream(f), '')
                    # reset mock os so only the other server is running
                    swift_init.os = MockOs([2])
                    # test pid not running
                    pids = server.signal_pids(signal.SIG_DFL)
                    self.assert_(1 not in pids)
                    self.assert_(1 not in swift_init.os.pid_sigs)
                    # test remove stale pid file
                    self.assertFalse(os.path.exists(
                        self.join_run_dir('proxy-server.pid')))
                    # reset mock os with no running pids
                    swift_init.os = MockOs([])
                    server = swift_init.SwiftServer('auth')
                    # test verbose warns on removing pid file
                    pids = server.signal_pids(signal.SIG_DFL, verbose=True)
                    output = pop_stream(f)
                    self.assert_('stale pid' in output.lower())
                    auth_pid = self.join_run_dir('auth-server.pid')
                    self.assert_(auth_pid in output)
            finally:
                sys.stdout = old_stdout

    def test_get_running_pids(self):
        # test only gets running pids
        pid_files = (
            ('test-server1.pid', 1),
            ('test-server2.pid', 2),
        )
        with temptree(*zip(*pid_files)) as t:
            swift_init.RUN_DIR = t
            server = swift_init.SwiftServer('test-server')
            # mock os, only pid '1' is running
            swift_init.os = MockOs([1])
            running_pids = server.get_running_pids()
            self.assertEquals(len(running_pids), 1)
            self.assert_(1 in running_pids)
            self.assert_(2 not in running_pids)
            # test persistant running pid files
            self.assert_(os.path.exists(os.path.join(t, 'test-server1.pid')))
            # test clean up stale pids
            pid_two = self.join_swift_dir('test-server2.pid')
            self.assertFalse(os.path.exists(pid_two))
            # reset mock os, no pids running
            swift_init.os = MockOs([])
            running_pids = server.get_running_pids()
            self.assertFalse(running_pids)
            # and now all pid files are cleaned out
            pid_one = self.join_run_dir('test-server1.pid')
            self.assertFalse(os.path.exists(pid_one))
            all_pids = os.listdir(t)
            self.assertEquals(len(all_pids), 0)

        # test only get pids for right server
        pid_files = (
            ('thing-doer.pid', 1),
            ('thing-sayer.pid', 2),
            ('other-doer.pid', 3),
            ('other-sayer.pid', 4),
        )
        files, pids = zip(*pid_files)
        with temptree(files, pids) as t:
            swift_init.RUN_DIR = t
            # all pids are running
            swift_init.os = MockOs(pids)
            server = swift_init.SwiftServer('thing-doer')
            running_pids = server.get_running_pids()
            # only thing-doer.pid, 1
            self.assertEquals(len(running_pids), 1)
            self.assert_(1 in running_pids)
            # no other pids returned
            for n in (2, 3, 4):
                self.assert_(n not in running_pids)
            # assert stale pids for other servers ignored
            swift_init.os = MockOs([1])  # only thing-doer is running
            running_pids = server.get_running_pids()
            for f in ('thing-sayer.pid', 'other-doer.pid', 'other-sayer.pid'):
                # other server pid files persist
                self.assert_(os.path.exists, os.path.join(t, f))
            # verify that servers are in fact not running
            for server_name in ('thing-sayer', 'other-doer', 'other-sayer'):
                server = swift_init.SwiftServer(server_name)
                running_pids = server.get_running_pids()
                self.assertFalse(running_pids)
            # and now all OTHER pid files are cleaned out
            all_pids = os.listdir(t)
            self.assertEquals(len(all_pids), 1)
            self.assert_(os.path.exists(os.path.join(t, 'thing-doer.pid')))

    def test_kill_running_pids(self):
        pid_files = (
            ('object-server.pid', 1),
            ('object-replicator1.pid', 11),
            ('object-replicator2.pid', 12),
        )
        files, pids = zip(*pid_files)
        with temptree(files, pids) as t:
            swift_init.RUN_DIR = t
            server = swift_init.SwiftServer('object')
            # test no servers running
            pids = server.kill_running_pids()
            self.assertFalse(pids)
            # start up pid
            swift_init.os = MockOs([1])
            # test kill one pid
            pids = server.kill_running_pids()
            self.assertEquals(len(pids), 1)
            self.assert_(1 in pids)
            self.assertEquals(swift_init.os.pid_sigs[1], [signal.SIGTERM])
            # reset os mock
            swift_init.os = MockOs([1])
            # test shutdown
            self.assert_('object-server' in
                         swift_init.GRACEFUL_SHUTDOWN_SERVERS)
            pids = server.kill_running_pids(graceful=True)
            self.assertEquals(len(pids), 1)
            self.assert_(1 in pids)
            self.assertEquals(swift_init.os.pid_sigs[1], [signal.SIGHUP])
            # start up other servers
            swift_init.os = MockOs([11, 12])
            # test multi server kill & ignore graceful on unsupport server
            self.assertFalse('object-replicator' in
                             swift_init.GRACEFUL_SHUTDOWN_SERVERS)
            server = swift_init.SwiftServer('object-replicator')
            pids = server.kill_running_pids(graceful=True)
            self.assertEquals(len(pids), 2)
            for pid in (11, 12):
                self.assert_(pid in pids)
                self.assertEquals(swift_init.os.pid_sigs[pid],
                                  [signal.SIGTERM])
            # and the other pid is of course not signaled
            self.assert_(1 not in swift_init.os.pid_sigs)

    def test_status(self):
        ini_files = (
            'test-server/1.conf',
            'test-server/2.conf',
            'test-server/3.conf',
            'test-server/4.conf',
        )

        pid_files = (
            ('test-server/1.pid', 1),
            ('test-server/2.pid', 2),
            ('test-server/3.pid', 3),
            ('test-server/4.pid', 4),
        )

        with temptree(ini_files) as swift_dir:
            swift_init.SWIFT_DIR = swift_dir
            files, pids = zip(*pid_files)
            with temptree(files, pids) as t:
                swift_init.RUN_DIR = t
                # setup running servers
                server = swift_init.SwiftServer('test')
                # capture stdio
                old_stdout = sys.stdout
                try:
                    with open(os.path.join(t, 'output'), 'w+') as f:
                        sys.stdout = f
                        # test status for all running
                        swift_init.os = MockOs(pids)
                        self.assertEquals(server.status(), 0)
                        output = pop_stream(f).strip().splitlines()
                        self.assertEquals(len(output), 4)
                        for line in output:
                            self.assert_('test-server running' in line)
                        # test get single server by number
                        self.assertEquals(server.status(number=4), 0)
                        output = pop_stream(f).strip().splitlines()
                        self.assertEquals(len(output), 1)
                        line = output[0]
                        self.assert_('test-server running' in line)
                        conf_four = self.join_swift_dir(ini_files[3])
                        self.assert_('4 - %s' % conf_four in line)
                        # test some servers not running
                        swift_init.os = MockOs([1, 2, 3])
                        self.assertEquals(server.status(), 0)
                        output = pop_stream(f).strip().splitlines()
                        self.assertEquals(len(output), 3)
                        for line in output:
                            self.assert_('test-server running' in line)
                        # test single server not running
                        swift_init.os = MockOs([1, 2])
                        self.assertEquals(server.status(number=3), 1)
                        output = pop_stream(f).strip().splitlines()
                        self.assertEquals(len(output), 1)
                        line = output[0]
                        self.assert_('not running' in line)
                        conf_three = self.join_swift_dir(ini_files[2])
                        self.assert_(conf_three in line)
                        # test no running pids
                        swift_init.os = MockOs([])
                        self.assertEquals(server.status(), 1)
                        output = pop_stream(f).lower()
                        self.assert_('no test-server running' in output)
                        # test use provided pids
                        pids = {
                            1: '1.pid',
                            2: '2.pid',
                        }
                        # shouldn't call get_running_pids
                        called = []

                        def mock(*args, **kwargs):
                            called.append(True)
                        server.get_running_pids = mock
                        status = server.status(pids=pids)
                        self.assertEquals(status, 0)
                        self.assertFalse(called)
                        output = pop_stream(f).strip().splitlines()
                        self.assertEquals(len(output), 2)
                        for line in output:
                            self.assert_('test-server running' in line)
                finally:
                    sys.stdout = old_stdout

    def test_spawn(self):

        # mocks
        class MockProcess():

            NOTHING = 'default besides None'
            STDOUT = 'stdout'
            PIPE = 'pipe'

            def __init__(self, pids=None):
                if pids is None:
                    pids = []
                self.pids = (p for p in pids)

            def Popen(self, args, **kwargs):
                return MockProc(self.pids.next(), args, **kwargs)

        class MockProc():

            def __init__(self, pid, args, stdout=MockProcess.NOTHING,
                         stderr=MockProcess.NOTHING):
                self.pid = pid
                self.args = args
                self.stdout = stdout
                if stderr == MockProcess.STDOUT:
                    self.stderr = self.stdout
                else:
                    self.stderr = stderr

        # setup running servers
        server = swift_init.SwiftServer('test')

        with temptree(['test-server.conf']) as swift_dir:
            swift_init.SWIFT_DIR = swift_dir
            with temptree([]) as t:
                swift_init.RUN_DIR = t
                old_subprocess = swift_init.subprocess
                try:
                    # test single server process calls spawn once
                    swift_init.subprocess = MockProcess([1])
                    conf_file = self.join_swift_dir('test-server.conf')
                    # spawn server no kwargs
                    server.spawn(conf_file)
                    # test pid file
                    pid_file = self.join_run_dir('test-server.pid')
                    self.assert_(os.path.exists(pid_file))
                    pid_on_disk = int(open(pid_file).read().strip())
                    self.assertEquals(pid_on_disk, 1)
                    # assert procs args
                    self.assert_(server.procs)
                    self.assertEquals(len(server.procs), 1)
                    proc = server.procs[0]
                    expected_args = [
                        'swift-test-server',
                        conf_file,
                    ]
                    self.assertEquals(proc.args, expected_args)
                    # assert stdout is /dev/null
                    self.assert_(isinstance(proc.stdout, file))
                    self.assertEquals(proc.stdout.name, os.devnull)
                    self.assertEquals(proc.stdout.mode, 'w+b')
                    self.assertEquals(proc.stderr, proc.stdout)
                    # test multi server process calls spawn multiple times
                    swift_init.subprocess = MockProcess([11, 12, 13, 14])
                    conf1 = self.join_swift_dir('test-server/1.conf')
                    conf2 = self.join_swift_dir('test-server/2.conf')
                    conf3 = self.join_swift_dir('test-server/3.conf')
                    conf4 = self.join_swift_dir('test-server/4.conf')
                    server = swift_init.SwiftServer('test')
                    # test server run once
                    server.spawn(conf1, once=True)
                    self.assert_(server.procs)
                    self.assertEquals(len(server.procs), 1)
                    proc = server.procs[0]
                    expected_args = ['swift-test-server', conf1, 'once']
                    self.assertEquals(proc.args, expected_args)
                    # assert stdout is /dev/null
                    self.assert_(isinstance(proc.stdout, file))
                    self.assertEquals(proc.stdout.name, os.devnull)
                    self.assertEquals(proc.stdout.mode, 'w+b')
                    self.assertEquals(proc.stderr, proc.stdout)
                    # test server not daemon
                    server.spawn(conf2, daemon=False)
                    self.assert_(server.procs)
                    self.assertEquals(len(server.procs), 2)
                    proc = server.procs[1]
                    expected_args = ['swift-test-server', conf2, 'verbose']
                    self.assertEquals(proc.args, expected_args)
                    # assert stdout is not changed
                    self.assertEquals(proc.stdout, None)
                    self.assertEquals(proc.stderr, None)
                    # test server wait
                    server.spawn(conf3, wait=True)
                    self.assert_(server.procs)
                    self.assertEquals(len(server.procs), 3)
                    proc = server.procs[2]
                    # assert stdout is piped
                    self.assertEquals(proc.stdout, MockProcess.PIPE)
                    self.assertEquals(proc.stderr, proc.stdout)
                    # test not daemon over-rides wait
                    server.spawn(conf4, wait=True, daemon=False, once=True)
                    self.assert_(server.procs)
                    self.assertEquals(len(server.procs), 4)
                    proc = server.procs[3]
                    expected_args = ['swift-test-server', conf4, 'once',
                                     'verbose']
                    self.assertEquals(proc.args, expected_args)
                    # daemon behavior should trump wait, once shouldn't matter
                    self.assertEquals(proc.stdout, None)
                    self.assertEquals(proc.stderr, None)
                    # assert pids
                    for i, proc in enumerate(server.procs):
                        pid_file = self.join_run_dir('test-server/%d.pid' %
                                                     (i + 1))
                        pid_on_disk = int(open(pid_file).read().strip())
                        self.assertEquals(pid_on_disk, proc.pid)
                finally:
                    swift_init.subprocess = old_subprocess

    def test_wait(self):
        server = swift_init.SwiftServer('test')
        self.assertEquals(server.wait(), 0)

        class MockProcess(Thread):
            def __init__(self, delay=0.1, fail_to_start=False):
                Thread.__init__(self)
                # setup pipe
                rfd, wfd = os.pipe()
                # subprocess connection to read stdout
                self.stdout = os.fdopen(rfd)
                # real process connection to write stdout
                self._stdout = os.fdopen(wfd, 'w')
                self.delay = delay
                self.finished = False
                self.returncode = None
                if fail_to_start:
                    self.run = self.fail

            def __enter__(self):
                self.start()
                return self

            def __exit__(self, *args):
                if self.isAlive():
                    self.join()

            def close_stdout(self):
                self._stdout.flush()
                with open(os.devnull, 'wb') as nullfile:
                    try:
                        os.dup2(nullfile.fileno(), self._stdout.fileno())
                    except OSError:
                        pass

            def fail(self):
                print >>self._stdout, 'mock process started'
                sleep(self.delay)  # perform setup processing
                print >>self._stdout, 'mock process failed to start'
                self.returncode = 1
                self.close_stdout()

            def run(self):
                print >>self._stdout, 'mock process started'
                sleep(self.delay)  # perform setup processing
                print >>self._stdout, 'setup complete!'
                self.close_stdout()
                sleep(self.delay)  # do some more processing
                print >>self._stdout, 'mock process finished'
                self.finished = True

        with temptree([]) as t:
            old_stdout = sys.stdout
            try:
                with open(os.path.join(t, 'output'), 'w+') as f:
                    # acctually capture the read stdout (for prints)
                    sys.stdout = f
                    # test closing pipe in subprocess unblocks read
                    with MockProcess() as proc:
                        server.procs = [proc]
                        status = server.wait()
                        self.assertEquals(status, 0)
                        # wait should return as soon as stdout is closed
                        self.assert_(proc.isAlive())
                        self.assertFalse(proc.finished)
                    self.assert_(proc.finished)  # make sure it did finish...
                    # test output kwarg prints subprocess output
                    with MockProcess() as proc:
                        server.procs = [proc]
                        status = server.wait(output=True)
                    output = pop_stream(f)
                    self.assert_('mock process started' in output)
                    self.assert_('setup complete' in output)
                    # make sure we don't get prints after stdout was closed
                    self.assert_('mock process finished' not in output)
                    # test process which fails to start
                    with MockProcess(fail_to_start=True) as proc:
                        server.procs = [proc]
                        status = server.wait()
                        self.assertEquals(status, 1)
                    self.assert_('failed' in pop_stream(f))
                    # test multiple procs
                    procs = [MockProcess() for i in range(3)]
                    for proc in procs:
                        proc.start()
                    server.procs = procs
                    status = server.wait()
                    self.assertEquals(status, 0)
                    for proc in procs:
                        self.assert_(proc.isAlive())
                    for proc in procs:
                        proc.join()
            finally:
                sys.stdout = old_stdout

    def test_interact(self):
        class MockProcess():

            def __init__(self, fail=False):
                self.returncode = None
                if fail:
                    self._returncode = 1
                else:
                    self._returncode = 0

            def communicate(self):
                self.returncode = self._returncode
                return '', ''

        server = swift_init.SwiftServer('test')
        server.procs = [MockProcess()]
        self.assertEquals(server.interact(), 0)
        server.procs = [MockProcess(fail=True)]
        self.assertEquals(server.interact(), 1)
        procs = []
        for fail in (False, True, True):
            procs.append(MockProcess(fail=fail))
        server.procs = procs
        self.assert_(server.interact() > 0)
        
    def test_launch(self):
        # stubs
        ini_files = (
            'proxy-server.conf',
            'object-server/1.conf',
            'object-server/2.conf',
            'object-server/3.conf',
            'object-server/4.conf',
        )
        pid_files = (
            ('proxy-server.pid', 1),
            ('proxy-server/2.pid', 2),
        )

        #mocks
        class MockSpawn():

            def __init__(self, pids=None):
                self.ini_files = []
                self.kwargs = []
                if not pids:
                    def one_forever():
                        while True:
                            yield 1
                    self.pids = one_forever()
                else:
                    self.pids = (x for x in pids)

            def __call__(self, ini_file, **kwargs):
                self.ini_files.append(ini_file)
                self.kwargs.append(kwargs)
                return self.pids.next()

        with temptree(ini_files) as swift_dir:
            swift_init.SWIFT_DIR = swift_dir
            files, pids = zip(*pid_files)
            with temptree(files, pids) as t:
                swift_init.RUN_DIR = t
                old_stdout = sys.stdout
                try:
                    with open(os.path.join(t, 'output'), 'w+') as f:
                        sys.stdout = f
                        # can't start server w/o an conf
                        server = swift_init.SwiftServer('test')
                        self.assertFalse(server.launch())
                        # start mock os running all pids
                        swift_init.os = MockOs(pids)
                        server = swift_init.SwiftServer('proxy')
                        # can't start server if it's already running
                        self.assertFalse(server.launch())
                        output = pop_stream(f)
                        self.assert_('running' in output)
                        ini_file = self.join_swift_dir('proxy-server.conf')
                        self.assert_(ini_file in output)
                        pid_file = self.join_run_dir('proxy-server/2.pid')
                        self.assert_(pid_file in output)
                        self.assert_('already started' in output)
                        # no running pids
                        swift_init.os = MockOs([])
                        # test ignore once for non-start-once server
                        mock_spawn = MockSpawn([1])
                        server.spawn = mock_spawn
                        ini_file = self.join_swift_dir('proxy-server.conf')
                        expected = {
                            1: ini_file,
                        }
                        self.assertEquals(server.launch(once=True), expected)
                        self.assertEquals(mock_spawn.ini_files, [ini_file])
                        expected = {
                            'once': False,
                        }
                        self.assertEquals(mock_spawn.kwargs, [expected])
                        output = pop_stream(f)
                        self.assert_('Starting' in output)
                        self.assert_('once' not in output)
                        # test multi-server kwarg once
                        server = swift_init.SwiftServer('object-replicator')
                        mock_spawn = MockSpawn([1, 2, 3, 4])
                        server.spawn = mock_spawn
                        conf1 = self.join_swift_dir('object-server/1.conf')
                        conf2 = self.join_swift_dir('object-server/2.conf')
                        conf3 = self.join_swift_dir('object-server/3.conf')
                        conf4 = self.join_swift_dir('object-server/4.conf')
                        expected = {
                            1: conf1,
                            2: conf2,
                            3: conf3,
                            4: conf4,
                        }
                        self.assertEquals(server.launch(once=True), expected)
                        self.assertEquals(mock_spawn.ini_files, [conf1, conf2,
                                                                 conf3, conf4])
                        expected = {
                            'once': True,
                        }
                        self.assertEquals(len(mock_spawn.kwargs), 4)
                        for kwargs in mock_spawn.kwargs:
                            self.assertEquals(kwargs, expected)
                        # test number kwarg
                        mock_spawn = MockSpawn([4])
                        server.spawn = mock_spawn
                        expected = {
                            4: conf4,
                        }
                        self.assertEquals(server.launch(number=4), expected)
                        self.assertEquals(mock_spawn.ini_files, [conf4])
                        expected = {
                            'number': 4
                        }
                        self.assertEquals(mock_spawn.kwargs, [expected])


                finally:
                    sys.stdout = old_stdout

    #TODO: more tests
    def test_stop(self):
        ini_files = (
            'account-server/1.conf',
            'account-server/2.conf',
            'account-server/3.conf',
            'account-server/4.conf',
        )
        pid_files = (
            ('account-reaper/1.pid', 1),
            ('account-reaper/2.pid', 2),
            ('account-reaper/3.pid', 3),
            ('account-reaper/4.pid', 4),
        )

        with temptree(ini_files) as swift_dir:
            swift_init.SWIFT_DIR = swift_dir
            files, pids = zip(*pid_files)
            with temptree(files, pids) as t:
                swift_init.RUN_DIR = t
                # start all pids in mock os
                swift_init.os = MockOs(pids)
                server = swift_init.SwiftServer('account-reaper')
                # test kill all running pids
                pids = server.stop()
                self.assertEquals(len(pids), 4)
                for pid in (1, 2, 3, 4):
                    self.assert_(pid in pids)
                    self.assertEquals(swift_init.os.pid_sigs[pid],
                                      [signal.SIGTERM])
                conf1 = self.join_swift_dir('account-reaper/1.conf')
                conf2 = self.join_swift_dir('account-reaper/2.conf')
                conf3 = self.join_swift_dir('account-reaper/3.conf')
                conf4 = self.join_swift_dir('account-reaper/4.conf')
                # reset mock os with only 2 running pids
                swift_init.os = MockOs([3, 4])
                pids = server.stop()
                self.assertEquals(len(pids), 2)
                for pid in (3, 4):
                    self.assert_(pid in pids)
                    self.assertEquals(swift_init.os.pid_sigs[pid],
                                      [signal.SIGTERM])
                self.assertFalse(os.path.exists(conf1))
                self.assertFalse(os.path.exists(conf2))
                # test number kwarg
                swift_init.os = MockOs([3, 4])
                pids = server.stop(number=3)
                self.assertEquals(len(pids), 1)
                expected = {
                    3: conf3,
                }
                self.assert_(pids, expected)
                self.assertEquals(swift_init.os.pid_sigs[3], [signal.SIGTERM])
                self.assertFalse(os.path.exists(conf4))
                self.assertFalse(os.path.exists(conf3))

#TODO: test SwiftInit class
class TestSwiftInitClass(unittest.TestCase):

    def test_placeholder(self):
        pass


#TODO: test main
class TestMain(unittest.TestCase):

    def test_placeholder(self):
        pass


if __name__ == '__main__':
    unittest.main()
