import pycparser
import copy
import os
import tempfile
import logging
import copy
import subprocess
import shlex
import time
from threading import Timer
from pycparser import c_generator
from pycparser.c_ast import Break


_ENV_ORIG_SRC = 'MUTATE_ORIG_SRC'
_ENV_MODIFIED_SRC = 'MUTATE_MODIFIED_SRC'


def _node_to_str(node):
    '''Produce a string representation of an AST node.'''
    gen = c_generator.CGenerator()
    return gen.visit(node)


def _find_nodes(node, nodetype):
    '''Find nodes of a given type in a given subtree.'''
    nodes = []

    if isinstance(node, nodetype):
        nodes.append(node)
    
    for _, c in node.children():
        nodes.extend(_find_nodes(c, nodetype))

    return nodes


def _get_op_swaps(op, swaps):
    '''Find the set of mutations to perform on a given op.'''
    ops = set()
    for s in swaps:
        if op in s:
            ops |= s - set(op)

    return ops


def _run_process(cmd, env_vars=None, timeout_sec=0, log_filename=None):
    def timeout(p):
        p.kill()
        raise TimeoutException()

    env = os.environ.copy()
    if env_vars is not None:
        env.update(env_vars)

    if log_filename is not None:
        log_file = open(log_filename, 'w')
        p = subprocess.Popen(shlex.split(cmd),
                             env=env,
                             stdout=log_file,
                             stderr=log_file)
    else:
        p = subprocess.Popen(shlex.split(cmd), env=env)

    timer = Timer(timeout_sec, timeout, [p])
    try:
        if timeout_sec > 0:
            timer.start()
        p.wait()
    finally:
        timer.cancel()

        if log_filename is not None:
            log_file.close()

    return p.returncode


class MutationGenerator(c_generator.CGenerator):
    def __init__(self, swap_nodes=None):
        self.swap_nodes = swap_nodes
        super().__init__()

    def visit(self, node):
        if node is self.swap_nodes[0]:
            if self.swap_nodes[1] is not None:
                return super().visit(self.swap_nodes[1])
            else:
                return ''
        else:
            return super().visit(node)


