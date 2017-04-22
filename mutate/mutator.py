import pycparser
import copy
import os
import tempfile
import logging
import copy

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

    def _test(self, swap_nodes, mutation_str=''):
        # Write the modified AST out to a file
        ext = os.path.splitext(self._orig_filename)[1]
        with tempfile.NamedTemporaryFile(
                mode='w', suffix=ext, delete=False) as f:
            gen = MutationGenerator(swap_nodes)
            f.write(gen.visit(self._ast))
            mutated_filename = f.name
            
        # TODO: Use subprocess rather than this
        # TODO: Check for build failures
        # Build the test
        os.system('LD_PRELOAD={} {}="{}" {}="{}" {}'.format(
            self._inject_path,
            _ENV_ORIG_SRC, self._orig_filename,
            _ENV_MODIFIED_SRC, mutated_filename,
            self._build_cmd))

        # Remove the mutated C file
        os.system('rm {}'.format(mutated_filename))

        # Run the test
        # TODO: Timeout - mutation could lead to infinite loop
        # TODO: Check for crashes.
        ret = os.system('./' + self._test_exe)
        if ret == 0:
            self.missed += 1
            result_str = 'missed'
            log_fn = logging.error
        else:
            self.caught += 1
            result_str = 'caught'
            log_fn = logging.info

        if mutation_str == '':
            if swap_nodes[1] is None:
                mutation_str = 'Remove {}'.format(_node_to_str(swap_nodes[0]))
            else:
                mutation_str = '"{}" -> "{}"'.format(
                    _node_to_str(swap_nodes[0]),
                    _node_to_str(swap_nodes[1]))

        log_fn('Run {}: {} {}, test output {} - {}'.format(
            self._iteration,
            swap_nodes[0].coord,
            mutation_str,
            ret,
            result_str)) 

        self._iteration += 1
