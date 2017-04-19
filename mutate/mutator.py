import pycparser
import copy
import os
import tempfile
import logging

from pycparser import c_generator
from pycparser.c_ast import Break


_ENV_ORIG_SRC = 'MUTATE_ORIG_SRC'
_ENV_MODIFIED_SRC = 'MUTATE_MODIFIED_SRC'


def node_to_str (node):
    gen = c_generator.CGenerator()
    return gen.visit(node)

class Mutator:
    def __init__(self, build_cmd, test_exe, mutate_file, inject_path):
        self._build_cmd = build_cmd
        self._test_exe = test_exe
        self._orig_filename = mutate_file
        self._ast = pycparser.parse_file(self._orig_filename)
        self._inject_path = inject_path
        self._iteration = 0
        self.caught = 0
        self.missed = 0

    @property
    def runs (self):
        return self.caught + self.missed

    def __call__(self):
        self._visit(self._ast, None)

    def _visit(self, node, parent):
        method = getattr(self, 
                         '_visit_' + node.__class__.__name__,
                         self._generic_visit)
        method(node, parent)

        # Visit the children. Note that this provides individual node visit
        # functions with no control over whether the children are visited or
        # not, this is assumed to be OK for now but could move this into
        # each node visit function if required.
        for _, c in node.children():
            self._visit(c, node)

    def _generic_visit(self, node, parent):
        pass

    def _visit_Case(self, node, parent):
        # Find if there is a break, and remove it. Note that
        # in the case where there are multiple breaks, we will
        # remove them all.
        old_stmts = node.stmts
        node.stmts = [s for s in node.stmts if not isinstance(s, Break)]

        self._test(node, 'remove breaks from "case {}"'.format(
            node_to_str(node.expr)))
        node.stmts = old_stmts

    def _visit_UnaryOp(self, node, parent):
        test = False

        old_node_str = node_to_str(node)
        old_op = node.op

        if node.op == 'p++':
            node.op = 'p--'
            test = True
        elif node.op == 'p--':
            node.op = 'p++'
            test = True

        if test:
            self._test(node, '"{}" -> "{}"'.format(old_node_str,
                                                   node_to_str(node)))
        node.op = old_op

    def _visit_BinaryOp(self, node, parent):
        old_node_str = node_to_str(node)
        old_op = node.op

        # Find the set of mutations to perform on this op. We define
        # groups of operators that get swapped, and try each of the
        # operators in that group if the op we are looking at is in
        # the group.
        ops = set()
        op_swaps = [{'+', '-'},
                    {'<', '>', '<=', '>='},
                    {'<<', '>>'},
                    {'!=', '=='},
                    {'&', '&&'},
                    {'&', '|'},
                    {'&&', '||'},
                    {'<<', '>>'},
                    {'|=', '&='}]

        for swap in op_swaps:
            if node.op in swap:
                ops |= swap - set(node.op)

        for op in ops:
            node.op = op
            self._test(node, '"{}" -> "{}"'.format(old_node_str,
                                                   node_to_str(node)))

        node.op = old_op

    def _test(self, node, mutation_str):
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
        os.system('LD_PRELOAD={} {}="{}" {}="{}" {}'.format(
            self._inject_path,
            _ENV_ORIG_SRC, self._orig_filename,
            _ENV_MODIFIED_SRC, mutated_filename,
            self._build_cmd))

        # Remove the mutated C file
        os.system('rm {}'.format(mutated_filename))

        # Run the test
        ret = os.system('./' + self._test_exe)
        if ret == 0:
            self.missed += 1
            result_str = 'missed'
            log_fn = logging.error
        else:
            self.caught += 1
            result_str = 'caught'
            log_fn = logging.info

        log_fn('Run {}: {} {}, test output {} - {}'.format(
            self._iteration,
            node.coord,
            mutation_str,
            ret,
            result_str)) 

        self._iteration += 1