class Mutator:
    _MIN_RUN_TIME = 5
    _TIMEOUT_MULTIPLIER = 4

    def __init__(self, build_cmd, test_exe, mutate_file, inject_path, log_dir):
        self._build_cmd = build_cmd
        self._test_exe = test_exe
        self._orig_filename = mutate_file
        self._ast = pycparser.parse_file(self._orig_filename, use_cpp=True)
        self._inject_path = inject_path
        self._iteration = 0
        self._log_dir = log_dir
        self._run_timeout = 0
        self.build_failed = 0
        self.crashed = 0
        self.timed_out = 0
        self.caught = 0
        self.missed = 0
        self._gen_orig_filename = '{}/{}.orig'.format(self._log_dir,
                                                      self._orig_filename)

    @property
    def runs (self):
        return self.caught + self.missed + self.build_failed + self.crashed

    def __call__(self):
        if self._initial_run():
            self._visit(self._ast, None)

    def _visit(self, node, parent):
        # Skip nodes that aren't in the original file (i.e. are in headers)
        if node.coord is not None and node.coord.file != self._orig_filename:
            return

        method = getattr(self, 
                         '_visit_' + node.__class__.__name__,
                         self._generic_visit)
        method(node, parent)

        # Visit the children.
        for _, c in node.children():
            self._visit(c, node)

    def _generic_visit(self, node, parent):
        pass

    def _visit_Case(self, node, parent):
        # Find any breaks, and remove them.
        for b in _find_nodes(node, Break):
            self._test((b, None))

    def _visit_UnaryOp(self, node, parent):
        test = False

        if node.op == '!':
            self._test((node, node.expr))
        else:
            ops = _get_op_swaps(node.op,
                                [{'p++', 'p--', '++', '--'}])
            new_node = copy.copy(node)
            for op in ops:
                new_node.op = op
                self._test((node, new_node))

    def _visit_BinaryOp(self, node, parent):
        new_node = copy.copy(node)

        ops = _get_op_swaps(node.op,
                            [{'+', '-'},
                             {'<', '>', '<=', '>='},
                             {'<<', '>>'},
                             {'!=', '=='},
                             {'&', '&&'},
                             {'&', '|'},
                             {'&&', '||'},
                             {'<<', '>>'},
                             {'|=', '&='}])
        for op in ops:
            new_node.op = op
            self._test((node, new_node))

    def _iter_log_dirname(self):
        '''Return the log directory name for the current iteration.'''
        return self._log_dir + '/{}'.format(self._iteration)

    def _write_mutation(self, swap_nodes):
        ext = os.path.splitext(self._orig_filename)[1]
        with tempfile.NamedTemporaryFile(
                mode='w', suffix=ext, delete=False) as f:
            gen = MutationGenerator(swap_nodes)
            f.write(gen.visit(self._ast))
            return f.name

    def _build_mutation(self, mutation_filename):
        '''Build the test executable, with the mutated file subbed in.'''
        env_vars = {
            'LD_PRELOAD': self._inject_path,
            _ENV_ORIG_SRC: self._orig_filename,
            _ENV_MODIFIED_SRC: mutation_filename
        }
        rc = _run_process(cmd=self._build_cmd,
                          env_vars=env_vars,
                          log_filename=self._iter_log_dirname() + '/build.log')
        return rc == 0

    def _write_diff(self, mutation_filename):
        # TODO: Check if the diff executable exists etc?
        os.system('diff -c {} {} > {}/{}.diff'.format(
            self._gen_orig_filename,
            mutation_filename,
            self._iter_log_dirname(),
            self._orig_filename))

    def _run_mutation(self, mutation_str, coord):
        # TODO: Build the exe path correctly
        # TODO: Check for crashes
        try:
            run_log = '{}/{}.log'.format(self._iter_log_dirname(),
                                         self._test_exe)
            rc = _run_process(cmd='./' + self._test_exe,
                              log_filename=run_log,
                              timeout_sec=self._run_timeout)
        except TimeoutException:
            self.timed_out += 1
            result_str = 'timed out'
            log_fn = logging.error
        else:
            if rc == 0:
                self.missed += 1
                result_str = 'missed'
                log_fn = logging.error
            else:
                self.caught += 1
                result_str = 'caught'
                log_fn = logging.info

        log_fn('Run {}: {} {}, test output {} - {}'.format(
            self._iteration,
            coord,
            mutation_str,
            rc,
            result_str))

    def _test(self, swap_nodes, mutation_str=''):
        if mutation_str == '':
            if swap_nodes[1] is None:
                mutation_str = 'Remove {}'.format(_node_to_str(swap_nodes[0]))
            else:
                mutation_str = '"{}" -> "{}"'.format(
                    _node_to_str(swap_nodes[0]),
                    _node_to_str(swap_nodes[1]))

        # Create the log directory for this iteration, the calls below will
        # assume it exists.
        os.mkdir(self._iter_log_dirname())

        # Write the mutated AST to disk.
        mutation_filename = self._write_mutation(swap_nodes)

        # Build the test with the mutated file.
        build_success = self._build_mutation(mutation_filename)

        # Write out the diff before deleting the mutated file.
        self._write_diff(mutation_filename)
        os.system('rm {}'.format(mutation_filename))

        if not build_success:
            self.build_failed += 1
            logging.error('Run {}: {} {} - build failed'.format(
                self._iteration,
                swap_nodes[0].coord,
                mutation_str))
        else:
            self._run_mutation(mutation_str, swap_nodes[0].coord)

        self._iteration += 1

    def _initial_run(self):
        # Dump the unmutated C file from the AST so that we can diff the
        # mutations against it. If we just diffed against the file we parsed,
        # the diffs would contain layout changes between the original file
        # and the layout that the generator produces.
        with open(self._gen_orig_filename, 'w') as f:
            gen = c_generator.CGenerator()
            f.write(gen.visit(self._ast))

        build_log = self._log_dir + '/build.log.orig'
        rc = _run_process(cmd=self._build_cmd, log_filename=build_log)

        if rc == 0:
            # Time the unmutated run so that we can time out mutated runs that
            # have got stuck (e.g. a mutation leads to an infinite loop or
            # deadlock).
            start = time.time()

            # TODO: Build the exe path correctly
            run_log = self._log_dir + '/' + self._test_exe + '.log.orig'
            rc = _run_process(cmd='./' + self._test_exe,
                              log_filename=run_log)

            end = time.time()

            # Use a min run time - if a process runs very quickly we don't
            # mind waiting a bit longer.
            self._run_timeout = (Mutator._TIMEOUT_MULTIPLIER *
                                 max(Mutator._MIN_RUN_TIME, int(end - start)))


        return rc == 0

