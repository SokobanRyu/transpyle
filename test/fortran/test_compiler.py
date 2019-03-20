"""Tests for Fortran language support."""

import logging
import operator
import shutil
import types
import unittest

from encrypted_config.json_io import json_to_file
import numpy as np
import timing

from transpyle.general.code_reader import CodeReader
from transpyle.general.binder import Binder
from transpyle.fortran.compiler import F2PyCompiler

from test.common import \
    now_timestamp, EXAMPLES_F77_FILES, EXAMPLES_F95_FILES, make_f2py_tmp_folder, \
    execute_on_all_language_examples, execute_on_all_language_fundamentals

_LOG = logging.getLogger(__name__)

_TIME = timing.get_timing_group(__name__)


def random_data(shape=None, dtype=np.int):
    if shape is None:
        return dtype(np.random.rand() * 1000)
    return (np.random.rand(*shape) * 1000).astype(dtype)


class Tests(unittest.TestCase):

    @execute_on_all_language_examples('f77', 'f95')
    def test_compile_and_bind_examples(self, input_path):
        output_dir = make_f2py_tmp_folder(input_path)

        code_reader = CodeReader()
        code = code_reader.read_file(input_path)
        compiler = F2PyCompiler()
        with _TIME.measure('compile.{}'.format(input_path.name.replace('.', '_'))) as timer:
            output_path = compiler.compile(code, input_path, output_dir)
        binder = Binder()
        with binder.temporarily_bind(output_path) as binding:
            self.assertIsInstance(binding, types.ModuleType)
        _LOG.warning('compiled "%s" in %fs', input_path, timer.elapsed)

        output_path.unlink()
        try:
            output_dir.rmdir()
        except OSError:
            pass

    @execute_on_all_language_fundamentals('f77', 'f95')
    def test_run_fundamentals(self, input_path):
        output_dir = make_f2py_tmp_folder(input_path)

        code_reader = CodeReader()
        code = code_reader.read_file(input_path)

        compiler = F2PyCompiler()
        output_path = compiler.compile(code, input_path, output_dir)
        binder = Binder()
        with binder.temporarily_bind(output_path) as binding:
            self.assertIsInstance(binding, types.ModuleType)
            prefix = {'fundamentals': '', 'fundamentals_arrays': 'itemwise_'}[input_path.stem]
            shape = None if prefix == '' else (1024 * 1024,)
            for type_ in ('integer', 'real'):
                py_type = {'integer': int, 'real': float}[type_]
                input1 = random_data(shape, dtype=py_type)
                input2 = random_data(shape, dtype=py_type)
                for operation in ('add', 'subtract', 'multiply'):
                    py_operator = {'add': operator.add, 'subtract': operator.sub,
                                   'multiply': operator.mul}[operation]
                    expected = py_operator(input1, input2)
                    function_name = '{}{}_{}'.format(prefix, operation, type_)
                    function = getattr(binding, function_name)
                    with self.subTest(function=function_name):
                        with _TIME.measure('run.{}.{}.{}'.format(
                                input_path.name.replace('.', '_'), type_,
                                '{}{}'.format(prefix, operation))) as timer:
                            output = function(input1, input2)
                        _LOG.warning('ran %s from "%s" in %fs',
                                     function_name, input_path, timer.elapsed)
                        if type_ == 'integer':
                            self.assertTrue(np.all(np.equal(expected, output)),
                                            msg=(input1, input2, output, expected))
                        else:
                            self.assertTrue(np.allclose(expected, output, atol=1e-4),
                                            msg=(input1, input2, output, expected))

    def test_directives(self):
        # from transpyle.general.language import Language
        # from transpyle.general.transpiler import AutoTranspiler
        from test.common import EXAMPLES_ROOTS, PERFORMANCE_RESULTS_ROOT

        binder = Binder()
        compiler_f95 = F2PyCompiler()
        compiler_f95_omp = F2PyCompiler()
        compiler_f95_acc = F2PyCompiler()
        compiler_f95_acc.f2py.fortran_compiler_executable = 'pgfortran'
        # transpiler_py_to_f95 = AutoTranspiler(
        #    Language.find('Python 3'), Language.find('Fortran 95'))

        name = 'itemwise_calc'
        variants = {}
        # variants['py'] = (EXAMPLES_ROOTS['python3'].joinpath(name + '.py'), None)
        variants['f95'] = (
            compiler_f95.compile_file(EXAMPLES_ROOTS['f95'].joinpath(name + '.f90')), None)
        variants['f95_openmp'] = (
            compiler_f95_omp.compile_file(
                EXAMPLES_ROOTS['f95'].joinpath(name + '_openmp.f90')), None)
        if shutil.which(compiler_f95_acc.f2py.fortran_compiler_executable) is not None:
            variants['f95_openacc'] = (
                compiler_f95_acc.compile_file(
                    EXAMPLES_ROOTS['f95'].joinpath(name + '_openacc.f90')), None)
        # variants['py_to_f95'] = (transpiler_py_to_f95.transpile_file(variants['py'][0]), None)
        # variants['py_numba'] = (variants['py'][0], lambda f: numba.jit(f))
        # variants['numpy'] = (variants['py'][0], lambda f: np.copy)

        arrays = [np.array(np.random.random_sample((array_size,)), dtype=np.double)
                  for array_size in range(1024, 1024 * 64 + 1, 1024 * 4)]

        for variant, (path, transform) in variants.items():
            with binder.temporarily_bind(path) as binding:
                tested_function = getattr(binding, name)
                if transform:
                    tested_function = transform(tested_function)
                # import ipdb; ipdb.set_trace()
                for array in arrays:
                    with self.subTest(variant=variant, path=path, array_size=array.size):
                        # with _TIME.measure('{}.{}.{}'.format(name, segments, variant)):
                        for _ in _TIME.measure_many('run.{}.{}.{}'.format(
                                name, array.size, variant), 50):
                            results = tested_function(array)
                        # self.assertListEqual(array.tolist(), array_copy.tolist())
                        self.assertTrue(results.shape, array.shape)

        for array in arrays:
            timings_name = '.'.join([__name__, 'run', name, str(array.size)])
            summary = timing.query_cache(timings_name).summary
            _LOG.info('%s', summary)
            json_to_file(summary, PERFORMANCE_RESULTS_ROOT.joinpath(timings_name + '.json'))

    def test_openmp(self):
        for input_path in [_ for _ in EXAMPLES_F77_FILES + EXAMPLES_F95_FILES]:
            if input_path.name == 'matmul_openmp.f':
                break

        output_dir = make_f2py_tmp_folder(input_path)

        code_reader = CodeReader()
        code = code_reader.read_file(input_path)
        compiler = F2PyCompiler()
        binder = Binder()

        output_path = compiler.compile(code, input_path, output_dir, openmp=False)
        with binder.temporarily_bind(output_path) as binding:
            self.assertIsInstance(binding, types.ModuleType)
            with _TIME.measure('run.matmul.simple'):
                ret_val = binding.intmatmul(20, 1024, 1024)
        self.assertEqual(ret_val, 0)
        output_path.unlink()

        output_path = compiler.compile(code, input_path, output_dir, openmp=True)
        with binder.temporarily_bind(output_path) as binding:
            self.assertIsInstance(binding, types.ModuleType)
            with _TIME.measure('run..matmul.openmp'):
                ret_val = binding.intmatmul(20, 1024, 1024)
        self.assertEqual(ret_val, 0)
        _LOG.warning('%s', _TIME.summary)
        output_path.unlink()

        try:
            output_dir.rmdir()
        except OSError:
            pass
