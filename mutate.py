import pycparser
import copy
import os
import tempfile
import logging

from pycparser import c_generator
from pycparser.c_ast import BinaryOp


_ENV_PRELOAD_PREFIX = 'LD_PRELOAD=$PWD/inject.so'
_ENV_ORIG_SRC = 'MUTATE_ORIG_SRC'
_ENV_MODIFIED_SRC = 'MUTATE_MODIFIED_SRC'


def node_to_str (node):
    gen = c_generator.CGenerator()
    return gen.visit(node)

class Mutator:
    def __init__(self, build_cmd, test_exe, mutate_file):
        self._build_cmd = build_cmd
        self._test_exe = test_exe
        self._orig_filename= mutate_file
        self._ast = pycparser.parse_file(self._orig_filename)
        self._iteration = 0
        self.caught = 0
        self.missed = 0

    @property
    def runs (self):
        return self.caught + self.missed

    def __call__(self):
        self._visit(self._ast)

    def _visit(self, node):
        method = getattr(self, 
                         '_visit_' + node.__class__.__name__,
                         self._generic_visit)
        method(node)

    def _generic_visit(self, node):
        for _, c in node.children():
            self._visit(c)

    def _visit_BinaryOp(self, node):
        old_node_str = node_to_str(node)
        old_op = node.op

        # Find the set of mutations to perform on this op. We define
        # groups of operators that get swapped, and try each of the
        # operators in that group if the op we are looking at is in
        # the group.
        ops = set()
        op_swaps = [{'+', '-'}, {'<', '>', '<=', '>='}, {'!=', '=='}]
        for swap in op_swaps:
            if node.op in swap:
                ops |= swap - set(node.op)

        for op in ops:
            node.op = op
            self._test(node, old_node_str)

        node.op = old_op

        self._visit(node.left)
        self._visit(node.right)

    def _test(self, node, old_node_str):
        # Write the modified AST out to a file
        ext = os.path.splitext(self._orig_filename)[1]
        
        with tempfile.NamedTemporaryFile(
                mode='w', suffix=ext, delete=False) as f:
            gen = c_generator.CGenerator()
            f.write(gen.visit(self._ast))
            mutated_filename = f.name
            
        # TODO: Use subprocess rather than this
        # TODO: Timeout - mutation could lead to infinite loop
        # Build the test
        os.system('{} {}="{}" {}="{}" {}'.format(
            _ENV_PRELOAD_PREFIX,
            _ENV_ORIG_SRC, self._orig_filename,
            _ENV_MODIFIED_SRC, mutated_filename,
            self._build_cmd))

        # Run the test
        ret = os.system('./' + self._test_exe)
        if ret == 0:
            self.missed += 1
            result_str = 'missed'
        else:
            self.caught += 1
            result_str = 'caught'

        print('Run {}: {} "{}" -> "{}", test output {} - {}'.format(
            self._iteration,
            node.coord,
            old_node_str,
            node_to_str(node),
            ret,
            result_str)) 

        self._iteration += 1


if __name__ == '__main__':
    # TODO: Move this stuff to cmdline args
    _BUILD_CMD = 'gcc -o test example.c test.c'
    _MUTATE_SRC = 'example.c' 
    _TEST_EXE = 'test'
    mut = Mutator(_BUILD_CMD, _TEST_EXE, _MUTATE_SRC)
    mut()

    # Tidy up by executing a unmodified build
    os.system(_BUILD_CMD)

